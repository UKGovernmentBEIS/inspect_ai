"""Phase 3 unit tests for ``AcpSession`` cancel/inject mechanics."""

from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest

from inspect_ai.agent import acp_session
from inspect_ai.agent._acp._session import (
    TurnCancelled,
    _LiveAcpSession,
    _NoOpAcpSession,
)
from inspect_ai.event import InterruptEvent, ModelEvent
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import ChatMessageTool, ChatMessageUser

if TYPE_CHECKING:
    from inspect_ai.agent._agent import AgentState


def _empty_state() -> "AgentState":
    """Construct a minimal AgentState with no user messages."""
    from inspect_ai.agent._agent import AgentState

    return AgentState(messages=[])


def _state_with_user(text: str = "seed") -> "AgentState":
    from inspect_ai.agent._agent import AgentState

    return AgentState(messages=[ChatMessageUser(content=text)])


async def test_turn_scope_exits_cleanly_when_nothing_happens() -> None:
    async with acp_session() as acp:
        with acp.turn_scope():
            pass
        # No exception raised; we got here.


async def test_client_cancel_raises_turn_cancelled() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            raised: list[type] = []
            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            await anyio.sleep_forever()
                    except TurnCancelled:
                        raised.append(TurnCancelled)

                async def producer() -> None:
                    await anyio.sleep(0.05)
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop)
                tg.start_soon(producer)
            assert raised == [TurnCancelled]
    finally:
        _transcript.reset(token)


async def test_sample_level_cancel_re_propagates() -> None:
    """Outer-scope cancel propagates as CancelledError, not TurnCancelled."""
    async with acp_session() as acp:
        cancelled_exc_type = anyio.get_cancelled_exc_class()
        captured: list[type] = []

        async with anyio.create_task_group() as outer_tg:

            async def agent_loop() -> None:
                try:
                    with acp.turn_scope():
                        await anyio.sleep_forever()
                except TurnCancelled:
                    captured.append(TurnCancelled)
                except cancelled_exc_type:
                    captured.append(cancelled_exc_type)
                    raise

            async def killer() -> None:
                await anyio.sleep(0.05)
                outer_tg.cancel_scope.cancel()

            outer_tg.start_soon(agent_loop)
            outer_tg.start_soon(killer)

        assert TurnCancelled not in captured
        # The agent_loop body should have seen a CancelledError, not TurnCancelled.
        assert cancelled_exc_type in captured


async def test_submit_then_before_turn_returns_message() -> None:
    async with acp_session() as acp:
        acp.submit_user_message(ChatMessageUser(content="hi"))
        messages = await acp.before_turn(_state_with_user())
        assert len(messages) == 1
        assert messages[0].content == "hi"


async def test_before_turn_blocks_on_first_call_with_empty_state() -> None:
    async with acp_session() as acp:
        result: list[list[ChatMessageUser]] = []

        async with anyio.create_task_group() as tg:

            async def agent() -> None:
                messages = await acp.before_turn(_empty_state())
                result.append(messages)

            async def producer() -> None:
                await anyio.sleep(0.05)
                acp.submit_user_message(ChatMessageUser(content="first prompt"))

            tg.start_soon(agent)
            tg.start_soon(producer)

        assert len(result) == 1
        assert len(result[0]) == 1
        assert result[0][0].content == "first prompt"


async def test_before_turn_does_not_block_on_second_call() -> None:
    async with acp_session() as acp:
        # First call with non-empty state — doesn't block, sets the flag.
        await acp.before_turn(_state_with_user())
        # Second call with empty state — must not block.
        with anyio.move_on_after(0.5) as scope:
            messages = await acp.before_turn(_empty_state())
        assert not scope.cancelled_caught, "before_turn blocked when it shouldn't"
        assert messages == []


async def test_after_cancel_drains_queued_messages() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            results: list[list] = []
            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            await anyio.sleep_forever()
                    except TurnCancelled:
                        results.append(await acp.after_cancel())

                async def producer() -> None:
                    await anyio.sleep(0.05)
                    acp.submit_user_message(ChatMessageUser(content="follow-up"))
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop)
                tg.start_soon(producer)

            assert len(results) == 1
            assert len(results[0]) == 1
            assert results[0][0].content == "follow-up"
    finally:
        _transcript.reset(token)


async def test_after_cancel_synthesizes_tool_repair_message() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            results: list[list] = []
            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            with acp.track_tool_call("tc-1"):
                                await anyio.sleep_forever()
                    except TurnCancelled:
                        results.append(await acp.after_cancel())

                async def producer() -> None:
                    await anyio.sleep(0.05)
                    acp.submit_user_message(ChatMessageUser(content="please stop"))
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop)
                tg.start_soon(producer)

            assert len(results) == 1
            msgs = results[0]
            assert len(msgs) == 2
            repair = msgs[0]
            assert isinstance(repair, ChatMessageTool)
            assert repair.tool_call_id == "tc-1"
            assert repair.error is not None
            assert repair.error.type == "cancelled"
            assert msgs[1].content == "please stop"
    finally:
        _transcript.reset(token)


async def test_after_cancel_repairs_multiple_tool_calls() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            results: list[list] = []
            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            with acp.track_tool_call("tc-1"):
                                with acp.track_tool_call("tc-2"):
                                    await anyio.sleep_forever()
                    except TurnCancelled:
                        results.append(await acp.after_cancel())

                async def producer() -> None:
                    await anyio.sleep(0.05)
                    acp.submit_user_message(ChatMessageUser(content="halt"))
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop)
                tg.start_soon(producer)

            assert len(results) == 1
            msgs = results[0]
            tool_msgs = [m for m in msgs if isinstance(m, ChatMessageTool)]
            assert len(tool_msgs) == 2
            assert {m.tool_call_id for m in tool_msgs} == {"tc-1", "tc-2"}
    finally:
        _transcript.reset(token)


async def test_after_cancel_blocks_until_message_arrives() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            results: list[list] = []
            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            await anyio.sleep_forever()
                    except TurnCancelled:
                        results.append(await acp.after_cancel())

                async def producer() -> None:
                    await anyio.sleep(0.05)
                    acp.cancel_current_turn()
                    # Defer the message — after_cancel should block.
                    await anyio.sleep(0.1)
                    acp.submit_user_message(ChatMessageUser(content="late"))

                tg.start_soon(agent_loop)
                tg.start_soon(producer)

            assert len(results) == 1
            assert len(results[0]) == 1
            assert results[0][0].content == "late"
    finally:
        _transcript.reset(token)


async def test_cancel_during_tool_call_emits_correct_interrupt_event() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            with acp.track_tool_call("tc-X"):
                                await anyio.sleep_forever()
                    except TurnCancelled:
                        pass

                async def producer() -> None:
                    await anyio.sleep(0.05)
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop)
                tg.start_soon(producer)

            events = [e for e in transcript.events if isinstance(e, InterruptEvent)]
            assert len(events) == 1
            ev = events[0]
            assert ev.source == "user_cancel"
            assert ev.interrupted == "tool_call"
            assert ev.interrupted_tool_call_id == "tc-X"
            assert ev.interrupted_model_event_id is None
    finally:
        _transcript.reset(token)


async def test_cancel_during_generate_emits_correct_interrupt_event() -> None:
    """Producer task fires cancel; agent task tracks the model event.

    The two tasks have separate ContextVar copies, so the session-level
    ``track_model_event`` is what makes the active event visible to the
    cancelling task. This is the production shape (transport task ↔
    agent task) — the test must mirror it.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            fake_model_event = ModelEvent(
                model="mock",
                input=[],
                tools=[],
                tool_choice="auto",
                config=cast("Any", {}),
                output=cast("Any", {"model": "mock", "choices": []}),
            )

            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            with acp.track_model_event(fake_model_event):
                                await anyio.sleep_forever()
                    except TurnCancelled:
                        pass

                async def producer() -> None:
                    await anyio.sleep(0.05)
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop)
                tg.start_soon(producer)

            events = [e for e in transcript.events if isinstance(e, InterruptEvent)]
            assert len(events) == 1
            ev = events[0]
            assert ev.source == "user_cancel"
            assert ev.interrupted == "generate"
            assert ev.interrupted_model_event_id == fake_model_event.uuid
            assert ev.interrupted_tool_call_id is None
    finally:
        _transcript.reset(token)


async def test_track_model_event_save_restore_handles_nesting() -> None:
    """Nested ``track_model_event`` restores the outer event on exit."""
    async with acp_session() as acp:
        live = cast(_LiveAcpSession, acp)
        outer = ModelEvent(
            model="m-outer",
            input=[],
            tools=[],
            tool_choice="auto",
            config=cast("Any", {}),
            output=cast("Any", {"model": "m-outer", "choices": []}),
        )
        inner = ModelEvent(
            model="m-inner",
            input=[],
            tools=[],
            tool_choice="auto",
            config=cast("Any", {}),
            output=cast("Any", {"model": "m-inner", "choices": []}),
        )
        with acp.track_model_event(outer):
            assert live._active_model_event is outer
            with acp.track_model_event(inner):
                assert live._active_model_event is inner
            assert live._active_model_event is outer
        assert live._active_model_event is None


async def test_submit_user_message_normalizes_source_to_operator() -> None:
    """``submit_user_message`` enforces operator provenance on every msg."""
    async with acp_session() as acp:
        # Source unset → normalized to "operator".
        acp.submit_user_message(ChatMessageUser(content="no source"))
        # Source already "operator" → preserved unchanged.
        acp.submit_user_message(ChatMessageUser(content="explicit", source="operator"))
        # Source from dataset ("input") → overridden to "operator" since
        # the message is being injected by an ACP client.
        acp.submit_user_message(ChatMessageUser(content="was input", source="input"))

        messages = await acp.before_turn(_state_with_user())
        assert [m.source for m in messages] == ["operator", "operator", "operator"]
        assert [m.content for m in messages] == ["no source", "explicit", "was input"]


async def test_submit_user_message_does_not_mutate_caller_instance() -> None:
    """Normalization uses ``model_copy`` so the caller's instance is untouched."""
    async with acp_session() as acp:
        original = ChatMessageUser(content="hi")
        assert original.source is None
        acp.submit_user_message(original)
        # Caller's original instance keeps its prior source.
        assert original.source is None


async def test_cancel_between_turns_emits_interrupt_event() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            # No turn_scope, no tool tracking, no active model event.
            acp.cancel_current_turn()

            events = [e for e in transcript.events if isinstance(e, InterruptEvent)]
            assert len(events) == 1
            ev = events[0]
            assert ev.source == "user_cancel"
            assert ev.interrupted == "between_turns"
            assert ev.interrupted_tool_call_id is None
            assert ev.interrupted_model_event_id is None
    finally:
        _transcript.reset(token)


async def test_cancel_between_turns_preserves_queued_message() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            acp.cancel_current_turn()  # No-op cancel, between turns
            acp.submit_user_message(ChatMessageUser(content="next"))
            # First-call flag already tripped by the cancel? No — cancel doesn't
            # call before_turn. State has user message so won't block anyway.
            messages = await acp.before_turn(_state_with_user())
            assert len(messages) == 1
            assert messages[0].content == "next"
    finally:
        _transcript.reset(token)


async def test_turn_scope_state_resets_between_turns() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            live = cast(_LiveAcpSession, acp)

            # First turn: cancel inside a tool call.
            async with anyio.create_task_group() as tg:

                async def agent_loop_1() -> None:
                    try:
                        with acp.turn_scope():
                            with acp.track_tool_call("tc-A"):
                                await anyio.sleep_forever()
                    except TurnCancelled:
                        await acp.after_cancel()

                async def producer_1() -> None:
                    await anyio.sleep(0.05)
                    acp.submit_user_message(ChatMessageUser(content="m1"))
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop_1)
                tg.start_soon(producer_1)

            # State should be clean — no leftover flag, no leftover tool ids.
            assert live._pending_turn_cancel is False
            assert live._cancelled_tool_call_ids == []
            assert live._in_flight_tool_calls == []

            # Second turn: cancel again, with a different tool.
            async with anyio.create_task_group() as tg:

                async def agent_loop_2() -> None:
                    try:
                        with acp.turn_scope():
                            with acp.track_tool_call("tc-B"):
                                await anyio.sleep_forever()
                    except TurnCancelled:
                        msgs = await acp.after_cancel()
                        # Repair only "tc-B", not "tc-A" from the prior turn.
                        tool_msgs = [m for m in msgs if isinstance(m, ChatMessageTool)]
                        assert len(tool_msgs) == 1
                        assert tool_msgs[0].tool_call_id == "tc-B"

                async def producer_2() -> None:
                    await anyio.sleep(0.05)
                    acp.submit_user_message(ChatMessageUser(content="m2"))
                    acp.cancel_current_turn()

                tg.start_soon(agent_loop_2)
                tg.start_soon(producer_2)
    finally:
        _transcript.reset(token)


async def test_track_tool_call_cleanup_on_exception() -> None:
    async with acp_session() as acp:
        live = cast(_LiveAcpSession, acp)
        with pytest.raises(RuntimeError):
            with acp.track_tool_call("tc-err"):
                raise RuntimeError("boom")
        assert live._in_flight_tool_calls == []


async def test_noop_session_variants_are_safe() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        noop = _NoOpAcpSession()
        # turn_scope: yields, exits cleanly.
        with noop.turn_scope():
            pass
        # before_turn: returns empty list.
        assert await noop.before_turn(_empty_state()) == []
        # after_cancel: returns empty list, does not block.
        assert await noop.after_cancel() == []
        # submit_user_message: no-op, no error.
        noop.submit_user_message(ChatMessageUser(content="x"))
        # cancel_current_turn: must NOT record an InterruptEvent on the
        # parent transcript when called on the no-op (sub-agents don't
        # emit cancel events into the top-level transcript).
        noop.cancel_current_turn()
        # track_tool_call: yields, exits cleanly.
        with noop.track_tool_call("ignored"):
            pass
        # Transcript stays empty.
        assert [e for e in transcript.events if isinstance(e, InterruptEvent)] == []
    finally:
        _transcript.reset(token)


async def test_race_cancel_arrives_as_turn_completes() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        async with acp_session() as acp:
            # Agent enters and exits immediately; cancel fires moments later.
            async with anyio.create_task_group() as tg:

                async def agent_loop() -> None:
                    try:
                        with acp.turn_scope():
                            pass  # immediate exit
                    except TurnCancelled:
                        pytest.fail(
                            "TurnCancelled should not fire after a clean scope exit"
                        )

                async def producer() -> None:
                    # Let the agent's turn_scope exit first.
                    await anyio.sleep(0.05)
                    acp.submit_user_message(ChatMessageUser(content="queued"))
                    acp.cancel_current_turn()  # No-op: scope already gone.

                tg.start_soon(agent_loop)
                tg.start_soon(producer)

            # The submitted message should survive for the next before_turn.
            messages = await acp.before_turn(_state_with_user())
            assert len(messages) == 1
            assert messages[0].content == "queued"
    finally:
        _transcript.reset(token)
