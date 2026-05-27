from inspect_ai import Task, eval
from inspect_ai._util.constants import DEFAULT_LOG_MODEL_API_CALLS
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, ModelOutput
from inspect_ai.model._model_call import ModelCall
from inspect_ai.solver import generate


def test_log_model_api_false_strips_call():
    """When log_model_api=False, model call data is stripped."""
    log = eval(
        Task(
            dataset=[Sample(input="Say hello")],
            solver=[generate()],
        ),
        model="mockllm/model",
        log_model_api=False,
    )[0]
    assert log.samples
    model_events = [
        event for event in log.samples[0].events if isinstance(event, ModelEvent)
    ]
    assert len(model_events) > 0
    for event in model_events:
        assert event.call is None


def test_log_model_api_true_preserves_call():
    """When log_model_api=True, model call data is preserved."""
    log = eval(
        Task(
            dataset=[Sample(input="Say hello")],
            solver=[generate()],
        ),
        model="mockllm/model",
        log_model_api=True,
    )[0]
    assert log.samples
    model_events = [
        event for event in log.samples[0].events if isinstance(event, ModelEvent)
    ]
    assert len(model_events) > 0
    for event in model_events:
        assert event.call is not None
        assert event.call.request is not None
        assert event.call.response is not None


def test_log_model_api_error_call_always_preserved():
    """Error calls are preserved even when log_model_api=False."""
    transcript = Transcript(log_model_api=False)
    init_transcript(transcript)

    call = ModelCall.create({"model": "test"}, None)
    call.set_error({"error": "bad request"})
    event = ModelEvent(
        model="test",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test", choices=[]),
        call=call,
    )

    transcript._process_event(event)
    assert event.call is not None
    assert event.call.error is True


def test_log_model_api_non_error_call_stripped():
    """Non-error calls are stripped when log_model_api=False."""
    transcript = Transcript(log_model_api=False)
    init_transcript(transcript)

    call = ModelCall.create({"model": "test"}, {"content": "hello"})
    event = ModelEvent(
        model="test",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test", choices=[]),
        call=call,
    )

    transcript._process_event(event)
    assert event.call is None


def _make_model_event(model: str = "test/model") -> ModelEvent:
    call = ModelCall.create({"model": model}, {"content": "hello"})
    return ModelEvent(
        model=model,
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model=model, choices=[]),
        call=call,
    )


def test_log_model_api_default_keeps_first_n():
    """Default (None) keeps the first N calls per model."""
    transcript = Transcript(log_model_api=None)
    init_transcript(transcript)

    events = [_make_model_event() for _ in range(DEFAULT_LOG_MODEL_API_CALLS + 3)]
    for event in events:
        transcript._event(event)

    for event in events[:DEFAULT_LOG_MODEL_API_CALLS]:
        assert event.call is not None

    for event in events[DEFAULT_LOG_MODEL_API_CALLS:]:
        assert event.call is None


def test_log_model_api_default_per_model_counting():
    """Default mode counts calls independently per model."""
    transcript = Transcript(log_model_api=None)
    init_transcript(transcript)

    for _ in range(DEFAULT_LOG_MODEL_API_CALLS + 1):
        transcript._event(_make_model_event("model/a"))
        transcript._event(_make_model_event("model/b"))

    events_a = [
        e
        for e in transcript._events
        if isinstance(e, ModelEvent) and e.model == "model/a"
    ]
    events_b = [
        e
        for e in transcript._events
        if isinstance(e, ModelEvent) and e.model == "model/b"
    ]

    assert sum(1 for e in events_a if e.call is not None) == DEFAULT_LOG_MODEL_API_CALLS
    assert sum(1 for e in events_b if e.call is not None) == DEFAULT_LOG_MODEL_API_CALLS


def test_log_model_api_default_error_always_kept():
    """Error calls are kept even beyond the N limit in default mode."""
    transcript = Transcript(log_model_api=None)
    init_transcript(transcript)

    for _ in range(DEFAULT_LOG_MODEL_API_CALLS):
        transcript._event(_make_model_event())

    error_call = ModelCall.create({"model": "test/model"}, None)
    error_call.set_error({"error": "bad request"})
    error_event = ModelEvent(
        model="test/model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test/model", choices=[]),
        call=error_call,
    )
    transcript._event(error_event)

    assert error_event.call is not None
    assert error_event.call.error is True


def test_log_model_api_default_refire_preserves():
    """Re-firing _process_event on a kept event doesn't discard it."""
    transcript = Transcript(log_model_api=None)
    init_transcript(transcript)

    event = _make_model_event()
    transcript._event(event)
    assert event.call is not None

    transcript._event_updated(event)
    assert event.call is not None
