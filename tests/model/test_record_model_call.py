from unittest.mock import patch

from inspect_ai import Task, eval
from inspect_ai._util.registry import _registry
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._samples import (
    set_active_model_event_call,
    track_active_model_event,
)
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import ChatMessage, GenerateConfig, ModelAPI, ModelOutput
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._registry import modelapi
from inspect_ai.scorer import match
from inspect_ai.tool import ToolChoice, ToolInfo


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

    call = ModelCall.create(request={"model": "test"}, response=None)

    with patch.object(transcript, "_event_updated") as mock_updated:
        with track_active_model_event(event):
            set_active_model_event_call(call)

        mock_updated.assert_called_once_with(event)

    assert event.call is call


def test_record_model_call_populates_event_call():
    """A provider calling record_model_call() populates ModelEvent.call in transcript."""

    class RecordingModelAPI(ModelAPI):
        async def generate(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> tuple[ModelOutput, ModelCall]:
            call = ModelCall.create(
                request={"messages": [m.model_dump() for m in input]},
                response=None,
            )
            self.record_model_call(call)

            call.response = {"content": "test response"}
            return ModelOutput.from_content(self.model_name, "test"), call

    @modelapi(name="recording_test")
    def recording_test() -> type[ModelAPI]:
        return RecordingModelAPI

    try:
        task = Task(dataset=[Sample(input="Hello", target="test")], scorer=match())
        log = eval(task, model="recording_test/model")[0]

        assert log.samples is not None
        sample = log.samples[0]
        model_events = [e for e in sample.transcript.events if e.event == "model"]

        assert len(model_events) > 0
        assert model_events[0].call is not None
        assert "messages" in model_events[0].call.request
    finally:
        del _registry["modelapi:recording_test"]
