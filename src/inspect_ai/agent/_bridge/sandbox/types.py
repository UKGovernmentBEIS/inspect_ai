from collections import deque
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn, Sequence

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
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

    def register_tool_execution_grants(self, calls: Sequence[ToolCall]) -> None:
        """Add one-shot host-tool grants for the calls in a response handed to the scaffold.

        A host tool executes only for a call the model proposed in a bridged
        generation, once per proposal: `call_tool` consumes a matching grant
        before running the tool and denies a call without one, whether or not an
        approval policy is active. Each grant binds the exact bridged (server,
        tool) the call's model-facing function name denotes plus the arguments
        handed to the scaffold (as approved or approver-modified; JSON-normalized,
        since the scaffold re-sends them as parsed JSON). A name that denotes more
        than one bridged tool is ambiguous — no grant is registered (fail closed,
        with a warning). No grant is stored for a server in
        `proposal_exempt_servers`, since none is needed to execute its tools.

        A grant is not scoped to the turn it was proposed in: it persists until
        consumed (or evicted, with a warning, once `_MAX_TOOL_EXECUTION_GRANTS`
        unconsumed grants accumulate) — including when the response never
        reached the scaffold (serialization or transport failure) — but only ever
        authorizes the exact proposed action. A call carries no execution target,
        so a scaffold-local call whose name denotes a bridged tool also mints a
        grant for it — still bounded to its arguments.
        """
        for call in calls:
            targets = _resolve_bridged_tools(self.bridged_tools, call.function)
            if not targets:
                continue
            if len(targets) > 1:
                warn_once(
                    logger,
                    f"Tool call '{call.function}' denotes more than one "
                    "bridged tool; no execution grant registered (the call "
                    "will be denied). Use unique tool names across bridged "
                    "servers, or a qualified name ('mcp__<server>__<tool>').",
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
                    arguments=to_jsonable_python(dict(call.arguments), fallback=str),
                )
            )

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


def _candidate_functions(server: str, tool: str) -> tuple[str, ...]:
    """The names a scaffold could have declared this bridged tool as to its model.

    Scaffolds name MCP tools under their own scheme: the bare tool name (Codex
    CLI), Claude Code's ``mcp__<server>__<tool>``, Gemini CLI's
    ``mcp_<server>_<tool>`` (older releases: ``<server>__<tool>`` for conflicting
    names), and OpenCode's ``<server>_<tool>``. Each candidate is an exact string
    computed from the known (server, tool) — never parsed out of a call name — so
    an unrecognized scheme, or a name the scaffold rewrote (characters outside
    its identifier set, or a long name Gemini CLI truncates), matches nothing
    (deny-safe) rather than the wrong tool.
    """
    return (
        tool,
        f"mcp__{server}__{tool}",
        f"{server}__{tool}",
        f"mcp_{server}_{tool}",
        f"{server}_{tool}",
    )


class _BridgedToolId(NamedTuple):
    """Identity of one bridged tool within the registry."""

    server: str
    tool: str


def _resolve_bridged_tools(
    bridged_tools: dict[str, dict[str, Tool]], function: str
) -> list[_BridgedToolId]:
    """Every bridged (server, tool) a call's function name could denote."""
    return [
        _BridgedToolId(server=server, tool=tool)
        for server, tools in bridged_tools.items()
        for tool in tools
        if function in _candidate_functions(server, tool)
    ]


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
