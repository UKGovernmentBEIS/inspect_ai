"""Test that emit_sample_event works correctly with an unbounded stream.

The stream is created with math.inf capacity, so WouldBlock can never occur
and there is no need for a recursion guard.
"""

import math

from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._logger import LoggerEvent, LoggingMessage
from inspect_ai.hooks._hooks import (
    SampleEvent,
    emit_sample_event,
)
from inspect_ai.log._samples import ActiveSample, _sample_active
from inspect_ai.log._transcript import Transcript, init_transcript


def test_emit_sample_event_unbounded_stream_never_blocks() -> None:
    """An unbounded stream should accept many events without raising WouldBlock."""
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

    import anyio

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
        _sample_active.reset(sample_token)
        init_transcript(Transcript())
