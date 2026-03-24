"""Test that emit_sample_event does not infinitely recurse when the queue is full.

Reproduces the bug where:
  emit_sample_event → logger.warning("queue full")
  → LogHandler.emit → log_to_transcript
  → transcript()._event(LoggerEvent)
  → on_sample_event callback → emit_sample_event  (infinite recursion)
"""

import logging

from inspect_ai._util.logger import log_to_transcript
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event import Event
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.hooks._hooks import (
    SampleEvent,
    emit_sample_event,
)
from inspect_ai.log._samples import ActiveSample, _sample_active
from inspect_ai.log._transcript import Transcript, init_transcript


class _TranscriptRelayHandler(logging.Handler):
    """Reproduces what the real LogHandler does: relay log records into the transcript."""

    def emit(self, record: logging.LogRecord) -> None:
        log_to_transcript(record)


def test_emit_sample_event_no_recursion_when_queue_full() -> None:
    """Full-queue emit_sample_event must not recurse via the logging pipeline.

    Sets up the same wiring that task/run.py creates — a Transcript subscribed
    to an event callback that calls emit_sample_event — then fills the queue and
    verifies the next emit silently drops instead of hitting RecursionError.
    """
    # -- Set up ActiveSample and the transcript, mirroring task/run.py ----------
    sample_transcript = Transcript()
    active = ActiveSample(
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
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
    )
    sample_token = _sample_active.set(active)
    init_transcript(sample_transcript)

    # -- Wire transcript → emit_sample_event (same pattern as task/run.py) -----
    def on_sample_event(event: Event) -> None:
        emit_sample_event(
            eval_set_id=None,
            run_id="run-1",
            eval_id="eval-1",
            sample_id="sample-1",
            event=event,
        )

    sample_transcript._subscribe(on_sample_event)

    # -- Start the event emitter (creates the send/receive queue on active) ----
    # start_sample_event_emitter needs active.tg, but we only need the queue it
    # creates — not the background consumer.  Manually create a tiny queue
    # (capacity 1) so it fills immediately, which is what triggers the bug.
    import anyio

    send_stream, receive_stream = anyio.create_memory_object_stream[SampleEvent](1)
    active.event_send = send_stream
    active.event_receive = receive_stream

    # -- Install a logging handler that relays to log_to_transcript, -----------
    # reproducing the real LogHandler.emit → log_to_transcript chain.
    hooks_logger = logging.getLogger("inspect_ai.hooks._hooks")
    relay_handler = _TranscriptRelayHandler()
    relay_handler.setLevel(logging.WARNING)
    hooks_logger.addHandler(relay_handler)

    try:
        event = LoggerEvent(
            message=LoggingMessage(level="info", message="filler", created=0.0)
        )

        # Fill the single-slot queue.
        emit_sample_event(
            eval_set_id=None,
            run_id="run-1",
            eval_id="eval-1",
            sample_id="sample-1",
            event=event,
        )

        # Queue is now full.  Without the fix this recurses infinitely:
        #   emit_sample_event → WouldBlock → logger.warning
        #   → relay handler → log_to_transcript → transcript._event
        #   → on_sample_event → emit_sample_event → …
        emit_sample_event(
            eval_set_id=None,
            run_id="run-1",
            eval_id="eval-1",
            sample_id="sample-1",
            event=event,
        )
    finally:
        hooks_logger.removeHandler(relay_handler)
        _sample_active.reset(sample_token)
        init_transcript(Transcript())  # restore default
