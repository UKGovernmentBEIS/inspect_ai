"""Tests for ``update_active_model_event_output``.

The helper is the streaming seam: providers call it from inside their SDK
stream loop to publish a partial ``ModelOutput`` snapshot onto the pending
``ModelEvent`` and notify transcript subscribers, before the final
``complete()`` overwrites with the settled output. Mirrors the existing
``set_active_model_event_call`` precedent (see ``test_record_model_call.py``).
"""

import pytest

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._samples import (
    track_active_model_event,
    update_active_model_event_output,
)
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, ModelOutput, get_model


def _pending_model_event() -> ModelEvent:
    return ModelEvent(
        model="test",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test", ""),
        pending=True,
    )


def test_partial_output_reaches_subscriber_and_preserves_pending() -> None:
    """Each flush mutates ``event.output`` and fires ``_event_updated``.

    ``pending`` stays ``True`` so the existing ``complete()`` path remains
    the sole place that clears it (the ACP event mapper depends on this).
    """
    t = Transcript()
    init_transcript(t)
    event = _pending_model_event()
    t._event(event)

    received: list[str] = []
    t._subscribe(
        lambda ev: received.append(ev.output.completion)
        if isinstance(ev, ModelEvent)
        else None
    )

    with track_active_model_event(event):
        update_active_model_event_output(ModelOutput.from_content("test", "Hel"))
        update_active_model_event_output(ModelOutput.from_content("test", "Hello, w"))
        update_active_model_event_output(
            ModelOutput.from_content("test", "Hello, world")
        )

    assert received == ["Hel", "Hello, w", "Hello, world"]
    assert event.output.completion == "Hello, world"
    assert event.pending is True
    assert list(t.pending_events) == [event]


def test_noop_outside_active_model_event() -> None:
    t = Transcript()
    init_transcript(t)
    received: list[object] = []
    t._subscribe(received.append)

    update_active_model_event_output(ModelOutput.from_content("test", "x"))

    assert received == []


def test_asserts_when_event_not_pending() -> None:
    """Guard against a provider flushing after ``complete()`` has run."""
    t = Transcript()
    init_transcript(t)
    event = _pending_model_event()
    event.pending = None

    with track_active_model_event(event):
        with pytest.raises(AssertionError, match="non-pending"):
            update_active_model_event_output(ModelOutput.from_content("test", "x"))


def test_complete_overwrites_partial() -> None:
    """The streaming snapshots are provisional.

    The final output replaces them wholesale, so a partial that dropped
    (e.g.) server-tool blocks is fully reconciled on completion.
    """
    t = Transcript()
    init_transcript(t)
    event = _pending_model_event()
    t._event(event)

    with track_active_model_event(event):
        update_active_model_event_output(ModelOutput.from_content("test", "Hel"))
    assert event.output.completion == "Hel"

    final = ModelOutput.from_content("test", "Hello, world")
    event.output = final
    event.pending = None
    t._event_updated(event)

    assert event.output is final
    assert list(t.pending_events) == []


async def test_mockllm_stream_chunks_emits_partials_then_terminal() -> None:
    """End-to-end: mockllm ``stream_chunks=N`` drives N partials then one terminal.

    Exercises the full provider path — ``Model.generate`` creating the
    pending ``ModelEvent``, ``track_active_model_event`` wrapping the API call,
    mockllm publishing growing-prefix partials (``pending=True``), and
    ``complete()`` clearing ``pending`` — without an API call.
    """
    t = Transcript()
    init_transcript(t)

    completion = "Hello, world!"
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", completion)],
        stream_chunks=3,
    )

    records: list[tuple[bool, str]] = []
    t._subscribe(
        lambda ev: records.append((bool(ev.pending), ev.output.completion))
        if isinstance(ev, ModelEvent)
        else None
    )

    await model.generate("hi")

    partials = [completion for pending, completion in records if pending]
    terminal = [completion for pending, completion in records if not pending]

    # the first pending record is the initial empty event recorded by
    # _record_model_interaction; the 3 streamed partials follow it
    streamed = [c for c in partials if c]
    assert len(streamed) == 3, records
    # growing prefixes that build up to the full completion
    assert streamed == ["Hello", "Hello, wor", "Hello, world!"], streamed
    assert all(completion.startswith(c) for c in streamed)

    # exactly one terminal record, carrying the full completion, and it is last
    assert len(terminal) == 1, records
    assert terminal[0] == completion
    assert not records[-1][0], "a pending partial fired after the terminal record"
