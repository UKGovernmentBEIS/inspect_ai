from typing import Generator, Type, TypeVar
from unittest.mock import patch

import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.environ import environ_var
from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.dataset._dataset import Sample
from inspect_ai.hooks._hooks import (
    ApiKeyOverride,
    Hooks,
    ModelUsageData,
    RunEnd,
    RunStart,
    SampleAbort,
    SampleEnd,
    SampleStart,
    TaskEnd,
    TaskStart,
    hooks,
    override_api_key,
)


class MockHook(Hooks):
    def __init__(self) -> None:
        self.should_enable = True
        self.run_start_events: list[RunStart] = []
        self.run_end_events: list[RunEnd] = []
        self.task_start_events: list[TaskStart] = []
        self.task_end_events: list[TaskEnd] = []
        self.sample_start_events: list[SampleStart] = []
        self.sample_end_events: list[SampleEnd] = []
        self.sample_abort_events: list[SampleAbort] = []
        self.model_usage_events: list[ModelUsageData] = []

    def assert_no_events(self) -> None:
        assert not self.run_start_events
        assert not self.run_end_events
        assert not self.task_start_events
        assert not self.task_end_events
        assert not self.sample_start_events
        assert not self.sample_end_events
        assert not self.sample_abort_events
        assert not self.model_usage_events

    def enabled(self) -> bool:
        return self.should_enable

    async def on_run_start(self, data: RunStart) -> None:
        self.run_start_events.append(data)

    async def on_run_end(self, data: RunEnd) -> None:
        self.run_end_events.append(data)

    async def on_task_start(self, data: TaskStart) -> None:
        self.task_start_events.append(data)

    async def on_task_end(self, data: TaskEnd) -> None:
        self.task_end_events.append(data)

    async def on_sample_start(self, data: SampleStart) -> None:
        self.sample_start_events.append(data)

    async def on_sample_end(self, data: SampleEnd) -> None:
        self.sample_end_events.append(data)

    async def on_sample_abort(self, data: SampleAbort) -> None:
        self.sample_abort_events.append(data)

    async def on_model_usage(self, data: ModelUsageData) -> None:
        self.model_usage_events.append(data)

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        return f"mocked-{data.env_var_name}-{data.value}"


class MockMinimalHook(Hooks):
    def __init__(self) -> None:
        self.run_start_events: list[RunStart] = []

    async def on_run_start(self, data: RunStart) -> None:
        self.run_start_events.append(data)


@pytest.fixture
def mock_hook() -> Generator[MockHook, None, None]:
    yield from _create_mock_hook("test_hook", MockHook)


@pytest.fixture
def hook_2() -> Generator[MockHook, None, None]:
    yield from _create_mock_hook("test_hook_2", MockHook)


@pytest.fixture
def hook_minimal() -> Generator[MockMinimalHook, None, None]:
    yield from _create_mock_hook("test_hook_minimal", MockMinimalHook)


def test_can_run_eval_with_no_hooks() -> None:
    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))


def test_respects_enabled(mock_hook: MockHook) -> None:
    mock_hook.assert_no_events()

    mock_hook.should_enable = False
    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    mock_hook.assert_no_events()

    mock_hook.should_enable = True
    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    assert len(mock_hook.run_start_events) == 1


def test_can_subscribe_to_events(mock_hook: MockHook) -> None:
    mock_hook.assert_no_events()

    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    assert len(mock_hook.run_start_events) == 1
    assert mock_hook.run_start_events[0].run_id is not None
    assert len(mock_hook.run_end_events) == 1
    assert len(mock_hook.task_start_events) == 1
    assert len(mock_hook.task_end_events) == 1
    assert len(mock_hook.sample_start_events) == 2
    assert len(mock_hook.sample_end_events) == 2
    assert len(mock_hook.sample_abort_events) == 0
    assert len(mock_hook.model_usage_events) == 0


def test_can_subscribe_to_events_with_multiple_hooks(
    mock_hook: MockHook, hook_2: MockHook
) -> None:
    mock_hook.assert_no_events()
    hook_2.assert_no_events()

    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    for h in (mock_hook, hook_2):
        assert len(h.run_start_events) == 1
        assert h.run_start_events[0].run_id is not None
        assert len(h.run_end_events) == 1
        assert len(h.task_start_events) == 1
        assert len(h.task_end_events) == 1
        assert len(h.sample_start_events) == 2
        assert len(h.sample_end_events) == 2
        assert len(h.sample_abort_events) == 0
        assert len(h.model_usage_events) == 0


def test_hook_does_not_need_to_subscribe_to_all_events(
    hook_minimal: MockMinimalHook,
) -> None:
    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    assert len(hook_minimal.run_start_events) == 1


def test_api_key_override(mock_hook: MockHook) -> None:
    overridden = override_api_key("TEST_VAR", "test_value")

    assert overridden == "mocked-TEST_VAR-test_value"


def test_api_key_override_falls_back_to_legacy(mock_hook: MockHook) -> None:
    mock_hook.should_enable = False

    with environ_var("INSPECT_API_KEY_OVERRIDE", "._legacy_hook_override"):
        with patch(
            "inspect_ai.hooks._hooks.override_api_key_legacy", _legacy_hook_override
        ):
            overridden = override_api_key("TEST_VAR", "test_value")

    assert overridden == "legacy-TEST_VAR-test_value"


def _legacy_hook_override(var: str, value: str) -> str | None:
    return f"legacy-{var}-{value}"


T = TypeVar("T", bound=Hooks)


def _create_mock_hook(name: str, hook_class: Type[T]) -> Generator[T, None, None]:
    @hooks(name)
    def get_hook_class() -> type[T]:
        return hook_class

    hook = registry_lookup("hooks", name)
    assert isinstance(hook, hook_class)
    try:
        yield hook
    finally:
        # Remove the hook from the registry to avoid conflicts in other tests.
        del _registry[f"hooks:{name}"]
