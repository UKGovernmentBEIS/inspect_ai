import json
from collections import deque
from typing import TYPE_CHECKING, Any, NoReturn, Sequence

import anyio

from inspect_ai._util.exception import TerminateSampleError
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
        self._tool_execution_grants: deque[tuple[str, str, str]] = deque()
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

        Each grant is identity-scoped to (server, tool, canonical arguments) and
        consumed once. It is not scoped to the turn or time it was approved: a
        grant persists for the bridge's (sample's) lifetime until consumed, so an
        approved call the scaffold never executes stays consumable later. That only
        ever re-authorizes the same action the approver already approved (same
        server, tool, and canonical arguments), never a different one.
        """
        if not self.tool_approval_required():
            return

        for call in calls:
            servers = [
                server
                for server, tools in self.bridged_tools.items()
                if call.function in tools
            ]
            if len(servers) == 1:
                key = _tool_execution_key(servers[0], call.function, call.arguments)
                self._tool_execution_grants.append(key)
                while len(self._tool_execution_grants) > _MAX_TOOL_EXECUTION_GRANTS:
                    self._tool_execution_grants.popleft()

    def consume_tool_execution_grant(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> bool:
        """Consume one exact server/tool/arguments grant, if present."""
        key = _tool_execution_key(server, tool, arguments)
        try:
            self._tool_execution_grants.remove(key)
        except ValueError:
            return False
        return True

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


def _tool_execution_key(
    server: str, tool: str, arguments: dict[str, Any]
) -> tuple[str, str, str]:
    """Canonical identity for a host tool execution request.

    Matching is exact on the canonical form: key order is normalized, but an
    execution is authorized only when re-issued with the same arguments the
    approver reviewed. A scaffold that re-serializes arguments differently (e.g.
    coercing number types) will not match and is denied — deliberately strict, so
    an unreviewed call can never slip through.
    """
    return (
        server,
        tool,
        json.dumps(
            arguments, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ),
    )
