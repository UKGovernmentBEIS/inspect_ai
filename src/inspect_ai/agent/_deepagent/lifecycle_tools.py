"""Lifecycle tools for background-dispatched subagents.

Four tools the parent agent uses to follow up on background dispatches
created via ``agent(background=True)``:

- ``agent_status(agent_id)`` — instant non-blocking peek
- ``agent_wait(agent_ids, mode, timeout)`` — block until one/all complete
- ``agent_cancel(agent_id)`` — terminate a running agent
- ``agent_list(status_filter)`` — enumerate agents in the registry

All four return readable markdown strings (``ToolResult`` forbids dict),
and each has a custom ``ToolCallViewer`` so the call line renders with a
clean title in the log viewer. They read the per-deepagent
``BackgroundRegistry`` from the ContextVar set in ``deepagent.execute()``.
They never raise — any problem (no registry, unknown agent id, empty
input) is reported as content so the model can see it and adjust.
"""

from __future__ import annotations

from typing import Literal

import anyio

from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._types import AgentContinue
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallView

from .agent_tool import (
    AgentFuture,
    BackgroundRegistry,
    active_background_agents,
    current_background_registry,
)

# Maximum bytes of the latest assistant message included in a running
# agent's status peek.
_PEEK_MAX_BYTES = 2000

# Bounded wait (seconds) for an agent_cancel to settle. Cancellation is
# cooperative, so a child stuck in a shielded or un-yielding call may not
# stop promptly; rather than block the parent indefinitely we cap the wait
# and report the cancellation as pending. A cooperative child settles in
# milliseconds (it hits an await checkpoint), so this rarely elapses.
_CANCEL_SETTLE_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Status formatting
# ---------------------------------------------------------------------------


def _peek_messages(future: AgentFuture) -> tuple[int, int, str]:
    """Snapshot a running agent's progress for the status peek.

    Returns (message_count, tool_call_count, last_assistant_text). The
    last assistant text is truncated to ``_PEEK_MAX_BYTES``. Handles the
    brief init window where ``child_state`` is still None.
    """
    if future.child_state is None:
        return 0, 0, ""

    # Defensive snapshot — the child may mutate its message list while we read.
    messages = list(future.child_state.messages)
    message_count = len(messages)
    tool_call_count = sum(
        len(m.tool_calls or []) for m in messages if isinstance(m, ChatMessageAssistant)
    )

    last_assistant = ""
    for m in reversed(messages):
        if isinstance(m, ChatMessageAssistant):
            last_assistant = m.text
            break

    truncated = truncate_string_to_bytes(last_assistant, _PEEK_MAX_BYTES)
    if truncated is not None:
        last_assistant = truncated.output

    return message_count, tool_call_count, last_assistant


def _format_future_status(future: AgentFuture) -> str:
    """Render one agent's state as a markdown block."""
    header = f"**{future.agent_id}** ({future.subagent_name}) — {future.status}"

    if future.status == "running":
        elapsed = max(0, int(anyio.current_time() - future.started_at))
        message_count, tool_call_count, last_assistant = _peek_messages(future)
        lines = [
            header,
            f"- elapsed: {elapsed}s",
            f"- messages: {message_count} ({tool_call_count} tool calls)",
        ]
        if last_assistant:
            lines.append(f"- latest: {last_assistant}")
        return "\n".join(lines)

    if future.status == "completed":
        result = future.result or "(no output)"
        return f"{header}\n\n{result}"

    if future.status == "errored":
        return f"{header}\n\n{future.error or '(no error detail)'}"

    # cancelled
    return header


def _format_many(futures: list[AgentFuture]) -> str:
    """Join multiple agent status blocks with a separator."""
    if not futures:
        return "No background agents."
    return "\n\n---\n\n".join(_format_future_status(f) for f in futures)


# ---------------------------------------------------------------------------
# Registry access helpers
#
# The lifecycle tools never raise — they always succeed and report any
# problem (no registry, unknown agent id, empty input) as readable content
# so the model can see what happened and adjust. These helpers therefore
# return content strings rather than raising.
# ---------------------------------------------------------------------------

_NO_REGISTRY = "Background dispatch is not enabled for this agent."


def _unknown_agent(registry: BackgroundRegistry, agent_id: str) -> str:
    """Content message for an agent id not present in the registry."""
    known = ", ".join(registry.futures.keys()) or "(none)"
    return f"Unknown agent id {agent_id!r}. Known agents: {known}."


# ---------------------------------------------------------------------------
# Tool viewers
# ---------------------------------------------------------------------------


def _status_viewer(call: ToolCall) -> ToolCallView:
    agent_id = call.arguments.get("agent_id") or ""
    return ToolCallView(
        call=ToolCallContent(title=f"agent_status: {agent_id}", format="text")
    )


def _wait_viewer(call: ToolCall) -> ToolCallView:
    ids = call.arguments.get("agent_ids") or []
    mode = call.arguments.get("mode") or "all"
    ids_str = ", ".join(ids) if isinstance(ids, list) else str(ids)
    return ToolCallView(
        call=ToolCallContent(title=f"agent_wait: {ids_str} ({mode})", format="text")
    )


def _cancel_viewer(call: ToolCall) -> ToolCallView:
    agent_id = call.arguments.get("agent_id") or ""
    return ToolCallView(
        call=ToolCallContent(title=f"agent_cancel: {agent_id}", format="text")
    )


def _list_viewer(call: ToolCall) -> ToolCallView:
    status_filter = call.arguments.get("status_filter")
    title = f"agent_list: {status_filter}" if status_filter else "agent_list"
    return ToolCallView(call=ToolCallContent(title=title, format="text"))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(viewer=_status_viewer)
def agent_status() -> Tool:
    """Check the status of a background agent without blocking."""

    async def execute(agent_id: str) -> str:
        """Check on a background agent without blocking.

        Returns the current status. For a running agent, includes a brief
        progress peek (elapsed time, message and tool-call counts, and its
        latest message). For a finished agent, includes the full result.
        Use this when you have other useful work to do and just want a
        quick check; use agent_wait when you actually need the result
        before continuing.

        Args:
            agent_id: The AGENT-N handle returned when the agent was
                dispatched in the background.
        """
        registry = current_background_registry()
        if registry is None:
            return _NO_REGISTRY
        future = registry.futures.get(agent_id)
        if future is None:
            return _unknown_agent(registry, agent_id)
        return _format_future_status(future)

    return execute


@tool(viewer=_wait_viewer)
def agent_wait() -> Tool:
    """Wait for one or more background agents to complete."""

    async def execute(
        agent_ids: list[str],
        mode: Literal["any", "all"] = "all",
        timeout: float | None = None,
    ) -> str:
        """Wait for one or more background agents to complete.

        Blocks until the agents finish (or the timeout elapses), then
        returns their status and results. Prefer a single agent_wait over
        a polling loop of agent_status calls. Use this when you need a
        result before you can continue; do other useful work first if you
        can.

        Args:
            agent_ids: AGENT-N handles to wait on.
            mode: "all" (default) waits for every listed agent; "any"
                returns as soon as the first one finishes.
            timeout: Optional seconds to wait before returning. On
                timeout, still-running agents are reported honestly with
                their current progress.
        """
        registry = current_background_registry()
        if registry is None:
            return _NO_REGISTRY
        if not agent_ids:
            return "No agent_ids provided."

        # Partition into known futures and unknown ids — never raise.
        futures = [
            registry.futures[aid] for aid in agent_ids if aid in registry.futures
        ]
        unknown = [aid for aid in agent_ids if aid not in registry.futures]

        # Treat an unexpected mode as the safe default rather than failing.
        effective_mode = mode if mode in ("any", "all") else "all"

        if futures:
            if effective_mode == "all":
                with anyio.move_on_after(timeout):
                    for f in futures:
                        await f.done.wait()
            else:  # any
                with anyio.move_on_after(timeout):
                    async with anyio.create_task_group() as tg:

                        async def _wait_one(fut: AgentFuture) -> None:
                            await fut.done.wait()
                            tg.cancel_scope.cancel()

                        for f in futures:
                            tg.start_soon(_wait_one, f)

        blocks = [_format_future_status(f) for f in futures]
        if unknown:
            known = ", ".join(registry.futures.keys()) or "(none)"
            blocks.append(
                f"Unknown agent id(s): {', '.join(unknown)}. Known agents: {known}."
            )
        return "\n\n---\n\n".join(blocks) if blocks else "No matching agents."

    return execute


@tool(viewer=_cancel_viewer)
def agent_cancel() -> Tool:
    """Cancel a running background agent."""

    async def execute(agent_id: str) -> str:
        """Cancel a running background agent.

        Terminates the agent's work. No-op if the agent has already
        finished. Returns the agent's status after cancellation.

        Args:
            agent_id: The AGENT-N handle to cancel.
        """
        registry = current_background_registry()
        if registry is None:
            return _NO_REGISTRY
        future = registry.futures.get(agent_id)
        if future is None:
            return _unknown_agent(registry, agent_id)
        if future.status == "running" and future.cancel_scope is not None:
            future.cancel_scope.cancel()
            # Wait (bounded) for the cancellation to be delivered so the
            # returned status reflects the settled state rather than the
            # stale "running". Cancellation is cooperative — a child stuck
            # in a shielded or un-yielding call may not stop promptly — so
            # cap the wait instead of blocking the parent indefinitely.
            with anyio.move_on_after(_CANCEL_SETTLE_TIMEOUT):
                await future.done.wait()
            if not future.done.is_set():
                return (
                    f"**{agent_id}** ({future.subagent_name}) — cancellation "
                    "requested. The agent has not stopped yet and will "
                    "terminate at its next checkpoint. Re-check with "
                    f"`agent_status({agent_id!r})`."
                )
        return _format_future_status(future)

    return execute


@tool(viewer=_list_viewer)
def agent_list() -> Tool:
    """List background agents and their statuses."""

    async def execute(
        status_filter: Literal["running", "completed", "errored", "cancelled"]
        | None = None,
    ) -> str:
        """List background agents and their statuses.

        Returns all background agents you have dispatched (optionally
        filtered by status), with a brief status for each. Useful for
        recovering track of agents — for example after a long stretch of
        work or after context compaction.

        Args:
            status_filter: Only include agents in this state. One of
                "running", "completed", "errored", "cancelled". Omit to
                list all.
        """
        registry = current_background_registry()
        if registry is None:
            return _NO_REGISTRY
        futures = list(registry.futures.values())
        if status_filter is not None:
            futures = [f for f in futures if f.status == status_filter]
        return _format_many(futures)

    return execute


# ---------------------------------------------------------------------------
# Periodic background-agent reminder (Phase 4)
#
# A forgetting *backstop*, not a periodic nag. deepagent.execute() wraps
# on_continue with a composer that resets a per-sample counter whenever the
# model touches a background tool, and injects a passive reminder only after
# REMINDER_INTERVAL turns of *ignoring* its background agents. The reminder
# reads as ambient awareness ("no action needed") to avoid pulling the model
# off-task into needless polling/waiting.
# ---------------------------------------------------------------------------

# Turns the model may go without touching a background tool before a reminder
# is injected (provided it has active background agents).
REMINDER_INTERVAL = 5

# Model-facing names of the background lifecycle tools. Touching any of these
# (or dispatching via agent(background=True)) counts as the model managing its
# background agents and resets the reminder counter.
_BACKGROUND_LIFECYCLE_TOOLS = frozenset(
    {"agent_status", "agent_wait", "agent_cancel", "agent_list"}
)


def _used_background_tool(state: AgentState) -> bool:
    """Whether the latest assistant turn managed a background agent.

    True if the most recent assistant message called any lifecycle tool or
    dispatched a new background agent via ``agent(background=True)``. Only the
    most recent assistant turn is inspected — the question is "did the model
    just interact?", which gates the reminder counter.
    """
    for m in reversed(state.messages):
        if isinstance(m, ChatMessageAssistant):
            for tc in m.tool_calls or []:
                if tc.function in _BACKGROUND_LIFECYCLE_TOOLS:
                    return True
                if tc.function == "agent" and tc.arguments.get("background"):
                    return True
            return False
    return False


def background_reminder_message(
    futures: list[AgentFuture],
) -> ChatMessageUser | None:
    """Build a passive reminder of the model's background agents.

    Lists still-running agents (no action needed) and finished agents whose
    results are worth collecting. Returns None when there is nothing worth
    reminding about (e.g. only cancelled agents remain), so the caller can
    skip injection.
    """
    running = [f for f in futures if f.status == "running"]
    finished = [f for f in futures if f.status in ("completed", "errored")]
    if not running and not finished:
        return None

    lines = [
        "[Automatic reminder — no action needed.] You have background agents "
        "from earlier. Keep working on your current task; only use "
        "`agent_wait` when you actually need a result before continuing."
    ]
    if running:
        lines.append("")
        lines.append("Still running (let them work):")
        for f in running:
            elapsed = max(0, int(anyio.current_time() - f.started_at))
            lines.append(f"- {f.agent_id} ({f.subagent_name}) — {elapsed}s")
    if finished:
        lines.append("")
        lines.append("Finished — collect when you need the result:")
        for f in finished:
            lines.append(
                f"- {f.agent_id} ({f.subagent_name}) — {f.status}; "
                f"call agent_status('{f.agent_id}')"
            )
    return ChatMessageUser(content="\n".join(lines))


def background_on_continue(
    on_continue: str | AgentContinue | None,
) -> AgentContinue:
    """Wrap ``on_continue`` to inject a periodic background-agent reminder.

    A forgetting *backstop*: a per-sample counter resets whenever the model
    touches a background tool and a passive reminder is injected only after
    ``REMINDER_INTERVAL`` turns of ignoring active background agents. The
    wrapper preserves ``react()``'s on_continue protocol for the
    None / str / callable / AgentState forms — composing the reminder into
    the inner result rather than mutating state directly.

    Args:
        on_continue: The user-configured continuation behavior to wrap.

    Returns:
        An ``AgentContinue`` to pass to ``react()``.
    """
    reminder_idle_turns = 0

    async def execute(st: AgentState) -> bool | str | AgentState:
        nonlocal reminder_idle_turns

        # delegate to the configured on_continue, preserving its semantics
        if on_continue is None:
            result: bool | str | AgentState = True
        elif isinstance(on_continue, str):
            # react only injects a str-continue on a stop (no tool calls);
            # returning it unconditionally would change that.
            result = on_continue if not st.output.message.tool_calls else True
        else:
            result = await on_continue(st)

        # reset on interaction this turn, otherwise advance the counter
        if _used_background_tool(st):
            reminder_idle_turns = 0
        else:
            reminder_idle_turns += 1

        # pass the inner result through unchanged when the agent is stopping
        # or no reminder is due yet
        if result is False or reminder_idle_turns < REMINDER_INTERVAL:
            return result

        reminder = background_reminder_message(active_background_agents())
        if reminder is None:
            return result
        reminder_idle_turns = 0

        # compose the reminder into the inner result, honoring react's
        # on_continue protocol:
        # - AgentState: append the reminder to the messages it carries
        # - str: append the reminder text to the continue string
        # - True: return the reminder text as the continue message
        if isinstance(result, AgentState):
            result.messages.append(reminder)
            return result
        if isinstance(result, str):
            return f"{result}\n\n{reminder.text}"
        return reminder.text

    return execute
