"""ModelEvent timing for attempt_timeout retry paths."""

# pyright: reportImplicitRelativeImport=false

from _helpers.event_assertions import assert_attempt_group, model_events
from _helpers.retry_provider import SlowThenSuccessAPI
from tenacity import RetryError

from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, get_model


async def test_attempt_timeout_retry_then_success_has_per_attempt_timing() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    model = get_model("mockllm/test", memoize=False)
    model.api = SlowThenSuccessAPI(slow_seconds=2.0)

    await model.generate(
        "hello", config=GenerateConfig(attempt_timeout=1, max_retries=3)
    )

    events = model_events(transcript)
    assert len(events) == 2
    assert events[0].error is not None
    assert events[0].completed is not None
    assert events[0].working_time is not None
    assert_attempt_group(events, retries=1, terminal_kind="success")


async def test_exhausted_attempt_timeouts_finalize_terminal_event() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    model = get_model("mockllm/test", memoize=False)
    model.api = SlowThenSuccessAPI(slow_seconds=2.0)

    try:
        await model.generate(
            "hello", config=GenerateConfig(attempt_timeout=1, max_retries=0)
        )
    except RetryError:
        pass

    events = model_events(transcript)
    # max_retries=0 permits no retries (a single attempt), so the timeout
    # exhausts the retry budget immediately
    assert len(events) == 1
    assert events[0].error is not None
    assert events[0].completed is not None
    assert events[0].working_time is not None
    assert events[0].call_started_at is not None
    assert events[0].call_completed_at is not None
