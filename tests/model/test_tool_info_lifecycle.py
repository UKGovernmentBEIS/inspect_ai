from collections.abc import Generator
from contextlib import contextmanager
from typing import TypeVar

import pytest
from tenacity.wait import wait_none
from test_helpers.tools import addition

from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.event import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.hooks import BeforeModelGenerate, Hooks, hooks
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._cache import CachePolicy, cache_clear
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util._limit import LimitExceededError

T = TypeVar("T", bound=Hooks)


@contextmanager
def _register_hook(name: str, hook_class: type[T]) -> Generator[T, None, None]:
    @hooks(name, description=f"{name}-description")
    def get_hook_class() -> type[T]:
        return hook_class

    hook = registry_lookup("hooks", name)
    assert isinstance(hook, hook_class)
    try:
        yield hook
    finally:
        del _registry[f"hooks:{name}"]


def _model_events(current: Transcript) -> list[ModelEvent]:
    return [event for event in current._events if isinstance(event, ModelEvent)]


@contextmanager
def _without_registered_hooks() -> Generator[None, None, None]:
    hooks = {key: value for key, value in _registry.items() if key.startswith("hooks:")}
    for key in hooks:
        del _registry[key]
    try:
        yield
    finally:
        for key in list(_registry.keys()):
            if key.startswith("hooks:"):
                del _registry[key]
        _registry.update(hooks)


@pytest.mark.anyio
async def test_no_hook_model_event_tools_share_raw_tool_parameters() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    model = get_model("mockllm/model", memoize=False)
    tool = addition()

    with _without_registered_hooks():
        await model.generate("hello", tools=[tool])
        await model.generate("hello", tools=[tool])

    events = _model_events(current)
    assert len(events) == 2
    assert events[0].tools[0].parameters is events[1].tools[0].parameters
    assert (
        events[0].tools[0].parameters.properties["x"]
        is events[1].tools[0].parameters.properties["x"]
    )


class ObservingHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        assert data.tools[0].description == "Add two numbers."


@pytest.mark.anyio
async def test_observing_hook_model_event_tools_share_raw_tool_parameters() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    model = get_model("mockllm/model", memoize=False)
    tool = addition()

    with _register_hook("tool_lifecycle_observing", ObservingHooks):
        await model.generate("hello", tools=[tool])
        await model.generate("hello", tools=[tool])

    events = _model_events(current)
    assert len(events) == 2
    assert events[0].tools[0].parameters is events[1].tools[0].parameters
    assert (
        events[0].tools[0].parameters.properties["x"]
        is events[1].tools[0].parameters.properties["x"]
    )


@pytest.mark.anyio
async def test_provider_tool_mutation_does_not_change_retained_model_event() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        tools[0].description = "provider mutated"
        tools[0].parameters.properties["x"].description = "provider mutated"
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", memoize=False, custom_outputs=out)
    await model.generate("hello", tools=[addition()])

    event = _model_events(current)[0]
    assert event.tools[0].description == "Add two numbers."
    assert (
        event.tools[0].parameters.properties["x"].description == "First number to add."
    )


class DescriptionOnlyHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        data.tools[0].description = "hook mutated description"


@pytest.mark.anyio
async def test_hook_description_mutation_shares_unchanged_parameters() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    model = get_model("mockllm/model", memoize=False)
    tool = addition()

    with _register_hook("tool_lifecycle_description_only", DescriptionOnlyHooks):
        await model.generate("hello", tools=[tool])
        await model.generate("hello", tools=[tool])

    events = _model_events(current)
    assert len(events) == 2
    assert events[0].tools[0].description == "hook mutated description"
    assert events[1].tools[0].description == "hook mutated description"
    assert events[0].tools[0].parameters is events[1].tools[0].parameters
    assert (
        events[0].tools[0].parameters.properties["x"]
        is events[1].tools[0].parameters.properties["x"]
    )


class OptionsOnlyHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        data.tools[0].options = {"hook": "mutated"}


@pytest.mark.anyio
async def test_hook_options_mutation_shares_unchanged_parameters() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    model = get_model("mockllm/model", memoize=False)
    tool = addition()

    with _register_hook("tool_lifecycle_options_only", OptionsOnlyHooks):
        await model.generate("hello", tools=[tool])
        await model.generate("hello", tools=[tool])

    events = _model_events(current)
    assert len(events) == 2
    assert events[0].tools[0].options == {"hook": "mutated"}
    assert events[1].tools[0].options == {"hook": "mutated"}
    assert events[0].tools[0].parameters is events[1].tools[0].parameters


class ParameterMutatingHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        data.tools[0].parameters.properties["x"].description = "hook mutated x"


@pytest.mark.anyio
async def test_hook_parameter_mutation_retains_changed_schema() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        tools[0].parameters.properties["x"].description = "provider mutated x"
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", memoize=False, custom_outputs=out)
    with _register_hook("tool_lifecycle_parameter_mutating", ParameterMutatingHooks):
        await model.generate("hello", tools=[addition()])

    event = _model_events(current)[0]
    assert event.tools[0].parameters.properties["x"].description == "hook mutated x"


class AddingToolHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        data.tools.append(
            ToolInfo(
                name="hook_added",
                description="Hook added tool.",
            )
        )


@pytest.mark.anyio
async def test_hook_can_add_tool_to_retained_event() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    model = get_model("mockllm/model", memoize=False)
    with _register_hook("tool_lifecycle_adding", AddingToolHooks):
        await model.generate("hello", tools=[addition()])

    event = _model_events(current)[0]
    assert [tool.name for tool in event.tools] == ["addition", "hook_added"]


class MutatingHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        data.tools[0].description = "hook mutated description"


@pytest.mark.anyio
async def test_hook_tool_mutation_is_retained_and_isolated_from_provider() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        tools[0].description = "provider mutated"
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", memoize=False, custom_outputs=out)
    with _register_hook("tool_lifecycle_mutating", MutatingHooks):
        await model.generate("hello", tools=[addition()])

    event = _model_events(current)[0]
    assert event.tools[0].description == "hook mutated description"


class AttemptAnnotatingHooks(Hooks):
    def __init__(self) -> None:
        self.calls = 0

    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        self.calls += 1
        data.tools[0].description += f" attempt {self.calls}"


@pytest.mark.anyio
async def test_before_model_generate_retries_start_from_clean_tool_baseline() -> None:
    seen: list[str] = []

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        seen.append(tools[0].description)
        if len(seen) == 1:
            raise RuntimeError("retry once")
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", memoize=False, custom_outputs=out)
    model.api.should_retry = lambda ex: True  # type: ignore[method-assign]
    model.api.retry_wait = lambda: wait_none()  # type: ignore[method-assign]

    with _register_hook("tool_lifecycle_attempts", AttemptAnnotatingHooks) as hook:
        await model.generate(
            "hello",
            tools=[addition()],
            config=GenerateConfig(max_retries=2),
        )

    assert hook.calls == 2
    assert seen == [
        "Add two numbers. attempt 1",
        "Add two numbers. attempt 2",
    ]


class OrderingHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        transcript().info("before_model_generate", source="hook")


@pytest.mark.anyio
async def test_before_model_generate_events_precede_model_event() -> None:
    current = Transcript(log_model_api=True)
    init_transcript(current)

    model = get_model("mockllm/model", memoize=False)
    with _register_hook("tool_lifecycle_ordering", OrderingHooks):
        await model.generate("hello", tools=[addition()])

    assert isinstance(current._events[0], InfoEvent)
    assert isinstance(current._events[1], ModelEvent)


class RaisingHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        raise LimitExceededError(
            "custom", value=1, limit=0, message="stop before provider"
        )


@pytest.mark.anyio
async def test_before_model_generate_limit_error_creates_no_pending_model_event() -> (
    None
):
    current = Transcript(log_model_api=True)
    init_transcript(current)

    model = get_model("mockllm/model", memoize=False)
    with _register_hook("tool_lifecycle_limit", RaisingHooks):
        with pytest.raises(LimitExceededError, match="stop before provider"):
            await model.generate("hello", tools=[addition()])

    assert _model_events(current) == []


class HookCacheHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        data.tools[0].description = "hook mutated description"


@pytest.mark.anyio
async def test_cache_lookup_uses_post_hook_tool_state() -> None:
    calls = 0

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        nonlocal calls
        calls += 1
        return ModelOutput.from_content(model="mockllm", content="ok")

    cache_clear("mockllm/model")
    model = get_model("mockllm/model", memoize=False, custom_outputs=out)

    try:
        with _register_hook("tool_lifecycle_cache_state", HookCacheHooks):
            await model.generate("hello", tools=[addition()], cache=True)
            await model.generate("hello", tools=[addition()], cache=True)
    finally:
        cache_clear("mockllm/model")

    assert calls == 1


@pytest.mark.anyio
async def test_cache_key_is_frozen_when_provider_mutates_input() -> None:
    calls = 0

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        nonlocal calls
        calls += 1
        input[0].content = "provider mutated input"
        return ModelOutput.from_content(model="mockllm", content="ok")

    cache_clear("mockllm/model")
    model = get_model("mockllm/model", memoize=False, custom_outputs=out)

    try:
        await model.generate("hello", cache=True)
        await model.generate("hello", cache=True)
    finally:
        cache_clear("mockllm/model")

    assert calls == 1


@pytest.mark.anyio
async def test_cache_policy_store_uses_explicit_cache_policy() -> None:
    calls = 0

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        nonlocal calls
        calls += 1
        return ModelOutput.from_content(model="mockllm", content="ok")

    cache_clear("mockllm/model")
    model = get_model("mockllm/model", memoize=False, custom_outputs=out)
    config = GenerateConfig(cache=CachePolicy(expiry=None))
    input: list[ChatMessage] = [ChatMessageUser(content="hello")]

    try:
        await model._generate(input, [], None, config)
        await model._generate(input, [], None, config)
    finally:
        cache_clear("mockllm/model")

    assert calls == 1
