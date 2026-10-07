"""Test sample event stream ownership and delivery with an unbounded queue.

The stream is created with math.inf capacity, so WouldBlock can never occur
and there is no need for a recursion guard.
"""

import logging
import math
import sys
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Literal

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from inspect_ai.dataset._dataset import Sample
from inspect_ai.event import InfoEvent
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.hooks import _hooks
from inspect_ai.hooks._hooks import (
    Hooks,
    SampleEvent,
    emit_sample_event,
)
from inspect_ai.log import _samples
from inspect_ai.log._samples import ActiveSample, _sample_active
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer


def test_emit_sample_event_unbounded_stream_never_blocks() -> None:
    """An unbounded stream should accept many events without raising WouldBlock."""
    active = _event_active_sample()
    sample_transcript = active.transcript
    sample_token = _sample_active.set(active)
    init_transcript(sample_transcript)

    send_stream, receive_stream = anyio.create_memory_object_stream[SampleEvent](
        math.inf
    )
    active.event_send = send_stream
    active.event_receive = receive_stream

    try:
        event = LoggerEvent(
            message=LoggingMessage(level="info", message="filler", created=0.0)
        )

        # Send many events — none should raise WouldBlock with an unbounded stream.
        for _ in range(2000):
            emit_sample_event(
                eval_set_id=None,
                run_id="run-1",
                eval_id="eval-1",
                sample_id="sample-1",
                event=event,
            )
    finally:
        send_stream.close()
        receive_stream.close()
        _sample_active.reset(sample_token)
        init_transcript(Transcript())


def _event_active_sample() -> ActiveSample:
    sample_transcript = Transcript()
    return ActiveSample(
        task="test_task",
        log_location="test",
        model="test_model",
        sample=Sample(input="test"),
        epoch=1,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=True,
        transcript=sample_transcript,
        sandboxes={},
        checkpointer=_NoopCheckpointer(),
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
        sample_uuid="sample-uuid-1",
    )


@contextmanager
def _event_sample() -> Iterator[ActiveSample]:
    active = _event_active_sample()
    token = _sample_active.set(active)
    init_transcript(active.transcript)
    try:
        yield active
    finally:
        if active.event_send is not None:
            active.event_send.close()
        if active.event_receive is not None:
            active.event_receive.close()
        _sample_active.reset(token)
        init_transcript(Transcript())


class _RecordingHook(Hooks):
    def __init__(
        self, hook_behavior: Literal["normal", "error", "closed", "blocked"] = "normal"
    ) -> None:
        self.events: list[str] = []
        self.hook_behavior = hook_behavior
        self.started = anyio.Event()
        self.release = anyio.Event()

    async def on_sample_event(self, data: SampleEvent) -> None:
        assert isinstance(data.event, InfoEvent)
        text = str(data.event.data)
        if text == "first" and self.hook_behavior == "blocked":
            self.started.set()
            await self.release.wait()
        self.events.append(text)
        if self.hook_behavior == "error":
            raise ValueError("hook failure")
        if self.hook_behavior == "closed":
            raise anyio.ClosedResourceError("hook closed")


def _install_hook(monkeypatch: pytest.MonkeyPatch, hook: Hooks) -> None:
    monkeypatch.setattr(_hooks, "get_all_hooks", lambda: [hook])


def _queue_event(active: ActiveSample, text: str) -> None:
    assert active.event_send is not None
    active.event_send.send_nowait(
        SampleEvent(
            eval_set_id=None,
            run_id="run-1",
            eval_id="eval-1",
            sample_id="sample-1",
            event=InfoEvent(data=text),
        )
    )


def _assert_closed(
    active: ActiveSample, receive: MemoryObjectReceiveStream[SampleEvent]
) -> None:
    stats = receive.statistics()
    assert stats.open_send_streams == stats.open_receive_streams == 0
    assert active.event_send is None
    assert active.event_receive is None
    assert active.event_done is None


@pytest.mark.parametrize("hook_behavior", ["normal", "error", "closed"])
async def test_event_emitter_closes_owned_receivers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    hook_behavior: Literal["normal", "error", "closed"],
) -> None:
    hook = _RecordingHook(hook_behavior)
    _install_hook(monkeypatch, hook)
    with _event_sample() as active:
        async with anyio.create_task_group() as tg:
            active.start(tg)
            _hooks.start_sample_event_emitter()
            receive = active.event_receive
            assert receive is not None
            assert receive.statistics().open_receive_streams == 2
            _queue_event(active, "first")
            _queue_event(active, "second")
            await _hooks.drain_sample_events()
        assert receive is not None
        _assert_closed(active, receive)
    assert hook.events == ["first", "second"]
    warnings = [
        record.message for record in caplog.records if record.levelname == "WARNING"
    ]
    if hook_behavior == "normal":
        assert warnings == []
    else:
        assert len(warnings) == 2
        assert all(
            "Exception calling hook '_RecordingHook':" in text for text in warnings
        )


async def test_cancelled_drain_preserves_live_emitter_events(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hook = _RecordingHook("blocked")
    _install_hook(monkeypatch, hook)
    with _event_sample() as active:
        async with anyio.create_task_group() as tg:
            active.start(tg)
            _hooks.start_sample_event_emitter()
            receive, done = active.event_receive, active.event_done
            assert receive is not None and done is not None
            _queue_event(active, "first")
            _queue_event(active, "second")
            await hook.started.wait()
            with anyio.CancelScope() as scope:
                scope.cancel()
                await _hooks.drain_sample_events()
            assert scope.cancelled_caught
            assert receive.statistics().open_send_streams == 0
            assert receive.statistics().open_receive_streams == 1
            assert active.event_receive is None
            assert active.event_done is None
            assert active.event_send is None
            assert not done.is_set()
            hook.release.set()
            with anyio.fail_after(2):
                await done.wait()
        assert receive is not None
        _assert_closed(active, receive)
    assert hook.events == ["first", "second"]
    assert not caplog.records


async def test_cancelled_emitter_retains_fallback_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook = _RecordingHook("blocked")
    _install_hook(monkeypatch, hook)
    with _event_sample() as active:
        async with anyio.create_task_group() as tg:
            active.start(tg)
            _hooks.start_sample_event_emitter()
            receive, done = active.event_receive, active.event_done
            assert receive is not None and done is not None
            _queue_event(active, "first")
            _queue_event(active, "second")
            await hook.started.wait()
            tg.cancel_scope.cancel()
        assert done is not None
        assert receive is not None
        assert done.is_set()
        assert receive.statistics().open_receive_streams == 1
        _queue_event(active, "scoring")
        await _hooks.drain_sample_events()
        _assert_closed(active, receive)
    assert hook.events == ["second", "scoring"]


async def test_failed_emitter_replacement_keeps_previous_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_hook(monkeypatch, _RecordingHook())
    with _event_sample() as active:
        async with anyio.create_task_group() as tg:
            active.start(tg)
            _hooks.start_sample_event_emitter()
            send, receive, done = (
                active.event_send,
                active.event_receive,
                active.event_done,
            )
            assert send is not None and receive is not None and done is not None
            active.start(anyio.create_task_group())
            with pytest.raises(RuntimeError, match="not active"):
                _hooks.start_sample_event_emitter()
            assert active.event_send is send
            assert active.event_receive is receive
            assert active.event_done is done
            assert receive.statistics().open_send_streams == 1
            assert receive.statistics().open_receive_streams == 2
            active.start(tg)
            await _hooks.drain_sample_events()
        assert receive is not None
        _assert_closed(active, receive)


@pytest.mark.parametrize(
    "teardown_failure",
    ["callback_error", "callback_base_exception", "checkpointer_error"],
)
async def test_sample_exit_closes_handles_when_teardown_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    teardown_failure: Literal[
        "callback_error", "callback_base_exception", "checkpointer_error"
    ],
) -> None:
    class TeardownError(BaseException):
        pass

    async def fail_callback() -> None:
        if teardown_failure == "callback_base_exception":
            raise TeardownError("callback teardown")
        raise ValueError("callback teardown")

    def fail_checkpointer() -> None:
        raise LookupError("checkpointer teardown")

    expected = (
        pytest.raises(TeardownError, match="callback teardown")
        if teardown_failure == "callback_base_exception"
        else pytest.raises(LookupError, match="checkpointer teardown")
        if teardown_failure == "checkpointer_error"
        else nullcontext()
    )
    receive: MemoryObjectReceiveStream[SampleEvent] | None = None
    active: ActiveSample | None = None
    token = _sample_active.set(None)
    try:
        with expected:
            async with _samples.active_sample(
                task="test_task",
                log_location="test",
                model="mockllm/model",
                sample=Sample(id=1, input="test"),
                epoch=1,
                message_limit=None,
                token_limit=None,
                cost_limit=None,
                time_limit=None,
                working_limit=None,
                fails_on_error=True,
                transcript=Transcript(),
                eval_id="eval-1",
                run_id="run-1",
                sample_uuid="sample-1",
            ) as active:
                async with anyio.create_task_group() as tg:
                    active.start(tg)
                    _hooks.start_sample_event_emitter()
                    receive = active.event_receive
                    assert receive is not None
                    tg.cancel_scope.cancel()
                assert receive is not None
                assert receive.statistics().open_receive_streams == 1
                if teardown_failure == "checkpointer_error":
                    monkeypatch.setattr(active.checkpointer, "close", fail_checkpointer)
                else:
                    active.on_complete = fail_callback
        assert active is not None
        assert receive is not None
        _assert_closed(active, receive)
        warnings = [
            record for record in caplog.records if record.levelno == logging.WARNING
        ]
        if teardown_failure == "callback_error":
            assert len(warnings) == 1
            assert warnings[0].name == _samples.logger.name
            assert (
                warnings[0].message.removeprefix("sample=1\n")
                == "ActiveSample on_complete hook raised"
            )
        else:
            assert warnings == []
    finally:
        if receive is not None:
            receive.close()
        if active is not None:
            if active.event_send is not None:
                active.event_send.close()
            if active in _samples._active_samples:
                _samples._active_samples.remove(active)
        _sample_active.reset(token)


async def test_timed_out_drain_preserves_live_callback_and_reused_emitter(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hook = _RecordingHook("blocked")
    _install_hook(monkeypatch, hook)
    with _event_sample() as active:
        async with anyio.create_task_group() as tg:
            active.start(tg)
            _hooks.start_sample_event_emitter()
            receive, done = active.event_receive, active.event_done
            assert receive is not None and done is not None
            _queue_event(active, "first")
            _queue_event(active, "second")
            await hook.started.wait()
            await _hooks.drain_sample_events()
            assert not done.is_set()
            assert receive.statistics().open_receive_streams == 1
            _hooks.start_sample_event_emitter()
            new_receive, new_done = active.event_receive, active.event_done
            assert new_receive is not None and new_done is not None
            _queue_event(active, "third")
            hook.release.set()
            with anyio.fail_after(2):
                await done.wait()
            assert active.event_receive is new_receive and active.event_done is new_done
            await _hooks.drain_sample_events()
        assert receive is not None
        assert new_receive is not None
        _assert_closed(active, receive)
        _assert_closed(active, new_receive)
    assert sorted(hook.events) == ["first", "second", "third"]
    assert len(caplog.records) == 1
    warning = caplog.records[0]
    assert warning.levelno == logging.WARNING
    assert warning.name == _hooks.logger.name
    assert (
        warning.message.removeprefix("sample=None\n")
        == "Timed out waiting for sample event emitter to drain"
    )


async def test_drain_keeps_replacement_emitter_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReplacingHook(Hooks):
        async def on_sample_event(self, data: SampleEvent) -> None:
            _hooks.start_sample_event_emitter()

    _install_hook(monkeypatch, ReplacingHook())
    with _event_sample() as active:
        async with anyio.create_task_group() as tg:
            active.start(tg)
            send, receive = anyio.create_memory_object_stream[SampleEvent](math.inf)
            active.event_send, active.event_receive = send, receive
            done = anyio.Event()
            done.set()
            active.event_done = done
            _queue_event(active, "replacement")
            await _hooks.drain_sample_events()
            new_receive = active.event_receive
            assert new_receive is not None and new_receive is not receive
            stats = receive.statistics()
            assert stats.open_send_streams == stats.open_receive_streams == 0
            await _hooks.drain_sample_events()
        assert new_receive is not None
        _assert_closed(active, new_receive)


async def test_failed_emitter_handoff_closes_all_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers: list[MemoryObjectReceiveStream[SampleEvent]] = []
    clone = MemoryObjectReceiveStream.clone

    def track_clone(
        self: MemoryObjectReceiveStream[SampleEvent],
    ) -> MemoryObjectReceiveStream[SampleEvent]:
        owned = clone(self)
        receivers.extend([self, owned])
        return owned

    monkeypatch.setattr(MemoryObjectReceiveStream, "clone", track_clone)
    with _event_sample() as active:
        active.start(anyio.create_task_group())
        with pytest.raises(RuntimeError, match="not active"):
            _hooks.start_sample_event_emitter()
        assert len(receivers) == 2
        for receive in receivers:
            _assert_closed(active, receive)


async def test_unexpected_emitter_receiver_close_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receivers: list[MemoryObjectReceiveStream[SampleEvent]] = []
    clone = MemoryObjectReceiveStream.clone

    def track_clone(
        self: MemoryObjectReceiveStream[SampleEvent],
    ) -> MemoryObjectReceiveStream[SampleEvent]:
        owned = clone(self)
        receivers.append(owned)
        return owned

    monkeypatch.setattr(MemoryObjectReceiveStream, "clone", track_clone)
    with _event_sample() as active:
        with pytest.raises(ExceptionGroup) as caught:
            async with anyio.create_task_group() as tg:
                active.start(tg)
                _hooks.start_sample_event_emitter()
                receivers[0].close()
        assert any(
            isinstance(ex, anyio.ClosedResourceError) for ex in caught.value.exceptions
        )
        receive = active.event_receive
        assert receive is not None
        await _hooks.drain_sample_events()
        _assert_closed(active, receive)
