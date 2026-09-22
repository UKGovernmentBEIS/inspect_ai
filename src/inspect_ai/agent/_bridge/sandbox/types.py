import re
from collections import deque
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn, Sequence

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge, DispatchedCall
from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import (
    GenerateFilter,
    Model,
    ModelEventSink,
    ModelResolver,
)
from inspect_ai.tool import Tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool_call import ToolCall
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
        self.bridged_tools = bridged_tools or {}
        self.proposal_exempt_servers = proposal_exempt_servers or set()
        self._served_tool_info: dict[_BridgedToolId, ToolInfo] = {}
        self._tool_execution_grants: deque[_ToolExecutionGrant] = deque(
            maxlen=_MAX_TOOL_EXECUTION_GRANTS
        )
        self._failure_requested = anyio.Event()
        self._failure: Exception | None = None

    port: int
    """Model proxy server port."""

    mcp_server_configs: list[MCPServerConfigHTTP]
    """MCP server configs for bridged tools (resolved from bridged_tools parameter)."""

    bridged_tools: dict[str, dict[str, Tool]]
    """Registry of bridged tools by server name, then tool name."""

    proposal_exempt_servers: set[str]
    """Bridged servers registered with `BridgedToolsSpec(require_proposal=False)`.

    Their tools execute without an execution grant, so for them the bridge does
    not guarantee that a host tool runs only for a call the model proposed.
    """

    grants_tool_execution = True
    """Host tools run only against a grant minted here from a response."""

    def register_tool_execution_grants(
        self, calls: Sequence[ToolCall], tools: Sequence[ToolInfo | Tool]
    ) -> None:
        """Add one-shot host-tool grants for the calls in a response handed to the scaffold.

        A host tool executes only for a call the model proposed in a bridged
        generation, once per proposal: `call_tool` consumes a matching grant
        before running the tool and denies a call without one, whether or not an
        approval policy is active. Each grant binds the exact bridged (server,
        tool) the call denotes plus the arguments handed to the scaffold (as
        approved or approver-modified; JSON-normalized, since the scaffold
        re-sends them as parsed JSON). The call is resolved against `tools`, the
        declarations the scaffold made to the model in this request, by the
        content the bridge itself served in `tools/list` (`_proposed_call`): a
        call the scaffold declared no tool for denotes nothing; otherwise its
        declaration is matched to a bridged tool by description, then by input
        schema shape, whatever the scaffold renamed the tool to; failing that, a
        dispatcher call (Antigravity's ``call_mcp_tool``, recognised by that
        function name and its argument shape, `_dispatched_call`) denotes the
        bridged tool its arguments name. A call that still denotes more
        than one bridged tool (they share a description the schema shape cannot
        separate; `warn_indistinct_tools` names them at setup) gets a grant for
        each of them, all bound to the call's arguments, so the scaffold's
        `tools/call` to whichever it targets is authorized once; the price, one
        proposal authorizing one execution of each same-described tool, is
        bounded by the argument binding and the one-shot rule. No grant is
        stored for a server in `proposal_exempt_servers`, since none is needed to
        execute its tools.

        A grant is not scoped to the turn it was proposed in: it persists until
        consumed (or evicted, with a warning, once `_MAX_TOOL_EXECUTION_GRANTS`
        unconsumed grants accumulate) — including when the response never
        reached the scaffold (serialization or transport failure) — but only ever
        authorizes the exact proposed action.
        """
        declared: dict[str, list[ToolInfo]] = {}
        for tool in tools:
            if isinstance(tool, ToolInfo):
                declared.setdefault(tool.name, []).append(tool)
        for call in calls:
            targets, arguments = _proposed_call(
                self.bridged_tools, self._served_tools(), call, declared
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
                    )
                )

    def warn_indistinct_tools(self) -> None:
        """Warn the eval author about bridged tools a proposal cannot single out.

        Run once, after every `BridgedToolsSpec` is registered and before the
        service starts, so the collision is visible at setup rather than at the
        first call. Two or more bridged tools with the same served description
        (whitespace-trimmed) are each granted by a proposal for any of them
        (`register_tool_execution_grants`). An empty description (once trimmed)
        is matched like any other, so such a tool is indistinguishable from every
        other undocumented tool, bridged or agent-local.
        """
        by_description: dict[str, list[_BridgedToolId]] = {}
        for tool_id, info in self._served_tools().items():
            by_description.setdefault(info.description.strip(), []).append(tool_id)
        for description, tool_ids in by_description.items():
            names = ", ".join(f"{t.server}/{t.tool}" for t in tool_ids)
            if not description:
                logger.warning(
                    f"Bridged tool(s) with an empty description ({names}): an "
                    "empty docstring makes a tool indistinguishable from any "
                    "other undocumented tool, so a proposal for one grants each "
                    "of them. Give them a docstring."
                )
            elif len(tool_ids) > 1:
                logger.warning(
                    f"Bridged tools sharing a description ({names}): a proposal "
                    "for one of them grants each of them one execution. Give "
                    "them distinct docstrings to restore one-to-one matching."
                )

    def _served_tools(self) -> dict["_BridgedToolId", ToolInfo]:
        """What `list_tools` served the scaffold for each bridged tool, memoized.

        The same `get_tools_info` view the service returns, so a scaffold's
        declaration can be matched to the tool by the description and schema it
        was given. Registrations do not change after the bridge starts.
        """
        for server, tools in self.bridged_tools.items():
            for tool, tool_fn in tools.items():
                tool_id = _BridgedToolId(server=server, tool=tool)
                if tool_id not in self._served_tool_info:
                    self._served_tool_info[tool_id] = get_tools_info([tool_fn])[0]
        return self._served_tool_info

    def consume_tool_execution_grant(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> bool:
        """Consume one grant binding this exact (server, tool), if present.

        Arguments match by JSON semantics (`_json_equal`): key order and
        int/float numeric equality (`5 == 5.0`) don't matter, so a scaffold's
        JSON round-trip cannot turn a proposed call into a denial; any other
        difference (including bool vs number) is denied.
        """
        for index, grant in enumerate(self._tool_execution_grants):
            if (
                grant.server == server
                and grant.tool == tool
                and _json_equal(grant.arguments, arguments)
            ):
                del self._tool_execution_grants[index]
                return True
        return False

    def dispatched_call(self, call: ToolCall) -> DispatchedCall | None:
        """The bridged tool call `call` makes through a dispatcher (`_dispatched_call`)."""
        return _dispatched_call(self.bridged_tools, call)

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
    """The arguments handed to the scaffold, JSON-normalized and matched via `_json_equal`."""


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
    the model sees it. When several bridged tools match, the input schema breaks
    the tie, conservatively: scaffolds do rewrite schemas, so only property and
    required names are compared, as a subset (`_same_schema_shape`). Tools that
    still cannot be told apart are all returned, and the caller grants each. An
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
        if len(matched) > 1:
            shaped = [
                tool_id
                for tool_id in matched
                if _same_schema_shape(served[tool_id], declaration)
            ]
            if shaped:
                matched = shaped
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

_TRAILING_BRACKETED = re.compile(r"[(\[][^()\[\]]{1,24}[)\]]$")


def _strip_trailing_non_alnum(text: str, keep: str = "") -> str:
    """Drop the trailing characters that are neither alphanumeric nor in `keep`.

    Alphanumeric by `str.isalnum`, so letters of any script count as text.
    """
    end = len(text)
    while end and not text[end - 1].isalnum() and text[end - 1] not in keep:
        end -= 1
    return text[:end]


def _is_truncation_of(declared: str, served: str) -> bool:
    """Whether a declared description is a served description cut short.

    Scaffold-agnostic: no scaffold's marker is looked for. A trailing run of
    non-alphanumeric characters (an ellipsis, ``...``) and at most one short
    bracketed suffix (``[truncated]``, ``[...]``) are dropped, then the rest must
    be at least `_MIN_TRUNCATED_PREFIX` characters and a prefix of the served
    text. Alphanumeric means `str.isalnum`, so a non-Latin suffix is text, not a
    marker. A scaffold that rewrites the leading text is not tolerated.
    """
    prefix = _strip_trailing_non_alnum(declared, keep=")]")
    prefix = _TRAILING_BRACKETED.sub("", prefix)
    prefix = _strip_trailing_non_alnum(prefix)
    return len(prefix) >= _MIN_TRUNCATED_PREFIX and served.startswith(prefix)


def _same_schema_shape(served: ToolInfo, declaration: ToolInfo) -> bool:
    """Whether a declaration's input schema could be the served one, by shape.

    Scaffolds rewrite schemas for their model APIs: types and formats are
    rewritten or dropped, and Gemini CLI adds a ``wait_for_previous`` property to
    every object schema. So only names are compared, and only as a subset: every
    served property and required name must appear in the declaration.
    """
    return set(served.parameters.properties) <= set(
        declaration.parameters.properties
    ) and set(served.parameters.required) <= set(declaration.parameters.required)


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


def _json_equal(a: Any, b: Any) -> bool:
    """Equality by JSON semantics: 5 == 5.0, but True != 1 (unlike Python `==`)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(v, b[k]) for k, v in a.items())
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and bool(a == b)
