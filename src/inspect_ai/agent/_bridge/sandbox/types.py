import json
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

        Each grant is identity-scoped to (server, tool, canonical arguments) and
        consumed once. It is not scoped to the turn or time it was approved: a
        grant persists for the bridge's (sample's) lifetime until consumed (or
        evicted, with a warning, once `_MAX_TOOL_EXECUTION_GRANTS` unconsumed
        grants accumulate), so an approved call the scaffold never executes stays
        consumable later. That only ever re-authorizes the same action the
        approver already approved (same server, tool, and canonical arguments),
        never a different one.

        Matching is by name: the approval API carries no execution target, so an
        approved call to a scaffold-local tool that happens to share a bridged
        tool's name also mints a host grant — still bounded to the exact
        approver-reviewed arguments.
        """
        if not self.tool_approval_required():
            return

        for call in calls:
            resolutions = _resolve_bridged_tool(self.bridged_tools, call.function)
            if len(resolutions) > 1:
                warn_once(
                    logger,
                    f"Approved tool call '{call.function}' matches multiple bridged "
                    f"tools ({', '.join('/'.join(r) for r in sorted(resolutions))}); "
                    "no execution grant was registered and executing it will be "
                    "denied. Give bridged tools unique names.",
                )
            elif len(resolutions) == 1:
                server, tool = next(iter(resolutions))
                if (
                    len(self._tool_execution_grants)
                    == self._tool_execution_grants.maxlen
                ):
                    warn_once(
                        logger,
                        "Bridged tool execution grants exceeded "
                        f"{_MAX_TOOL_EXECUTION_GRANTS}; evicting the oldest "
                        "unconsumed grant. An approved-but-never-executed call "
                        "that old can no longer be executed.",
                    )
                self._tool_execution_grants.append(
                    _tool_execution_key(server, tool, call.arguments)
                )

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


class _ToolExecutionGrant(NamedTuple):
    """Canonical identity of one approved host tool execution."""

    server: str
    tool: str
    arguments: str
    """Canonical JSON of the approved arguments (see `_tool_execution_key`)."""


def _resolve_bridged_tool(
    bridged_tools: dict[str, dict[str, Tool]], function: str
) -> set[tuple[str, str]]:
    """Resolve a model-facing tool call name to bridged (server, tool) pairs.

    Scaffolds declare MCP tools to their model under their own naming scheme, so
    the approved call's name may be qualified rather than the bare tool name:
    Claude Code uses ``mcp__<server>__<tool>``, and Gemini CLI qualifies
    conflicting names as ``<server>__<tool>``. Each candidate is an exact string
    computed from the registry — never a fuzzy parse — so an unrecognized scheme
    resolves to nothing (deny-safe) rather than to the wrong tool.

    Returns every distinct resolution; more than one means the name is ambiguous
    and no grant may be issued for it.
    """
    resolutions: set[tuple[str, str]] = set()
    for server, tools in bridged_tools.items():
        if function in tools:
            resolutions.add((server, function))
        for prefix in (f"mcp__{server}__", f"{server}__"):
            if function.startswith(prefix) and function[len(prefix) :] in tools:
                resolutions.add((server, function[len(prefix) :]))
    return resolutions


def _tool_execution_key(
    server: str, tool: str, arguments: dict[str, Any]
) -> _ToolExecutionGrant:
    """Canonical identity for a host tool execution request.

    Matching is exact on the canonical form: key order is normalized, but an
    execution is authorized only when re-issued with the same arguments the
    approver reviewed. A scaffold that re-serializes arguments differently (e.g.
    coercing number types) will not match and is denied — deliberately strict, so
    an unreviewed call can never slip through.

    `default=str` keeps this total for the values `dict[str, Any]` admits beyond
    JSON (an approver `modify` can inject e.g. `Path`): registration must never
    crash an approved generate. Such values still only match if the scaffold
    re-sends the identical string form — unmatched remains denied, not an error.
    """
    return _ToolExecutionGrant(
        server=server,
        tool=tool,
        arguments=json.dumps(
            arguments,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ),
    )
