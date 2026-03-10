from inspect_ai.event._model import ModelEvent
from inspect_ai.log._condense import (
    condense_sample,
    delta_encode_model_inputs,
    resolve_input_deltas,
    resolve_sample_attachments,
)
from inspect_ai.log._log import EvalSample
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


def _make_model_event(input: list) -> ModelEvent:
    return ModelEvent(
        model="test-model",
        input=input,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )


def test_delta_encode_and_resolve_round_trip() -> None:
    """Test that delta encoding followed by resolving produces the original."""
    msg1 = ChatMessageUser(content="hello")
    msg2 = ChatMessageAssistant(content="hi there")
    msg3 = ChatMessageUser(content="how are you?")
    msg4 = ChatMessageAssistant(content="I'm fine")
    msg5 = ChatMessageUser(content="great")

    # Simulate multi-turn: each ModelEvent has growing input
    events = [
        _make_model_event([msg1]),
        _make_model_event([msg1, msg2, msg3]),
        _make_model_event([msg1, msg2, msg3, msg4, msg5]),
    ]

    # Save original inputs for comparison
    original_inputs = [list(e.input) for e in events]

    # Delta encode
    encoded = delta_encode_model_inputs(events)

    # First event should keep full input
    assert not encoded[0].input_delta
    assert len(encoded[0].input) == 1

    # Second event should be delta-encoded (only new messages)
    assert encoded[1].input_delta
    assert len(encoded[1].input) == 2  # msg2, msg3

    # Third event should be delta-encoded
    assert encoded[2].input_delta
    assert len(encoded[2].input) == 2  # msg4, msg5

    # Resolve
    resolved = resolve_input_deltas(encoded)

    # Should match originals
    for i, event in enumerate(resolved):
        assert not event.input_delta
        assert event.input == original_inputs[i]


def test_delta_encode_no_shared_prefix() -> None:
    """Events with no shared prefix are not delta-encoded."""
    msg1 = ChatMessageUser(content="hello")
    msg2 = ChatMessageUser(content="different")

    events = [
        _make_model_event([msg1]),
        _make_model_event([msg2]),
    ]

    encoded = delta_encode_model_inputs(events)
    assert not encoded[0].input_delta
    assert not encoded[1].input_delta


def test_delta_encode_partial_shared_prefix_not_encoded() -> None:
    """Events that diverge after a shared prefix are not delta-encoded."""
    msg1 = ChatMessageUser(content="hello")
    msg2 = ChatMessageUser(content="there")
    msg3 = ChatMessageUser(content="different")

    events = [
        _make_model_event([msg1, msg2]),
        _make_model_event([msg1, msg3]),
    ]

    encoded = delta_encode_model_inputs(events)
    assert not encoded[0].input_delta
    assert not encoded[1].input_delta
    assert encoded[1].input == [msg1, msg3]


def test_delta_encode_shrinking_input_not_encoded() -> None:
    """Events with shrinking input are not delta-encoded."""
    msg1 = ChatMessageUser(content="hello")
    msg2 = ChatMessageUser(content="there")
    msg3 = ChatMessageUser(content="more")

    events = [
        _make_model_event([msg1, msg2, msg3]),
        _make_model_event([msg1, msg2]),
    ]

    encoded = delta_encode_model_inputs(events)
    assert not encoded[0].input_delta
    assert not encoded[1].input_delta
    assert encoded[1].input == [msg1, msg2]


def test_delta_encode_single_event() -> None:
    """A single event is never delta-encoded."""
    msg1 = ChatMessageUser(content="hello")
    events = [_make_model_event([msg1])]

    encoded = delta_encode_model_inputs(events)
    assert not encoded[0].input_delta
    assert len(encoded[0].input) == 1


def test_condense_sample_applies_delta_encoding() -> None:
    """Test that condense_sample delta-encodes ModelEvent inputs."""
    msg1 = ChatMessageUser(content="hello")
    msg2 = ChatMessageAssistant(content="hi")
    msg3 = ChatMessageUser(content="bye")

    events = [
        _make_model_event([msg1]),
        _make_model_event([msg1, msg2, msg3]),
    ]

    sample = EvalSample(
        id="test",
        epoch=1,
        input="test",
        target="target",
        messages=[],
        events=events,
        output={},
        scores={},
    )

    condensed = condense_sample(sample, log_images=True)

    # Second event should be delta-encoded
    model_events = [e for e in condensed.events if isinstance(e, ModelEvent)]
    assert not model_events[0].input_delta
    assert model_events[1].input_delta

    # Resolve should restore originals
    resolved = resolve_sample_attachments(condensed)
    resolved_model_events = [e for e in resolved.events if isinstance(e, ModelEvent)]
    assert not resolved_model_events[0].input_delta
    assert not resolved_model_events[1].input_delta
    assert len(resolved_model_events[0].input) == 1
    assert len(resolved_model_events[1].input) == 3


def test_resolve_input_deltas_no_delta() -> None:
    """Resolving events with no deltas is a no-op."""
    msg1 = ChatMessageUser(content="hello")
    events = [_make_model_event([msg1])]

    resolved = resolve_input_deltas(events)
    assert resolved[0].input == [msg1]
    assert not resolved[0].input_delta
