"""Distinguish outer Tenacity retries from provider-internal retry signals."""

# pyright: reportImplicitRelativeImport=false

from collections.abc import Generator

from _helpers.event_assertions import model_events
from _helpers.retry_provider import (
    RetryableModelError,
    install_retry_classifier,
    make_mockllm_with_callable,
)

from inspect_ai._util.registry import _registry
from inspect_ai.hooks._hooks import Hooks, ModelUsageData, hooks
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig
from inspect_ai.model._model_output import ModelOutput, ModelUsage


class _UsageHooks(Hooks):
    def __init__(self) -> None:
        self.model_usage_events: list[ModelUsageData] = []

    async def on_model_usage(self, data: ModelUsageData) -> None:
        self.model_usage_events.append(data)


def _registered_usage_hooks() -> Generator[_UsageHooks, None, None]:
    name = "test_retry_classification_usage"

    @hooks(name, description="capture usage retry counters")
    def usage_hooks() -> type[_UsageHooks]:
        return _UsageHooks

    hook = _registry[f"hooks:{name}"]
    assert isinstance(hook, _UsageHooks)
    try:
        yield hook
    finally:
        del _registry[f"hooks:{name}"]


async def test_outer_retry_increments_call_and_http_counters() -> None:
    remaining = [2]

    def custom_outputs(input, tools, tool_choice, config):
        if remaining[0] > 0:
            remaining[0] -= 1
            raise RetryableModelError("transient")
        output = ModelOutput.from_content("mockllm", "ok")
        output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return output

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    install_retry_classifier(model)

    await model.generate("hello", config=GenerateConfig(max_retries=5))

    terminal = model_events(transcript)[-1]
    assert terminal.call_retries == 2
    assert terminal.http_retries == 2
    assert terminal.retries == 2


async def test_provider_internal_retry_increments_only_http_counter() -> None:
    def custom_outputs(input, tools, tool_choice, config):
        from inspect_ai._util.retry import report_http_retry

        report_http_retry()
        output = ModelOutput.from_content("mockllm", "ok")
        output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return output

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)

    await model.generate("hello")

    terminal = model_events(transcript)[-1]
    assert terminal.call_retries == 0
    assert terminal.http_retries == 1
    assert terminal.retries == 1


async def test_model_usage_hook_receives_retry_counters() -> None:
    remaining = [1]
    hooks_iter = _registered_usage_hooks()
    usage_hooks = next(hooks_iter)

    def custom_outputs(input, tools, tool_choice, config):
        if remaining[0] > 0:
            remaining[0] -= 1
            raise RetryableModelError("transient")
        output = ModelOutput.from_content("mockllm", "ok")
        output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return output

    try:
        model = make_mockllm_with_callable(custom_outputs)
        install_retry_classifier(model)

        await model.generate("hello", config=GenerateConfig(max_retries=3))

        assert len(usage_hooks.model_usage_events) == 1
        usage = usage_hooks.model_usage_events[0]
        assert usage.call_retries == 1
        assert usage.http_retries == 1
        assert usage.call_working_time is not None
        assert usage.call_working_time >= 0
    finally:
        try:
            next(hooks_iter)
        except StopIteration:
            pass
