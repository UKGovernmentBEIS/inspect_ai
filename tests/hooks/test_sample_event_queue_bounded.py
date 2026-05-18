"""Tests for the bounded sample event queue with drop-oldest semantics."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import anyio

from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.hooks._hooks import (
    SAMPLE_EVENT_QUEUE_CAPACITY,
    SampleEvent,
    emit_sample_event,
)
from inspect_ai.log._samples import ActiveSample, _sample_active
from inspect_ai.log._transcript import Transcript, init_transcript


@contextmanager
def _capture_hooks_warnings(caplog) -> Iterator[None]:
    """Capture WARNING records from the hooks logger exactly once each.

    A prior ``init_eval`` call may set ``propagate = False`` on the
    ``inspect_ai`` package logger, which would prevent records from reaching
    pytest's caplog handler on the root logger. We attach caplog's handler
    directly to the hooks logger and disable propagation for the duration of
    the context to avoid double-capturing the same record via both paths.
    """
    hooks_logger = logging.getLogger("inspect_ai.hooks._hooks")
    original_propagate = hooks_logger.propagate
    hooks_logger.addHandler(caplog.handler)
    hooks_logger.propagate = False
    try:
        with caplog.at_level(logging.WARNING, logger="inspect_ai.hooks._hooks"):
            yield
    finally:
        hooks_logger.removeHandler(caplog.handler)
        hooks_logger.propagate = original_propagate


def _make_active() -> ActiveSample:
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
        transcript=Transcript(),
        sandboxes={},
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
    )


def _filler_event(marker: str = "filler") -> LoggerEvent:
    return LoggerEvent(
        message=LoggingMessage(level="info", message=marker, created=0.0)
    )


def _marker_of(sample_event: SampleEvent) -> str:
    ev = sample_event.event
    assert isinstance(ev, LoggerEvent)
    msg = ev.message
    assert isinstance(msg, LoggingMessage)
    return msg.message


def test_emit_sample_event_under_capacity_does_not_block_or_warn(caplog) -> None:
    """Sends under capacity are delivered in order with no warning logged."""
    active = _make_active()
    sample_token = _sample_active.set(active)
    init_transcript(active.transcript)

    send_stream, receive_stream = anyio.create_memory_object_stream[SampleEvent](
        SAMPLE_EVENT_QUEUE_CAPACITY
    )
    active.event_send = send_stream
    active.event_receive = receive_stream

    try:
        total = 10
        with _capture_hooks_warnings(caplog):
            for i in range(total):
                emit_sample_event(
                    eval_set_id=None,
                    run_id="run-1",
                    eval_id="eval-1",
                    sample_id="sample-1",
                    event=_filler_event(f"event-{i}"),
                )

        drained: list[SampleEvent] = []
        while True:
            try:
                drained.append(receive_stream.receive_nowait())
            except (anyio.WouldBlock, anyio.EndOfStream):
                break

        drained_markers = [_marker_of(d) for d in drained]
        assert drained_markers == [f"event-{i}" for i in range(total)]

        saturation_warnings = [
            r for r in caplog.records if "queue saturated" in r.getMessage().lower()
        ]
        assert saturation_warnings == []
        assert active.event_queue_warned is False
    finally:
        _sample_active.reset(sample_token)
        init_transcript(Transcript())


def test_overflow_with_capacity_two_drops_oldest_keeps_newest_warns_once(
    caplog,
) -> None:
    """Overflow drops oldest, keeps newest, warns exactly once."""
    active = _make_active()
    sample_token = _sample_active.set(active)
    init_transcript(active.transcript)

    capacity = 2
    send_stream, receive_stream = anyio.create_memory_object_stream[SampleEvent](
        capacity
    )
    active.event_send = send_stream
    active.event_receive = receive_stream

    try:
        total = 5
        with _capture_hooks_warnings(caplog):
            for i in range(total):
                emit_sample_event(
                    eval_set_id=None,
                    run_id="run-1",
                    eval_id="eval-1",
                    sample_id="sample-1",
                    event=_filler_event(f"event-{i}"),
                )

        drained: list[SampleEvent] = []
        while True:
            try:
                drained.append(receive_stream.receive_nowait())
            except (anyio.WouldBlock, anyio.EndOfStream):
                break

        drained_markers = [_marker_of(d) for d in drained]
        assert drained_markers == [f"event-{i}" for i in range(total - capacity, total)]

        saturation_warnings = [
            r for r in caplog.records if "queue saturated" in r.getMessage().lower()
        ]
        assert len(saturation_warnings) == 1
        assert active.event_queue_warned is True
    finally:
        _sample_active.reset(sample_token)
        init_transcript(Transcript())
