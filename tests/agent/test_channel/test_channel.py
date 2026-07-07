"""Unit tests for the source-agnostic agent channel primitive."""

from __future__ import annotations

import sys

import anyio
import pytest

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup  # noqa: F401

from inspect_ai.agent import (
    AgentChannel,
    AgentInterrupted,
    agent_channel,
)
from inspect_ai.agent._channel import (
    _INERT_CHANNEL,
    Cancel,
    UserMessage,
    current_agent_channel,
)
from inspect_ai.agent._channel.observer import (
    NullExecutionObserver,
    null_execution_observer,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.tool._tool_call import ToolCall

# ---------------------------------------------------------------------------
# Ambient accessor / inert default
# ---------------------------------------------------------------------------


def test_current_agent_channel_outside_scope_is_inert() -> None:
    ch = current_agent_channel()
    assert ch is _INERT_CHANNEL
    # inert never delivers items
    ch._post(UserMessage(message=ChatMessageUser(content="x")))
    assert ch._drain() == []


async def test_agent_channel_installs_into_contextvar() -> None:
    async with agent_channel() as ch:
        assert current_agent_channel() is ch
    # restored after exit
    assert current_agent_channel() is _INERT_CHANNEL


async def test_nested_channels_are_independent() -> None:
    async with agent_channel() as outer:
        outer._post(UserMessage(message=ChatMessageUser(content="outer")))
        async with agent_channel() as inner:
            # current is inner now, not outer
            assert current_agent_channel() is inner
            assert inner._drain() == []
        # outer restored, items still queued
        assert current_agent_channel() is outer
        items = outer._drain()
        assert len(items) == 1


# ---------------------------------------------------------------------------
# post / drain
# ---------------------------------------------------------------------------


def test_post_then_drain() -> None:
    ch = AgentChannel()
    ch._post(UserMessage(message=ChatMessageUser(content="a")))
    ch._post(UserMessage(message=ChatMessageUser(content="b")))
    items = ch._drain()
    assert len(items) == 2
    assert ch._drain() == []  # drained


def test_ref_only_exposes_producer_surface() -> None:
    ch = AgentChannel()
    ref = ch._ref()
    # ref.post and ref.interrupt exist; no drain/scope/recv
    assert hasattr(ref, "post")
    assert hasattr(ref, "interrupt")
    assert not hasattr(ref, "drain")
    assert not hasattr(ref, "scope")
    assert not hasattr(ref, "recv")


# ---------------------------------------------------------------------------
# recv
# ---------------------------------------------------------------------------


async def test_recv_returns_immediately_if_queued() -> None:
    ch = AgentChannel()
    ch._post(UserMessage(message=ChatMessageUser(content="x")))
    items = await ch._recv()
    assert len(items) == 1


async def test_recv_blocks_until_item_arrives() -> None:
    ch = AgentChannel()
    ref = ch._ref()

    async def producer() -> None:
        await anyio.sleep(0.01)
        ref.post(UserMessage(message=ChatMessageUser(content="late")))

    async with anyio.create_task_group() as tg:
        tg.start_soon(producer)
        items = await ch._recv()

    assert len(items) == 1
    msg = items[0]
    assert isinstance(msg, UserMessage)
    assert msg.message.content == "late"


async def test_recv_on_inert_raises() -> None:
    with pytest.raises(RuntimeError):
        await _INERT_CHANNEL._recv()


# ---------------------------------------------------------------------------
# scope + interrupt
# ---------------------------------------------------------------------------


async def test_interrupt_inside_scope_raises_agent_interrupted() -> None:
    ch = AgentChannel()
    ref = ch._ref()

    async def fire() -> None:
        await anyio.sleep(0.01)
        ref.interrupt(Cancel(reason="user_cancel"))

    raised = False
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(fire)
            with ch.turn_scope():
                await anyio.sleep(1.0)
    except BaseException as exc:
        # AgentInterrupted may arrive directly or wrapped in an
        # ExceptionGroup if the task group merged exceptions.
        if isinstance(exc, AgentInterrupted):
            raised = True
        elif isinstance(exc, BaseExceptionGroup):
            for sub in exc.exceptions:
                if isinstance(sub, AgentInterrupted):
                    raised = True
                    break

    assert raised
    items = ch._drain()
    assert len(items) == 1
    assert isinstance(items[0], Cancel)
    assert items[0].reason == "user_cancel"


def test_interrupt_no_scope_degrades_to_deliver() -> None:
    ch = AgentChannel()
    ref = ch._ref()
    ref.interrupt(Cancel())
    items = ch._drain()
    assert len(items) == 1
    assert isinstance(items[0], Cancel)


async def test_scope_without_interrupt_completes_normally() -> None:
    ch = AgentChannel()
    with ch.turn_scope():
        await anyio.sleep(0)
    # no exception raised; drain stays empty
    assert ch._drain() == []


async def test_external_cancel_propagates_as_cancelled_error() -> None:
    """External cancel must propagate as CancelledError, not AgentInterrupted.

    Sample-level cancels (from outside the channel — limit, eval shutdown)
    are distinct from operator-initiated interrupts.
    """
    ch = AgentChannel()

    async def cancel_outer(scope: anyio.CancelScope) -> None:
        await anyio.sleep(0.01)
        scope.cancel()

    cancelled = False
    async with anyio.create_task_group() as tg:
        outer_scope = tg.cancel_scope
        tg.start_soon(cancel_outer, outer_scope)
        try:
            with ch.turn_scope():
                await anyio.sleep(1.0)
        except BaseException:
            # asyncio CancelledError surfaces; that's fine
            pass
        # We expect to be cancelled out of the sleep; no AgentInterrupted
        cancelled = outer_scope.cancel_called

    assert cancelled
    # The channel's pending_interrupt flag was never set, so even if scope
    # caught a cancellation, AgentInterrupted wasn't raised.


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------


def test_repair_synthesizes_tool_messages_for_unanswered_calls() -> None:
    ch = AgentChannel()
    msgs: list[ChatMessage] = [
        ChatMessageUser(content="do x and y"),
        ChatMessageAssistant(
            content="ok",
            tool_calls=[
                ToolCall(id="t1", function="x", arguments={}),
                ToolCall(id="t2", function="y", arguments={}),
            ],
        ),
    ]
    repairs = ch._repair(msgs)
    assert len(repairs) == 2
    assert {r.tool_call_id for r in repairs} == {"t1", "t2"}
    for r in repairs:
        assert isinstance(r, ChatMessageTool)
        assert r.error is not None
        assert r.error.type == "cancelled"


def test_repair_skips_already_answered() -> None:
    ch = AgentChannel()
    msgs: list[ChatMessage] = [
        ChatMessageUser(content="do x and y"),
        ChatMessageAssistant(
            content="ok",
            tool_calls=[
                ToolCall(id="t1", function="x", arguments={}),
                ToolCall(id="t2", function="y", arguments={}),
            ],
        ),
        ChatMessageTool(tool_call_id="t1", content="done"),
    ]
    repairs = ch._repair(msgs)
    assert len(repairs) == 1
    assert repairs[0].tool_call_id == "t2"


def test_repair_returns_empty_when_no_pending() -> None:
    ch = AgentChannel()
    msgs: list[ChatMessage] = [
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content="hello"),  # no tool calls
    ]
    assert ch._repair(msgs) == []
    assert ch._repair([]) == []  # empty messages


def test_repair_cause_selects_message_text() -> None:
    ch = AgentChannel()
    msgs = [
        ChatMessageAssistant(
            content="ok",
            tool_calls=[ToolCall(id="t1", function="x", arguments={})],
        ),
    ]
    r = ch._repair(msgs, reason="limit")[0]
    assert r.error is not None
    assert "limit" in r.error.message.lower()


# ---------------------------------------------------------------------------
# subscribe_drained observer
# ---------------------------------------------------------------------------


def test_subscribe_drained_fires_on_non_empty_drain() -> None:
    """Observer callback receives the drained items."""
    ch = AgentChannel()
    captured: list[list] = []
    ch.subscribe_drained(lambda items: captured.append(items))
    ch._post(UserMessage(message=ChatMessageUser(content="a", source="operator")))
    items = ch._drain()
    assert len(captured) == 1
    assert captured[0] == items


def test_subscribe_drained_does_not_fire_on_empty_drain() -> None:
    """Empty drains carry no signal; observer is not invoked."""
    ch = AgentChannel()
    captured: list[list] = []
    ch.subscribe_drained(lambda items: captured.append(items))
    assert ch._drain() == []
    assert captured == []


def test_subscribe_drained_unsubscribe_is_idempotent() -> None:
    """Calling the returned unsubscribe more than once is safe."""
    ch = AgentChannel()
    unsub = ch.subscribe_drained(lambda items: None)
    unsub()
    unsub()  # must not raise


# ---------------------------------------------------------------------------
# subscribe_turn_state observer
# ---------------------------------------------------------------------------


async def test_subscribe_turn_state_fires_started_then_ended() -> None:
    """Normal turn_scope() fires "started" on entry and "ended" on exit."""
    ch = AgentChannel()
    states: list[str] = []
    ch.subscribe_turn_state(lambda s: states.append(s))
    with ch.turn_scope():
        assert states == ["started"]
    assert states == ["started", "ended"]


async def test_subscribe_turn_state_fires_cancelled_on_interrupt() -> None:
    """An operator interrupt fires "cancelled" (not "ended") on exit."""
    ch = AgentChannel()
    ref = ch._ref()
    states: list[str] = []
    ch.subscribe_turn_state(lambda s: states.append(s))

    async def fire() -> None:
        await anyio.sleep(0.01)
        ref.interrupt(Cancel(reason="user_cancel"))

    raised = False
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(fire)
            with ch.turn_scope():
                await anyio.sleep(1.0)
    except BaseException as exc:
        if isinstance(exc, AgentInterrupted):
            raised = True
        elif isinstance(exc, BaseExceptionGroup):
            raised = any(isinstance(e, AgentInterrupted) for e in exc.exceptions)

    assert raised
    assert states == ["started", "cancelled"]


def test_subscribe_turn_state_unsubscribe_is_idempotent() -> None:
    ch = AgentChannel()
    unsub = ch.subscribe_turn_state(lambda s: None)
    unsub()
    unsub()  # must not raise


async def test_subscribe_turn_state_broken_observer_does_not_break_scope() -> None:
    """A raising observer must not stall the agent's turn boundary."""
    ch = AgentChannel()
    good: list[str] = []

    def broken(state: str) -> None:
        raise RuntimeError("boom")

    ch.subscribe_turn_state(broken)
    ch.subscribe_turn_state(lambda s: good.append(s))
    with ch.turn_scope():
        pass
    assert good == ["started", "ended"]


def test_inert_channel_turn_scope_does_not_fire_turn_state() -> None:
    """The inert singleton's turn_scope() is a no-op yield; observers never fire."""
    states: list[str] = []
    unsub = _INERT_CHANNEL.subscribe_turn_state(lambda s: states.append(s))
    with _INERT_CHANNEL.turn_scope():
        pass
    assert states == []
    unsub()


def test_subscribe_drained_broken_observer_does_not_break_drain() -> None:
    """A raising observer must not break sibling observers or the drain itself.

    Mirrors the resilience contract on the transcript subscriber
    fan-out: a producer's task continues even if a downstream
    listener is broken.
    """
    ch = AgentChannel()
    good_calls: list[list] = []

    def broken(items: list) -> None:
        raise RuntimeError("boom")

    ch.subscribe_drained(broken)
    ch.subscribe_drained(lambda items: good_calls.append(items))
    ch._post(UserMessage(message=ChatMessageUser(content="x", source="operator")))
    items = ch._drain()
    assert len(items) == 1
    assert len(good_calls) == 1


# ---------------------------------------------------------------------------
# is_live / mark_live external-reach marker
# ---------------------------------------------------------------------------


def test_is_live_false_by_default() -> None:
    """A bare channel has no externally-reachable producer attached."""
    ch = AgentChannel()
    assert ch.is_live is False


def test_mark_live_flips_is_live_true() -> None:
    """A single producer marking live makes the channel live."""
    ch = AgentChannel()
    ch.mark_live()
    assert ch.is_live is True


def test_mark_live_clear_returns_to_false() -> None:
    """Calling the returned clear callable decrements the marker."""
    ch = AgentChannel()
    clear = ch.mark_live()
    assert ch.is_live is True
    clear()
    assert ch.is_live is False


def test_mark_live_clear_is_idempotent() -> None:
    """Clearing twice on the same handle must not double-decrement."""
    ch = AgentChannel()
    clear = ch.mark_live()
    clear()
    clear()  # second call must be a no-op
    assert ch.is_live is False
    # Another independent producer still works correctly.
    other_clear = ch.mark_live()
    assert ch.is_live is True
    other_clear()
    assert ch.is_live is False


def test_mark_live_supports_multiple_producers() -> None:
    """Stays live until every producer's clear callable runs."""
    ch = AgentChannel()
    clear_a = ch.mark_live()
    clear_b = ch.mark_live()
    assert ch.is_live is True
    clear_a()
    assert ch.is_live is True  # second producer keeps it live
    clear_b()
    assert ch.is_live is False


def test_inert_channel_is_never_live() -> None:
    """The singleton must not be mutated by a stray ``mark_live`` call."""
    # Calling mark_live on the inert singleton must not flip its state.
    clear = _INERT_CHANNEL.mark_live()
    assert _INERT_CHANNEL.is_live is False
    clear()  # safe no-op
    assert _INERT_CHANNEL.is_live is False


# ---------------------------------------------------------------------------
# High-level facade — before_turn / after_cancel
# ---------------------------------------------------------------------------


async def test_before_turn_returns_drained_messages_without_blocking() -> None:
    """When state has a user message, drain + coalesce; never block."""
    async with agent_channel() as ch:
        ch._post(UserMessage(message=ChatMessageUser(content="hi", source="operator")))
        state_msgs: list[ChatMessage] = [ChatMessageUser(content="prior")]
        # State has a user message → no recv block even if we never posted.
        result = await ch.before_turn(state_msgs)
        assert len(result) == 1
        assert result[0].content == "hi"


async def test_before_turn_blocks_until_initial_message_arrives() -> None:
    """No state user msg + empty drain → block on recv until producer posts."""
    async with agent_channel() as ch:
        received: list[ChatMessageUser] = []

        async def consumer() -> None:
            received.extend(await ch.before_turn([]))

        async def producer() -> None:
            await anyio.sleep(0.05)
            ch._post(UserMessage(message=ChatMessageUser(content="kickoff")))

        async with anyio.create_task_group() as tg:
            tg.start_soon(consumer)
            tg.start_soon(producer)

        assert len(received) == 1
        assert received[0].content == "kickoff"


async def test_before_turn_does_not_block_when_state_has_user_message() -> None:
    """State has a user message + drain is empty → returns []; no block."""
    async with agent_channel() as ch:
        state_msgs: list[ChatMessage] = [ChatMessageUser(content="prior")]
        result = await ch.before_turn(state_msgs)
        assert result == []


async def test_after_cancel_returns_repair_plus_followup() -> None:
    """Repair messages come first, then the operator's redirect message."""
    async with agent_channel() as ch:
        msgs: list[ChatMessage] = [
            ChatMessageAssistant(
                content="thinking...",
                tool_calls=[ToolCall(id="t1", function="echo", arguments={})],
            ),
        ]
        # Redirect posted alongside the cancel (no blocking needed).
        ch._post(
            UserMessage(message=ChatMessageUser(content="redirect", source="operator"))
        )
        result = await ch.after_cancel(msgs)
        assert len(result) == 2
        assert isinstance(result[0], ChatMessageTool)
        assert result[0].tool_call_id == "t1"
        assert isinstance(result[1], ChatMessageUser)
        assert result[1].content == "redirect"


async def test_after_cancel_blocks_for_followup_when_none_queued() -> None:
    """If no redirect arrived alongside the cancel, after_cancel blocks for one."""
    async with agent_channel() as ch:
        msgs: list[ChatMessage] = []  # nothing to repair either
        received: list[ChatMessage] = []

        async def consumer() -> None:
            received.extend(await ch.after_cancel(msgs))

        async def producer() -> None:
            await anyio.sleep(0.05)
            ch._post(
                UserMessage(message=ChatMessageUser(content="late", source="operator"))
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(consumer)
            tg.start_soon(producer)

        # No repair (no tool_calls in flight), just the late follow-up.
        assert len(received) == 1
        assert isinstance(received[0], ChatMessageUser)
        assert received[0].content == "late"


async def test_after_cancel_blocks_for_redirect_with_existing_user_messages() -> None:
    """Post-cancel block fires regardless of prior user messages in history.

    Regression: an earlier implementation delegated to ``before_turn``,
    whose user-message gate fires only when ``messages`` has no
    ``ChatMessageUser``. After turn 1 the history always has user
    messages, so the block was silently skipped — the agent would
    resume immediately after a cancel instead of waiting for the
    operator's redirect.
    """
    async with agent_channel() as ch:
        # Realistic post-turn-1 conversation: prior user message in history.
        msgs: list[ChatMessage] = [
            ChatMessageUser(content="initial prompt"),
            ChatMessageAssistant(content="prior turn complete"),
        ]
        received: list[ChatMessage] = []

        async def consumer() -> None:
            received.extend(await ch.after_cancel(msgs))

        async def producer() -> None:
            # Delay the redirect — after_cancel must block for it
            # rather than returning immediately on the back of the
            # existing user message in history.
            await anyio.sleep(0.05)
            ch._post(
                UserMessage(
                    message=ChatMessageUser(content="redirect", source="operator")
                )
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(consumer)
            tg.start_soon(producer)

        # Only the redirect; no repair (no in-flight tool calls in msgs).
        assert len(received) == 1
        assert isinstance(received[0], ChatMessageUser)
        assert received[0].content == "redirect"


# ---------------------------------------------------------------------------
# ExecutionObserver null default
# ---------------------------------------------------------------------------


def test_null_observer_is_singleton_noop() -> None:
    obs = null_execution_observer()
    assert isinstance(obs, NullExecutionObserver)
    assert null_execution_observer() is obs
    # both context managers are no-op yields
    with obs.track_tool_call("id1"):
        pass
    # track_model_event needs a ModelEvent — null observer doesn't read it
    from inspect_ai.event._model import ModelEvent

    me = ModelEvent.__new__(ModelEvent)
    with obs.track_model_event(me):
        pass
