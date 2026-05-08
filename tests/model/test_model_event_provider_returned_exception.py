"""Provider returning an Exception object: RuntimeError wrap, no retry."""

# pyright: reportImplicitRelativeImport=false

import pytest
from _helpers.event_assertions import model_events
from _helpers.retry_provider import RetryableModelError, install_retry_classifier
from tenacity import wait_fixed
from tenacity.wait import WaitBaseT

from inspect_ai._util.registry import REGISTRY_INFO, RegistryInfo
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model import ModelAPI
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool import ToolChoice, ToolInfo


class _ReturningExceptionAPI(ModelAPI):
    def __init__(self, *, attempts_to_return_exception: int) -> None:
        super().__init__(
            model_name="fake",
            base_url=None,
            api_key=None,
            api_key_vars=[],
            config=GenerateConfig(),
        )
        setattr(
            self,
            REGISTRY_INFO,
            RegistryInfo(type="modelapi", name="inspect_ai/mockllm"),
        )
        self._remaining = attempts_to_return_exception

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        if self._remaining > 0:
            self._remaining -= 1
            call = ModelCall.create(
                {"input": [message.model_dump() for message in input]}, None
            )
            return RetryableModelError("transient"), call
        return ModelOutput.from_content("fake", "ok")

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, RetryableModelError)

    def retry_wait(self) -> WaitBaseT:
        return wait_fixed(0)


async def test_returned_exception_raises_runtime_error_no_retry() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    model = get_model("mockllm/test", memoize=False)
    model.api = _ReturningExceptionAPI(attempts_to_return_exception=1)
    install_retry_classifier(model)

    with pytest.raises(RuntimeError) as exc_info:
        await model.generate("hello", config=GenerateConfig(max_retries=5))

    assert "RetryableModelError" in str(exc_info.value)
    events = model_events(transcript)
    assert len(events) == 1
    event = events[0]
    assert event.error is not None
    assert event.completed is not None
    assert event.working_time is not None
    assert event.call_started_at is not None
    assert event.call_completed_at is not None
