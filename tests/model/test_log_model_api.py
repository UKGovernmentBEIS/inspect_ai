from inspect_ai import Task, eval
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
