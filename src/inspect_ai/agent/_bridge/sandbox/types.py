from collections import deque
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn, Sequence

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
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
        dispatcher call whose arguments name a bridged server and tool
        (Antigravity's shape) denotes that tool. A call that still denotes more
        than one bridged tool is ambiguous — no grant is registered (fail closed,
        with a warning). No grant is stored for a server in
        `proposal_exempt_servers`, since none is needed to execute its tools.

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
            if not targets:
                continue
            if len(targets) > 1:
                warn_once(
                    logger,
                    f"Tool call '{call.function}' matches more than one "
                    "bridged tool by served description and schema; no "
                    "execution grant registered (the call will be denied). "
                    "Give bridged tools distinct descriptions.",
                )
                continue
            target = targets[0]
            if target.server in self.proposal_exempt_servers:
                continue
            if len(self._tool_execution_grants) == self._tool_execution_grants.maxlen:
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

    def request_fail(self, error: Exception) -> None:
        """Fail the sample with `error` from a bridged generation.

        A sandbox bridge's generations run in the sandbox service task, where
        `_handle_request` turns exceptions into RPC error responses rather than
        letting them propagate (only `LimitExceededError` is special-cased). So
        raising from a generation would never reach the sample runner.

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
    dispatcher call naming its target in its arguments (`_dispatched_call`).
    """
    declarations = declared.get(call.function)
    if not declarations:
        return _NO_PROPOSAL
    targets = _resolve_by_served_content(served, declarations)
    if targets:
        return _ProposedCall(targets, dict(call.arguments))
    return _dispatched_call(bridged_tools, call)


def _resolve_by_served_content(
    served: dict[_BridgedToolId, ToolInfo], declarations: Sequence[ToolInfo]
) -> list[_BridgedToolId]:
    """The bridged tools a declaration denotes by what the bridge served for them.

    The description is the key: the scaffolds forward the MCP description to
    their models unchanged (verified per scaffold in the PR), so equality after
    trimming whitespace identifies the tool whatever name it was given. An empty
    description identifies nothing. When several bridged tools share a
    description, the input schema breaks the tie, conservatively: scaffolds do
    rewrite schemas, so only property and required names are compared, as a
    subset (`_same_schema_shape`). Tools that still cannot be told apart are all
    returned, and the caller fails closed on more than one.
    """
    targets: list[_BridgedToolId] = []
    for declaration in declarations:
        description = declaration.description.strip()
        if not description:
            continue
        described = [
            tool_id
            for tool_id, info in served.items()
            if info.description.strip() == description
        ]
        if len(described) > 1:
            shaped = [
                tool_id
                for tool_id in described
                if _same_schema_shape(served[tool_id], declaration)
            ]
            if shaped:
                described = shaped
        targets.extend(tool_id for tool_id in described if tool_id not in targets)
    return targets


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
) -> _ProposedCall:
    """The bridged tool call a dispatcher call stands for, if it is one.

    Some scaffolds expose every MCP tool through one function whose arguments
    name the target, so the call's declaration carries the scaffold's own
    description and matches no bridged tool by content. The one such shape in
    the wild is Antigravity's ``call_mcp_tool(ServerName, ToolName, Arguments)``:
    string ``ServerName`` and ``ToolName`` naming a registered bridged tool and an
    object ``Arguments`` denote that tool with those arguments. A dispatcher with
    other parameter names is unsupported, and its calls are denied.
    """
    server = call.arguments.get("ServerName")
    tool = call.arguments.get("ToolName")
    arguments = call.arguments.get("Arguments")
    if (
        isinstance(server, str)
        and isinstance(tool, str)
        and isinstance(arguments, dict)
        and tool in bridged_tools.get(server, {})
    ):
        return _ProposedCall([_BridgedToolId(server=server, tool=tool)], arguments)
    return _NO_PROPOSAL


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
