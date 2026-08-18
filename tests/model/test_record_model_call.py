from unittest.mock import patch

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._samples import (
    set_active_model_event_call,
    track_active_model_event,
)
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, ModelOutput


def test_set_active_model_event_call_notifies_transcript():
    """set_active_model_event_call notifies transcript when call is recorded."""
    transcript = Transcript()
    init_transcript(transcript)

    event = ModelEvent(
        model="test",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test", choices=[]),
    )

    with patch.object(transcript, "_event_updated") as mock_updated:
        with track_active_model_event(event):
            call = set_active_model_event_call(request={"model": "test"})

        mock_updated.assert_called_once_with(event)

    assert event.call is call
