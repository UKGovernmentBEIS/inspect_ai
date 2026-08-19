from collections import deque
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn, Sequence

import anyio

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import GenerateFilter, Model, ModelEventSink
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
        model_event_sink: ModelEventSink | None = None,
        forward_generation_config: bool = False,
        approval: list["ApprovalPolicy"] | None = None,
        checkpointer: Checkpointer | None = None,
        allow_remote_mcp: bool = False,
        allow_remote_media: bool = False,
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
        )
        self.port = port
        self.mcp_server_configs = mcp_server_configs or []
        self.bridged_tools = bridged_tools or {}
        self._tool_execution_grants: deque[_ToolExecutionGrant] = deque(
            maxlen=_MAX_TOOL_EXECUTION_GRANTS
        )
        self._terminate_requested = anyio.Event()
        self._terminate_reason: str | None = None

    port: int
    """Model proxy server port."""

    mcp_server_configs: list[MCPServerConfigHTTP]
    """MCP server configs for bridged tools (resolved from bridged_tools parameter)."""

    bridged_tools: dict[str, dict[str, Tool]]
    """Registry of bridged tools by server name, then tool name."""

    def register_tool_execution_grants(self, calls: Sequence[ToolCall]) -> None:
        """Add one-shot host-tool grants from an approved response.

        Each grant is identity-scoped to the approved call's model-facing function
        name plus its arguments and consumed once; `consume_tool_execution_grant`
        resolves which bridged tool a name denotes. It is not scoped to the turn
        or time it was approved: a grant persists for the bridge's (sample's)
        lifetime until consumed (or evicted, with a warning, once
        `_MAX_TOOL_EXECUTION_GRANTS` unconsumed grants accumulate), so an approved
        call the scaffold never executes stays consumable later. That only ever
        re-authorizes the same action the approver already approved (same function
        name and arguments), never a different one.

        Matching is by name: the approval API carries no execution target, so an
        approved call to a scaffold-local tool that happens to share a bridged
        tool's name also mints a host grant — still bounded to the exact
        approver-reviewed arguments. Calls whose names cannot denote any bridged
        tool are not stored, so the bounded store holds only grants an execution
        could consume.
        """
        if not self.tool_approval_required():
            return

        for call in calls:
            if not _denotes_bridged_tool(self.bridged_tools, call.function):
                continue
            if len(self._tool_execution_grants) == self._tool_execution_grants.maxlen:
                warn_once(
                    logger,
                    "Bridged tool execution grants exceeded "
                    f"{_MAX_TOOL_EXECUTION_GRANTS}; evicting the oldest "
                    "unconsumed grant. An approved-but-never-executed call "
                    "that old can no longer be executed.",
                )
            self._tool_execution_grants.append(
                _ToolExecutionGrant(
                    function=call.function, arguments=dict(call.arguments)
                )
            )

    def consume_tool_execution_grant(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> bool:
        """Consume one grant matching this execution, if present.

        The requested (server, tool) is authoritative here, so the grant may have
        been registered under any of the names a scaffold could have declared it
        as (see `_candidate_functions`). Arguments match structurally (`==`): key
        order and int/float numeric equality (`5 == 5.0`) don't matter, so a
        scaffold's JSON round-trip cannot turn an approved call into a denial;
        any other difference is denied.
        """
        for function in _candidate_functions(server, tool):
            try:
                self._tool_execution_grants.remove(
                    _ToolExecutionGrant(function=function, arguments=arguments)
                )
                return True
            except ValueError:
                continue
        return False

    def tool_approval_required(self) -> bool:
        """Return whether explicit or ambient approval governs host tool calls."""
        from inspect_ai.agent._bridge._approval import bridge_approval_scope
        from inspect_ai.approval._apply import have_tool_approval

        with bridge_approval_scope(self.approval):
            return have_tool_approval()

    def request_terminate(self, reason: str) -> NoReturn:
        """Terminate the sample from a bridged generation.

        A sandbox bridge's generations run in the sandbox service task, where
        `_handle_request` turns exceptions into RPC error responses rather than
        letting them propagate (only `LimitExceededError` is special-cased). So the
        base implementation's raise would never reach the sample runner.

        Instead, signal the monitor task in `sandbox_agent_bridge`'s task group,
        which raises on the agent's side and tears the sample down. The raise below
        still unwinds the current RPC, so the sandboxed agent gets an error response
        rather than blocking on a reply that will never come.
        """
        self._terminate_reason = reason
        self._terminate_requested.set()
        raise TerminateSampleError(reason)


class _ToolExecutionGrant(NamedTuple):
    """Identity of one approved host tool execution: name plus arguments."""

    function: str
    """The approved call's model-facing function name, stored as the model used it."""

    arguments: dict[str, Any]
    """The approved arguments, matched structurally (`==`)."""


def _candidate_functions(server: str, tool: str) -> tuple[str, str, str]:
    """The names a scaffold could have declared this bridged tool as to its model.

    Scaffolds name MCP tools under their own scheme: the bare tool name, Claude
    Code's ``mcp__<server>__<tool>``, or Gemini CLI's ``<server>__<tool>`` (used
    for conflicting names). Each candidate is an exact string computed from the
    known (server, tool) — never parsed out of a call name — so an unrecognized
    scheme matches nothing (deny-safe) rather than the wrong tool.
    """
    return (tool, f"mcp__{server}__{tool}", f"{server}__{tool}")


def _denotes_bridged_tool(
    bridged_tools: dict[str, dict[str, Tool]], function: str
) -> bool:
    """Whether an approved call's function name could denote some bridged tool."""
    return any(
        function in _candidate_functions(server, tool)
        for server, tools in bridged_tools.items()
        for tool in tools
    )
