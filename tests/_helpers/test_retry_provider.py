"""Tests for retry-test provider helpers."""

# pyright: reportImplicitRelativeImport=false

import pytest
from tenacity import wait_fixed

from _helpers.retry_provider import (
    RaisingThenSucceedingAPI,
    RetryableModelError,
    install_retry_classifier,
    make_mockllm_with_callable,
)
from inspect_ai.model import GenerateConfig
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model_output import ModelOutput


async def test_raising_then_succeeding_api() -> None:
    api = RaisingThenSucceedingAPI(failures=2)
    for _ in range(2):
        with pytest.raises(RetryableModelError):
            await api.generate(
                [ChatMessageUser(content="x")], [], "auto", GenerateConfig()
            )
    out = await api.generate(
        [ChatMessageUser(content="x")], [], "auto", GenerateConfig()
    )
    assert (out[0].completion if isinstance(out, tuple) else out.completion) == "ok"


async def test_retry_wait_returns_zero() -> None:
    api = RaisingThenSucceedingAPI(failures=0)
    assert isinstance(api.retry_wait(), type(wait_fixed(0)))


async def test_install_retry_classifier_classifies_retryable_error() -> None:
    model = make_mockllm_with_callable(
        lambda *args, **kwargs: ModelOutput.from_content("mockllm", "ok")
    )
    install_retry_classifier(model)
    assert model.api.should_retry(RetryableModelError("x")) is True
    assert model.api.should_retry(ValueError("x")) is False


async def test_make_mockllm_with_callable_invokes_callable_per_generate() -> None:
    calls: list[object] = []

    def custom_outputs(input, tools, tool_choice, config):
        calls.append(input)
        return ModelOutput.from_content("mockllm", f"call-{len(calls)}")

    model = make_mockllm_with_callable(custom_outputs)
    assert (await model.generate("a")).completion == "call-1"
    assert (await model.generate("b")).completion == "call-2"
