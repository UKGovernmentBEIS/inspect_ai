from collections import deque
from copy import deepcopy
from dataclasses import replace
from logging import getLogger
from os.path import commonprefix
from typing import TYPE_CHECKING, Any, Callable, Mapping, NamedTuple, NoReturn, Sequence

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.json import json_equal
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge, DispatchedCall, ReviewedCall
from inspect_ai.model._call_tools import (
    ValidatedToolCall,
    approved_modification,
    get_tools_info,
    validated_tool_call,
)
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import (
    GenerateFilter,
    Model,
    ModelEventSink,
    ModelResolver,
)
from inspect_ai.tool import Tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._checkpoint.checkpointer import Checkpointer

if TYPE_CHECKING:
    # deferred: importing `inspect_ai.approval` at module scope here cycles
    # through approval -> event -> scorer while `inspect_ai.agent` is still
    # initializing. Same reason `model/_call_tools.py` defers it.
    from inspect_ai.approval._policy import ApprovalPolicy


logger = getLogger(__name__)

_MAX_TOOL_EXECUTION_GRANTS = 1024


class SandboxAgentBridge(AgentBridge):
    """Sandbox agent bridge."""

    def __init__(
        self,
        state: AgentState,
        filter: GenerateFilter | None,
        retry_refusals: int | None,
        compaction: CompactionStrategy | None,
        port: int,
        model: str | None,
        model_aliases: dict[str, str | Model] | None = None,
        mcp_server_configs: list[MCPServerConfigHTTP] | None = None,
        bridged_tools: dict[str, dict[str, Tool]] | None = None,
        proposal_exempt_servers: set[str] | None = None,
        model_event_sink: ModelEventSink | None = None,
        forward_generation_config: bool = False,
        approval: list["ApprovalPolicy"] | None = None,
        checkpointer: Checkpointer | None = None,
        allow_remote_mcp: bool = False,
        allow_remote_media: bool = False,
        model_resolver: ModelResolver | None = None,
    ) -> None:
        super().__init__(
            state,
            filter,
            retry_refusals,
            compaction,
            model=model,
            model_aliases=model_aliases,
            model_event_sink=model_event_sink,
            forward_generation_config=forward_generation_config,
            approval=approval,
            checkpointer=checkpointer,
            allow_remote_mcp=allow_remote_mcp,
            allow_remote_media=allow_remote_media,
            model_resolver=model_resolver,
        )
        self.port = port
        self.mcp_server_configs = mcp_server_configs or []
        self.bridged_tools = {}
        self.served_tools = {}
        self.proposal_exempt_servers = proposal_exempt_servers or set()
        for server, tools in (bridged_tools or {}).items():
            self.register_bridged_tools(server, tools)
        self._tool_execution_grants: deque[_ToolExecutionGrant] = deque(
            maxlen=_MAX_TOOL_EXECUTION_GRANTS
        )
        self._failure_requested = anyio.Event()
        self._approved_preparations: dict[tuple[int, str, str], ValidatedToolCall] = {}
        self._failure: Exception | None = None

    port: int
    """Model proxy server port."""

    mcp_server_configs: list[MCPServerConfigHTTP]
    """MCP server configs for bridged tools (resolved from bridged_tools parameter)."""

    bridged_tools: dict[str, dict[str, Tool]]
    """Registry of bridged tools by server name, then tool name."""

    served_tools: dict["_BridgedToolId", ToolInfo]
    """What `list_tools` serves the scaffold for each bridged tool.

    The same `get_tools_info` view the service returns, so a scaffold's
    declaration can be matched to the tool by the description it was given.
    """

    proposal_exempt_servers: set[str]
    """Bridged servers registered with `BridgedToolsSpec(require_proposal=False)`.

    Their tools execute without an execution grant, so for them the bridge does
    not guarantee that a host tool runs only for a call the model proposed.
    """

    grants_tool_execution = True
    """Host tools run only against a grant minted here from a response."""

    def register_bridged_tools(
        self, server: str, tools: dict[str, Tool], require_proposal: bool = True
    ) -> None:
        """Register `tools` (by name) as bridged server `server`."""
        self.bridged_tools[server] = tools
        for info in get_tools_info(list(tools.values())):
            self.served_tools[_BridgedToolId(server=server, tool=info.name)] = info
        if not require_proposal:
            self.proposal_exempt_servers.add(server)

    def record_approved_preparations(
        self, prepared: Mapping[tuple[int, str, str], ValidatedToolCall]
    ) -> None:
        """Hold the calls approval prepared for `register_tool_execution_grants`."""
        self._approved_preparations = dict(prepared)

    def reviewed_modification(
        self,
        call: ToolCall,
        reviewed: ReviewedCall,
        selected: dict[str, Any],
        declared: dict[str, list[ToolInfo]],
    ) -> ReviewedCall:
        """Prepare a host tool's modified call (`approved_modification()`)."""
        if (
            reviewed.target is None
            or reviewed.prepared is None
            or reviewed.source is None
        ):
            return super().reviewed_modification(call, reviewed, selected, declared)
        tool_def = ToolDef(self.bridged_tools[reviewed.target[0]][reviewed.target[1]])
        prepared = approved_modification(
            reviewed.source,
            reviewed.prepared,
            replace(reviewed.source, arguments=deepcopy(selected)),
            tool_def,
        )
        return reviewed._replace(call=prepared.call, prepared=prepared)

    def register_tool_execution_grants(
        self, calls: Sequence[ToolCall], tools: Sequence[ToolInfo | Tool]
    ) -> None:
        """Add one-shot host-tool grants for the calls in a response handed to the scaffold.

        `call_tool` consumes a matching grant before running a host tool and
        denies a call without one, with or without an approval policy. A grant
        binds the bridged (server, tool) the call denotes (`_proposed_call`,
        resolved against `tools`, the declarations the scaffold made to the model)
        and the arguments handed to the scaffold, JSON-normalized since the
        scaffold re-sends them as parsed JSON. A call denoting several bridged
        tools (a shared description; `warn_indistinct_tools` names them at setup)
        gets one grant for each. No grant is stored for a server in
        `proposal_exempt_servers`.

        A grant also carries the host tool's prepared call, which is what runs:
        the one approval reviewed (`record_approved_preparations`, by the call's
        position in the response and its target), or one prepared here from its
        own copy of the arguments for a call no approval reviewed. The tool is
        not prepared again at execution, so a model whose construction varies
        (a `default_factory`, a stateful validator) runs as approved.

        A grant persists until consumed or evicted (with a warning, once
        `_MAX_TOOL_EXECUTION_GRANTS` unconsumed grants accumulate), including when
        the response never reached the scaffold, but only ever authorizes the
        exact proposed action.
        """
        declared: dict[str, list[ToolInfo]] = {}
        for tool in tools:
            if isinstance(tool, ToolInfo):
                declared.setdefault(tool.name, []).append(tool)
        prepared = self._approved_preparations
        self._approved_preparations = {}
        for index, call in enumerate(calls):
            targets, arguments = _proposed_call(
                self.bridged_tools, self.served_tools, call, declared
            )
            if len(targets) > 1:
                warn_once(
                    logger,
                    f"Tool call '{call.function}' denotes several bridged tools "
                    "sharing a description ("
                    + ", ".join(f"{t.server}/{t.tool}" for t in targets)
                    + "); an execution grant was registered for each of them.",
                )
            for target in targets:
                if target.server in self.proposal_exempt_servers:
                    continue
                target_prepared = prepared.get(
                    (index, target.server, target.tool)
                ) or _prepared_host_call(
                    self.bridged_tools[target.server][target.tool],
                    target.tool,
                    arguments,
                )
                if (
                    len(self._tool_execution_grants)
                    == self._tool_execution_grants.maxlen
                ):
                    warn_once(
                        logger,
                        "Bridged tool execution grants exceeded "
                        f"{_MAX_TOOL_EXECUTION_GRANTS}; evicting the oldest "
                        "unconsumed grant. A proposed-but-never-executed call "
                        "that old can no longer be executed.",
                    )
                self._tool_execution_grants.append(
                    _ToolExecutionGrant(
                        server=target.server,
                        tool=target.tool,
                        arguments=to_jsonable_python(arguments, fallback=str),
                        prepared=target_prepared,
                    )
                )

    def warn_indistinct_tools(self) -> None:
        """Warn the eval author about bridged tools a proposal cannot single out.

        Run once, after every `BridgedToolsSpec` is registered and before the
        service starts, so the collision is visible at setup rather than at the
        first call. Two or more bridged tools with the same served description
        (whitespace-trimmed, so empty descriptions collide too) are each granted
        by a proposal for any of them (`register_tool_execution_grants`).
        """
        by_description: dict[str, list[_BridgedToolId]] = {}
        for tool_id, info in self.served_tools.items():
            by_description.setdefault(info.description.strip(), []).append(tool_id)
        for tool_ids in by_description.values():
            if len(tool_ids) > 1:
                names = ", ".join(f"{t.server}/{t.tool}" for t in tool_ids)
                logger.warning(
                    f"Bridged tools sharing a description ({names}): a proposal "
                    "for one of them grants each of them one execution. Give "
                    "them distinct docstrings to restore one-to-one matching."
                )

    def consume_tool_execution_grant(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> "_ToolExecutionGrant | None":
        """Consume and return one grant binding this exact (server, tool), if present.

        Arguments match by JSON semantics (`json_equal`): key order and
        int/float numeric equality (`5 == 5.0`) don't matter, so a scaffold's
        JSON round-trip cannot turn a proposed call into a denial; any other
        difference (including bool vs number) is denied.
        """
        for index, grant in enumerate(self._tool_execution_grants):
            if (
                grant.server == server
                and grant.tool == tool
                and json_equal(grant.arguments, arguments)
            ):
                del self._tool_execution_grants[index]
                return grant
        return None

    def dispatched_call(self, call: ToolCall) -> DispatchedCall | None:
        """The bridged tool call `call` makes through a dispatcher (`_dispatched_call`)."""
        return _dispatched_call(self.bridged_tools, call)

    def reviewed_calls(
        self, call: ToolCall, declared: dict[str, list[ToolInfo]]
    ) -> list[ReviewedCall]:
        """Review a call denoting bridged host tools as each will run it.

        The host tools are resolved as for execution grants (`_proposed_call`),
        except that a dispatcher call needs no declaration (as before). Each is
        reviewed with the host tool's validated, canonical arguments
        (`validated_tool_call()`) and its viewer, under the scaffold's function
        name for a call matched by its declaration and under the target's name
        for a dispatcher call. Any other call is reviewed as the base class does.

        Raises:
            ToolParsingError: The arguments are not valid for a host tool it
                denotes, or for the scaffold's declaration.
        """
        declarations = declared.get(call.function)
        targets = (
            _resolve_by_served_content(self.served_tools, declarations)
            if declarations
            else []
        )
        if targets:
            return [
                _reviewed_host_call(
                    call,
                    self.bridged_tools[target.server][target.tool],
                    None,
                    target,
                )
                for target in targets
            ]
        dispatched = self.dispatched_call(call)
        if dispatched is not None:
            target = _BridgedToolId(
                server=dispatched.server, tool=dispatched.target.function
            )
            tool = self.bridged_tools[target.server][target.tool]
            return [
                _reviewed_host_call(
                    dispatched.target, tool, dispatched.dispatch, target
                )
            ]
        return super().reviewed_calls(call, declared)

    def request_fail(self, error: Exception) -> None:
        """Fail the sample with `error` from a bridged generation or tool call.

        A sandbox bridge's generations and host tool calls run in the sandbox
        service task, where `_handle_request` turns exceptions into RPC error
        responses rather than letting them propagate (only `LimitExceededError`
        is special-cased). So raising from one would never reach the sample
        runner.

        Instead, store the error and signal the monitor task in
        `sandbox_agent_bridge`'s task group, which raises it on the agent's side
        and tears the sample down. This does not raise itself: the caller decides
        how the current RPC unwinds (`request_terminate` raises, and the model
        service returns a provider error payload so the sandboxed agent gets a
        reply rather than blocking on one that will never come). The first error
        requested wins; later requests are ignored.
        """
        if self._failure is None:
            self._failure = error
        self._failure_requested.set()

    def request_terminate(self, reason: str) -> NoReturn:
        """Terminate the sample from a bridged generation.

        Signals the sample failure via `request_fail` (see there for why a plain
        raise would not reach the sample runner) and raises so the current RPC
        unwinds with an error response.
        """
        error = TerminateSampleError(reason)
        self.request_fail(error)
        raise error


class _ToolExecutionGrant(NamedTuple):
    """Identity of one host tool execution the model proposed."""

    server: str
    """Bridged server the grant is bound to."""

    tool: str
    """Tool name within the bridged server."""

    arguments: dict[str, Any]
    """The arguments handed to the scaffold, JSON-normalized and matched via `json_equal`."""

    prepared: ValidatedToolCall | None
    """The host tool's prepared call, which the execution runs (None when the
    arguments are invalid for the tool; the service reports the parsing error)."""


class _BridgedToolId(NamedTuple):
    """Identity of one bridged tool within the registry."""

    server: str
    tool: str


class _ProposedCall(NamedTuple):
    """What a proposed call would execute: the bridged tools it could denote, with what."""

    targets: list[_BridgedToolId]
    arguments: dict[str, Any]


_NO_PROPOSAL = _ProposedCall([], {})


def _proposed_call(
    bridged_tools: dict[str, dict[str, Tool]],
    served: dict[_BridgedToolId, ToolInfo],
    call: ToolCall,
    declared: dict[str, list[ToolInfo]],
) -> _ProposedCall:
    """Resolve a proposed call to the bridged tools it denotes and its arguments.

    Scaffolds rename MCP tools to their models under their own schemes, so the
    called name is ignored. `declared` are the tools the scaffold declared to the
    model in this request, by name; a call to a name the scaffold never declared
    denotes nothing. The call's declaration is matched to a bridged tool by the
    content the bridge served for it in `tools/list`
    (`_resolve_by_served_content`); when nothing matches, the call may be a
    dispatcher call, recognised by its function name and argument shape
    (`_dispatched_call`), denoting the bridged tool its arguments name.
    """
    declarations = declared.get(call.function)
    if not declarations:
        return _NO_PROPOSAL
    targets = _resolve_by_served_content(served, declarations)
    if targets:
        return _ProposedCall(targets, dict(call.arguments))
    dispatched = _dispatched_call(bridged_tools, call)
    if dispatched is None:
        return _NO_PROPOSAL
    return _ProposedCall(
        [_BridgedToolId(server=dispatched.server, tool=dispatched.target.function)],
        dispatched.target.arguments,
    )


def _resolve_by_served_content(
    served: dict[_BridgedToolId, ToolInfo], declarations: Sequence[ToolInfo]
) -> list[_BridgedToolId]:
    """The bridged tools a declaration denotes by what the bridge served for them.

    The description is the key: the scaffolds forward the MCP description to
    their models unchanged (verified per scaffold in the PR), so equality after
    trimming whitespace identifies the tool whatever name it was given; an empty
    description is matched like any other, so it identifies every bridged tool
    served without one. Failing an exact match, a declaration that is a
    truncation of a served description identifies it too
    (`_is_truncation_of`), since a scaffold may cut a long description before
    the model sees it. Schemas are not consulted: scaffolds rewrite them. Tools
    that cannot be told apart are all returned, and the caller grants each. An
    exact match wins even when that description is a prefix of another bridged
    tool's; a truncated declaration which could refer to both denotes both.
    """
    targets: list[_BridgedToolId] = []
    for declaration in declarations:
        description = declaration.description.strip()
        matched = [
            tool_id
            for tool_id, info in served.items()
            if info.description.strip() == description
        ] or [
            tool_id
            for tool_id, info in served.items()
            if _is_truncation_of(description, info.description.strip())
        ]
        targets.extend(tool_id for tool_id in matched if tool_id not in targets)
    return targets


_MIN_TRUNCATED_PREFIX = 64
"""Shortest declared text accepted as a truncation of a served description.

Longer than inspect's shortest built-in tool descriptions (`bash`, 43
characters; `text_editor`, 51) and far below any scaffold's truncation limit
(the one known, Claude Code's, is 2048), so a genuine truncation always
qualifies while a short description can never match another tool's as an
accidental prefix.
"""

_MAX_TRUNCATION_MARKER = 24
"""Longest tail a truncating scaffold is assumed to append (``… [truncated]``)."""


def _is_truncation_of(declared: str, served: str) -> bool:
    """Whether a declared description is a served description cut short.

    Scaffold-agnostic: no scaffold's marker is looked for. The two texts must
    agree for at least `_MIN_TRUNCATED_PREFIX` characters, and whatever the
    declared text carries beyond that common prefix (an ellipsis, ``[...]``,
    ``… [truncated]``) must be at most `_MAX_TRUNCATION_MARKER` characters. A
    scaffold that rewrites the leading text is not tolerated.
    """
    common = len(commonprefix([declared, served]))
    return (
        common >= _MIN_TRUNCATED_PREFIX
        and len(declared) - common <= _MAX_TRUNCATION_MARKER
    )


def _dispatched_call(
    bridged_tools: dict[str, dict[str, Tool]], call: ToolCall
) -> DispatchedCall | None:
    """The bridged tool call a dispatcher call stands for, if it is one.

    Some scaffolds expose every MCP tool through one function whose arguments
    name the target. The one such shape in the wild is Antigravity's
    ``call_mcp_tool(ServerName, ToolName, Arguments)``: string ``ServerName`` and
    ``ToolName`` naming a registered bridged tool and an object ``Arguments``
    denote that tool with those arguments. Anything else is not a dispatched call
    and is reviewed as the call it is: a dispatcher with another name or other
    parameter names, a target that is not a bridged tool, and in particular an
    ordinary call whose own arguments happen to carry these fields (the function
    name is checked first, so no other tool's call can borrow a bridged tool's
    policy, or mint an execution grant for it, by naming it in its arguments).
    Both approval (`SandboxAgentBridge.dispatched_call`) and grant resolution
    (`_proposed_call`) recognise a dispatcher call through this one function, so
    they cannot disagree about what is one.
    """
    if call.function != "call_mcp_tool":
        return None
    server = call.arguments.get("ServerName")
    tool = call.arguments.get("ToolName")
    arguments = call.arguments.get("Arguments")
    if (
        isinstance(server, str)
        and isinstance(tool, str)
        and isinstance(arguments, dict)
        and tool in bridged_tools.get(server, {})
    ):
        return DispatchedCall(
            server=server,
            target=ToolCall(id=call.id, function=tool, arguments=arguments),
            dispatch=lambda modified: {**call.arguments, "Arguments": modified},
        )
    return None


def _reviewed_host_call(
    call: ToolCall,
    tool: Tool,
    dispatch: Callable[[dict[str, Any]], dict[str, Any]] | None,
    target: _BridgedToolId,
) -> ReviewedCall:
    """`call` as `tool` will run it, for approval (raises `ToolParsingError`).

    Prepared from its own copy of the arguments, so a target sharing the
    proposal with others cannot change what another runs.
    """
    tool_def = ToolDef(tool)
    source = replace(call, arguments=deepcopy(call.arguments))
    prepared = validated_tool_call(source, tool_def)
    return ReviewedCall(
        prepared.call,
        tool_def.viewer,
        dispatch,
        (target.server, target.tool),
        prepared,
        source,
    )


def _prepared_host_call(
    tool: Tool, name: str, arguments: dict[str, Any]
) -> ValidatedToolCall | None:
    """The host tool's prepared call for (a copy of) `arguments`, or None if invalid."""
    call = ToolCall(id="", function=name, arguments=deepcopy(arguments))
    try:
        return validated_tool_call(call, ToolDef(tool))
    except ToolParsingError:
        return None
