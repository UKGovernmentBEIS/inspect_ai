"""Test helpers for retry-path scenarios."""

from __future__ import annotations

from collections.abc import Callable

import anyio
from tenacity import wait_fixed
from tenacity.wait import WaitBaseT

from inspect_ai._util.registry import REGISTRY_INFO, RegistryInfo
from inspect_ai.model import GenerateConfig, Model, get_model
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model import ModelAPI
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool import ToolChoice, ToolInfo


class RetryableModelError(RuntimeError):
    """Test exception classified as retryable by retry-test helpers."""


class RaisingThenSucceedingAPI(ModelAPI):
    """Async fake provider that raises ``failures`` times then succeeds."""

    def __init__(
        self,
        *,
        failures: int,
        success_content: str = "ok",
        success_output_time: float = 0.001,
        model_name: str = "fake",
    ) -> None:
        super().__init__(
            model_name=model_name,
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
        self._remaining = failures
        self._success_content = success_content
        self._success_output_time = success_output_time

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        if self._remaining > 0:
            self._remaining -= 1
            raise RetryableModelError(f"transient (remaining={self._remaining})")
        out = ModelOutput.from_content(self.model_name, self._success_content)
        out.time = self._success_output_time
        model_call = ModelCall.create(
            request={"input": [message.model_dump() for message in input]},
            response={"content": out.completion},
            time=self._success_output_time,
        )
        return out, model_call

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, RetryableModelError)

    def retry_wait(self) -> WaitBaseT:
        return wait_fixed(0)


class SlowThenSuccessAPI(ModelAPI):
    """First attempt sleeps ``slow_seconds``, then succeeds."""

    def __init__(self, *, slow_seconds: float, model_name: str = "fake") -> None:
        super().__init__(
            model_name=model_name,
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
        self._first = True
        self._slow_seconds = slow_seconds

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        if self._first:
            self._first = False
            await anyio.sleep(self._slow_seconds)
        out = ModelOutput.from_content(self.model_name, "ok")
        out.time = 0.001
        model_call = ModelCall.create(
            request={"input": [message.model_dump() for message in input]},
            response={"content": out.completion},
            time=0.001,
        )
        return out, model_call

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, RetryableModelError)

    def retry_wait(self) -> WaitBaseT:
        return wait_fixed(0)


def install_retry_classifier(model: Model) -> None:
    """Monkeypatch ``model.api.should_retry`` for retry-test exceptions."""
    original = getattr(model.api, "should_retry", None)

    def classifier(ex: Exception) -> bool:
        if isinstance(ex, RetryableModelError):
            return True
        if original is not None:
            return bool(original(ex))
        return False

    model.api.should_retry = classifier  # type: ignore[method-assign]
    model.api.retry_wait = lambda: wait_fixed(0)  # type: ignore[method-assign]


def make_mockllm_with_callable(
    custom_outputs: Callable[..., ModelOutput],
    model_name: str = "mockllm/test",
) -> Model:
    """Construct a non-memoized MockLLM model with the given callable."""
    return get_model(model_name, custom_outputs=custom_outputs, memoize=False)
