"""The :class:`AgentChannel` primitive — per-execution intervention substrate.

There are two ways to consume a channel from an agent loop:

- **High-level facade (recommended)** — three method calls per turn,
  matching the pattern documented in ``docs/intervention.qmd``:

  - :meth:`AgentChannel.before_turn` — drain queued operator messages.
  - :meth:`AgentChannel.turn_scope` — cancellable region for generate + tools.
  - :meth:`AgentChannel.after_cancel` — recover after a cancel was caught.

  Most custom agents (including ``react()``) use exactly this surface.
  Copy the snippet in ``docs/intervention.qmd`` and you have a working
  intervention-aware loop.

- **Low-level primitives** — :meth:`AgentChannel._post`,
  :meth:`AgentChannel._interrupt`, :meth:`AgentChannel._drain`,
  :meth:`AgentChannel._recv`, :meth:`AgentChannel._repair`,
  :meth:`AgentChannel._ref`. Underscored to mark them as internal.
  Exposed for *producers* (the ACP transport, tests, future operator
  consoles) and for the rare custom agent that needs to compose its
  own intervention semantics. Reach for them only when the facade
  doesn't fit.

Architecturally the channel carries typed :mod:`items
<inspect_ai.agent._channel.items>` between intervention producers
(operator over ACP, future subagent supervisor, ...) and the
consuming agent loop. Two delivery disciplines share one queue:

- **Data plane** (``post``): producer enqueues; consumer drains at its
  own boundaries. Cannot preempt in-flight work.
- **Control plane** (``interrupt``): producer enqueues a :class:`Cancel`
  AND cancels the bound :meth:`turn_scope` (if any). Surfaces as
  :exc:`AgentInterrupted` inside the running region. With no scope
  bound, degrades gracefully to a plain :meth:`post`.

The channel is source-agnostic and inert by default — with no producer
attached, ``drain`` returns ``[]`` and ``scope`` never cancels.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Callable, Iterator, Sequence

import anyio

from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.tool._tool_call import ToolCallError

from .exceptions import AgentInterrupted
from .items import Cancel, CancelReason, ChannelItem, UserMessage, coalesce

if TYPE_CHECKING:
    from .ref import AgentRef


_REPAIR_MESSAGE_FOR_REASON: dict[CancelReason, str] = {
    "user_cancel": "Tool call cancelled by user.",
    "limit": "Tool call cancelled by limit.",
    "system": "Tool call cancelled by system.",
}


class AgentChannel:
    """Per-execution intervention channel.

    There are two ways to consume a channel from an agent loop. Most
    custom agents should use the **high-level facade** — it's three
    method calls per turn and matches the documented pattern in
    ``docs/intervention.qmd``::

        async with agent_channel() as ch:
            while True:
                state.messages.extend(await ch.before_turn(state.messages))
                try:
                    with ch.turn_scope():
                        # generate + tool calls...
                except AgentInterrupted:
                    state.messages.extend(await ch.after_cancel(state.messages))
                    continue

    - :meth:`before_turn` — drain queued operator messages at the start
      of a turn (blocks for an initial one if state has none).
    - :meth:`turn_scope` — cancellable region for model generation + tool
      execution; an operator interrupt raises :exc:`AgentInterrupted`.
    - :meth:`after_cancel` — recovery messages (repair + follow-up)
      after :exc:`AgentInterrupted` was caught.

    The **low-level primitives** — :meth:`_post`, :meth:`_interrupt`,
    :meth:`_drain`, :meth:`_recv`, :meth:`_repair`, :meth:`_ref` — are
    underscored to mark them as internal. They are exposed for producers
    (ACP transport, tests, future operator consoles) and for the rare
    custom agent that needs to compose its own intervention semantics.
    Reach for them only when the facade doesn't fit; in nearly every
    agent loop it does.

    Owns: an unbounded item queue, an anyio Event for blocking on
    arrivals, and the currently-bound :class:`anyio.CancelScope` (if
    any). Source-agnostic — producers and consumers never interact
    with each other directly; the channel mediates.

    Instances are not thread-safe and not designed for use outside an
    enclosing agent execution (use :func:`agent_channel` /
    :func:`current_agent_channel` from the package root to acquire one).
    """

    def __init__(self) -> None:
        self._queue: list[ChannelItem] = []
        # Recreated after each drain so a stale set() from a
        # fired-then-drained item doesn't trigger a no-op wake.
        self._event: anyio.Event = anyio.Event()
        # The currently-bound scope, if any. Set by ``turn_scope()`` on entry,
        # cleared on exit.
        self._scope: anyio.CancelScope | None = None
        # Discriminates an interrupt()-driven cancel (we cancelled it,
        # raise AgentInterrupted on exit) from a sample-level cancel
        # propagating from outside (let CancelledError unwind).
        self._pending_interrupt: bool = False
        # Producer-side observers fired when ``_drain`` consumes items.
        # Producers register via ``subscribe_drained`` to learn that
        # their queued items reached the consumer (e.g. the ACP
        # transport clears its ``interrupt_pending`` flag when a
        # pre-queued operator message is drained).
        self._on_drained: list[Callable[[list[ChannelItem]], None]] = []

    # ------------------------------------------------------------------
    # Producer-facing API (also exposed via AgentRef)
    # ------------------------------------------------------------------

    def _post(self, item: ChannelItem) -> None:
        """Enqueue ``item`` for delivery at the next drain/recv boundary.

        Non-preemptive: cannot affect an in-flight model call or tool;
        the consumer chooses when to drain.
        """
        self._queue.append(item)
        self._event.set()

    def _interrupt(self, item: Cancel) -> None:
        """Enqueue ``item`` AND cancel the bound :meth:`turn_scope` (if any).

        With a scope bound: the wrapped block raises :exc:`AgentInterrupted`
        on exit; the consumer catches it, drains (sees the Cancel item and
        any sibling-posted UserMessage), and continues.

        With NO scope bound: degrades gracefully to a plain :meth:`_post`
        of the cancel item, delivered at the next drain. So "interrupt"
        means *preempt if a region is running, otherwise just deliver* —
        no race window to special-case.
        """
        self._post(item)
        if self._scope is not None:
            self._pending_interrupt = True
            self._scope.cancel()

    def _ref(self) -> "AgentRef":
        """Return a producer-side handle (:class:`AgentRef`).

        The handle exposes a public :meth:`AgentRef.post` /
        :meth:`AgentRef.interrupt` surface (delegating internally to
        :meth:`_post` / :meth:`_interrupt`). Producers hold refs so
        they can address an agent's channel without having access to
        the consumer-side surface (``_drain``, ``scope``, etc.).
        """
        from .ref import AgentRef

        return AgentRef(self)

    # ------------------------------------------------------------------
    # Consumer-facing API
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def turn_scope(self) -> Iterator[None]:
        """Demarcate an interruptible region.

        The agent enters this around foreground work it is willing to
        have preempted. An :meth:`_interrupt` call cancels the underlying
        :class:`anyio.CancelScope`; on exit the channel raises
        :exc:`AgentInterrupted` inside the block — but only when the
        cancel originated from this channel. A sample-level
        :class:`asyncio.CancelledError` (limit, eval shutdown) passes
        through unchanged.

        Exactly one scope per region is supported; nested scopes on the
        same channel are not. The scope must enclose tool execution as
        well as ``model.generate()`` so a blocking tool call can be
        cancelled by a producer-initiated interrupt mid-call.
        """
        self._pending_interrupt = False
        with anyio.CancelScope() as cs:
            self._scope = cs
            try:
                yield
            finally:
                self._scope = None
        if cs.cancelled_caught and self._pending_interrupt:
            self._pending_interrupt = False
            raise AgentInterrupted()

    def _drain(self) -> list[ChannelItem]:
        """Pop and return all currently-queued items (non-blocking).

        Sole-consumer drain: the channel is single-reader by contract
        (the enclosing agent loop). Returns ``[]`` if nothing is queued.

        Fires any registered drain observers (see
        :meth:`subscribe_drained`) when items are returned. Empty drains
        do not fire observers (no signal to consumers).
        """
        items = list(self._queue)
        self._queue.clear()
        self._event = anyio.Event()
        if items:
            # Snapshot to tolerate unsubscribes that fire during iteration.
            for cb in list(self._on_drained):
                try:
                    cb(items)
                except Exception:
                    # Observers must not break the consumer loop.
                    # Log via channel logger if we add one; for now,
                    # swallow per the same resilience contract as the
                    # transcript subscriber fan-out.
                    pass
        return items

    def subscribe_drained(
        self, callback: Callable[[list[ChannelItem]], None]
    ) -> Callable[[], None]:
        """Register a callback fired after a non-empty :meth:`_drain`.

        The callback receives the list of items that were drained. It
        runs synchronously in the consumer's task; exceptions are
        swallowed so a broken observer cannot stall the agent loop.

        Returns an idempotent unsubscribe callable — calling it more
        than once is safe and has no further effect.

        Producer use case: the ACP transport subscribes during
        :meth:`AcpTransport.maybe_bind` to observe when its queued
        :class:`UserMessage` items reach the consumer, so it can
        resolve its ``interrupt_pending`` flag without the channel
        needing to know about ACP.
        """
        self._on_drained.append(callback)

        def _unsubscribe() -> None:
            try:
                self._on_drained.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    async def _recv(self) -> list[ChannelItem]:
        """Await at least one item, then drain.

        Intended for one-shot blocking only — typically the first turn
        of a fresh run, where the consumer has no initial user message
        and is waiting for an operator (or other producer) to provide
        one. Do NOT use as a general consumption primitive; use
        :meth:`_drain` at boundaries.

        Returns at least one item.
        """
        if not self._queue:
            await self._event.wait()
        return self._drain()

    def _repair(
        self,
        messages: Sequence[ChatMessage],
        reason: CancelReason = "user_cancel",
    ) -> list[ChatMessageTool]:
        """Return repair messages to make ``messages`` well-formed after interrupt.

        Today this synthesizes a :class:`ChatMessageTool` result for
        every tool_call in the last assistant message that lacks a
        matching tool result downstream — covering tools that were in
        flight at cancel, tools that never started because an earlier
        sibling was cancelled, and tools whose completed results were
        lost when anyio cancellation interrupted ``_execute_tools_impl``
        before it returned. Without these repairs the next
        ``generate()`` would reject the conversation.

        Pure-structural: scans ``messages``, no channel state required.
        Safe to call any time; returns ``[]`` if nothing needs repair.

        ``reason`` selects the per-call error sentinel stamped on
        synthesized :class:`ToolCallError` instances. Defaults to
        ``"user_cancel"``.
        """
        repair_ids = _unanswered_tool_call_ids(messages)
        if not repair_ids:
            return []
        message_text = _REPAIR_MESSAGE_FOR_REASON[reason]
        return [
            ChatMessageTool(
                tool_call_id=tool_call_id,
                content=message_text,
                error=ToolCallError(type="cancelled", message=message_text),
            )
            for tool_call_id in repair_ids
        ]

    # ------------------------------------------------------------------
    # High-level facade (recommended consumer surface)
    # ------------------------------------------------------------------

    async def before_turn(
        self, messages: Sequence[ChatMessage]
    ) -> list[ChatMessageUser]:
        """Pending operator-supplied user messages for the start of a turn.

        Drains queued :class:`UserMessage` items, coalesces consecutive
        operator sends into one, and returns the resulting list ready to
        extend onto ``state.messages``.

        Blocks via :meth:`_recv` iff BOTH (a) the drain produced no
        :class:`UserMessage` AND (b) ``messages`` contains no
        :class:`ChatMessageUser` already. This is the "wait for an
        initial user message" gate — on every subsequent turn
        ``messages`` already has the prior user input so the call
        returns immediately.
        """
        items = self._drain()
        if not any(isinstance(it, UserMessage) for it in items) and not any(
            isinstance(m, ChatMessageUser) for m in messages
        ):
            items += await self._recv()
        return coalesce(items)

    async def after_cancel(self, messages: Sequence[ChatMessage]) -> list[ChatMessage]:
        """Recovery messages after :exc:`AgentInterrupted` was caught.

        Returns, in order:

        - Repair messages — synthetic :class:`ChatMessageTool` results
          for any ``tool_calls`` the last assistant message left in
          flight, so the conversation is well-formed for the next
          generation.
        - Pending user messages — coalesced producer follow-up posted
          alongside the interrupt. Always blocks for one if none arrived
          (preserves the stop-and-redirect semantics: after a cancel
          the agent waits for the operator's follow-up before resuming,
          regardless of how many user messages already exist in the
          conversation history).
        """
        repair_msgs = self._repair(messages)
        # Distinct from before_turn: the post-cancel block is
        # unconditional on the queue being empty. We've just been told
        # to stop; the operator's redirect — not stale prior user
        # messages — is what determines whether we resume.
        items = self._drain()
        if not any(isinstance(it, UserMessage) for it in items):
            items += await self._recv()
        return [*repair_msgs, *coalesce(items)]


def _unanswered_tool_call_ids(messages: Sequence[ChatMessage]) -> list[str]:
    """Return tool_call ids from the last assistant message that lack a result.

    Scans ``messages`` backwards to find the last
    :class:`ChatMessageAssistant`; collects every tool_call id from
    that message that does not have a matching
    :class:`ChatMessageTool` (by ``tool_call_id``) appearing later in
    the list.
    """
    last_assistant_idx: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], ChatMessageAssistant):
            last_assistant_idx = i
            break
    if last_assistant_idx is None:
        return []
    last_assistant = messages[last_assistant_idx]
    assert isinstance(last_assistant, ChatMessageAssistant)
    if not last_assistant.tool_calls:
        return []
    answered: set[str] = set()
    for m in messages[last_assistant_idx + 1 :]:
        if isinstance(m, ChatMessageTool) and m.tool_call_id:
            answered.add(m.tool_call_id)
    return [tc.id for tc in last_assistant.tool_calls if tc.id not in answered]
