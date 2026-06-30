"""Agent channel — source-agnostic, per-execution intervention substrate.

The agent channel is the runtime primitive for getting intervention
messages into a running agent (operator user messages, cancel signals,
and future item types) and for letting consumers (``react()`` and other
``@agent`` implementations) react to them at well-defined boundaries.

Three roles:

- **Channel** (:class:`AgentChannel`): the bidirectional conduit. Owns
  the item queue and the bound cancellation scope.
- **Producer** (:class:`AgentRef`): handle held by anything that wants
  to intervene — the ACP transport today, future subagent supervisors.
  Exposes only :meth:`AgentRef.post` and :meth:`AgentRef.interrupt`.
- **Consumer**: the agent loop. Acquires its channel via
  :func:`agent_channel` (context manager) and reads via
  :meth:`AgentChannel.drain` / :meth:`AgentChannel.recv`.

Inert by default: with no producer attached, ``drain`` returns ``[]``
and the scope never cancels. An eval with no ACP attached pays no
runtime cost beyond the empty queue and an unused :class:`anyio.Event`.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import AsyncIterator, Callable, Iterator, Sequence

from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool

from .channel import AgentChannel
from .exceptions import AgentInterrupted
from .items import (
    Cancel,
    CancelReason,
    ChannelItem,
    UserMessage,
    coalesce,
)
from .observer import ExecutionObserver, NullExecutionObserver, null_execution_observer
from .ref import AgentRef


class _InertAgentChannel(AgentChannel):
    """Singleton channel returned when no channel is installed.

    All operations are safe but produce no effect:

    - :meth:`_post` / :meth:`_interrupt` silently discard.
    - :meth:`_drain` always returns ``[]``.
    - :meth:`turn_scope` never cancels.
    - :meth:`_recv` raises (calling ``_recv`` on the inert channel
      indicates the consumer is outside any agent execution — there
      is no producer to wait for).
    """

    def _post(self, item: ChannelItem) -> None:
        return None

    def _interrupt(self, item: Cancel) -> None:
        return None

    def _drain(self) -> list[ChannelItem]:
        return []

    async def _recv(self) -> list[ChannelItem]:
        raise RuntimeError(
            "AgentChannel._recv() called outside an agent execution; "
            "no producer attached so this would block forever."
        )

    @contextlib.contextmanager
    def turn_scope(self) -> Iterator[None]:
        yield

    def _repair(
        self, messages: Sequence[ChatMessage], reason: CancelReason = "user_cancel"
    ) -> list[ChatMessageTool]:
        return []

    def mark_live(self) -> "Callable[[], None]":
        # Singleton — never live, never lets a stray producer mutate
        # shared state by incrementing a counter on the inert instance.
        return lambda: None


_INERT_CHANNEL: AgentChannel = _InertAgentChannel()

_channel_var: ContextVar[AgentChannel] = ContextVar(
    "_agent_channel", default=_INERT_CHANNEL
)


@contextlib.asynccontextmanager
async def agent_channel() -> AsyncIterator[AgentChannel]:
    """Open a fresh :class:`AgentChannel` for the enclosing scope.

    Use as an async context manager::

        async with agent_channel() as ch:
            ...

    Inside the ``with`` block, :func:`current_agent_channel` returns
    ``ch``. The channel is uniform at every nesting level: nested
    ``agent_channel()`` opens (e.g. a sub-agent invoked via handoff)
    each get their own working channel.

    Opening also offers the channel's :class:`AgentRef` to the active
    sample's ACP session (if any) via ``maybe_bind`` — first-binder-wins,
    so a nested sub-agent's open is silently rejected and the outer
    react remains the producer target. ``unbind`` on exit clears the
    slot iff this channel was the binder, letting a successor react in
    the same sample rebind. The channel itself never knows whether it
    is nested; the bind-once semantics live on the ACP session.
    """
    ch = AgentChannel()
    ref = ch._ref()
    bound_session = None
    # Defer the bind attempt: look up the active sample's ACP session
    # and offer the ref. Local imports to avoid a load-time cycle
    # (agent._channel → log._samples → … → agent._channel).
    try:
        from inspect_ai.log._samples import sample_active

        sample = sample_active()
        if sample is not None and sample.acp_transport is not None:
            if sample.acp_transport.maybe_bind(ch, ref):
                bound_session = sample.acp_transport
    except Exception:  # noqa: BLE001 — best-effort hook; never crash the agent
        pass
    token = _channel_var.set(ch)
    try:
        yield ch
    finally:
        _channel_var.reset(token)
        if bound_session is not None:
            try:
                bound_session.unbind(ref)
            except Exception:  # noqa: BLE001
                pass


def current_agent_channel() -> AgentChannel:
    """Return the currently active :class:`AgentChannel`.

    Returns the inert singleton when called outside any
    :func:`agent_channel` scope, so callers never need to guard for
    ``None``. The inert channel silently drops producer writes and
    yields no items on drain — calling it outside an execution is a
    no-op rather than an error.
    """
    return _channel_var.get()


__all__ = [
    # Channel core
    "AgentChannel",
    "AgentRef",
    "AgentInterrupted",
    "agent_channel",
    "current_agent_channel",
    # Items
    "ChannelItem",
    "UserMessage",
    "Cancel",
    "CancelReason",
    "coalesce",
    # Observer
    "ExecutionObserver",
    "NullExecutionObserver",
    "null_execution_observer",
]
