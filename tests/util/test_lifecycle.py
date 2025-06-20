import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.registry import registry_lookup
from inspect_ai.dataset._dataset import Sample
from inspect_ai.util._lifecycle import (
    EvalEndEvent,
    EvalStartEvent,
    LifecycleHooks,
    ModelUsageEvent,
    SampleScoredEvent,
    SampleStartedEvent,
    lifecycle_hook,
)


class MockHook(LifecycleHooks):
    def __init__(self) -> None:
        self.eval_start_events: list[EvalStartEvent] = []
        self.eval_end_events: list[EvalEndEvent] = []
        self.sample_started_events: list[SampleStartedEvent] = []
        self.sample_scored_events: list[SampleScoredEvent] = []
        self.model_usage_events: list[ModelUsageEvent] = []

    def assert_no_events(self) -> None:
        assert not self.eval_start_events
        assert not self.eval_end_events
        assert not self.sample_started_events
        assert not self.sample_scored_events
        assert not self.model_usage_events

    async def on_run_start(self, event: EvalStartEvent) -> None:
        self.eval_start_events.append(event)

    async def on_run_end(self, event: EvalEndEvent) -> None:
        self.eval_end_events.append(event)

    async def on_sample_start(self, event: SampleStartedEvent) -> None:
        self.sample_started_events.append(event)

    async def on_sample_score(self, event: SampleScoredEvent) -> None:
        self.sample_scored_events.append(event)

    async def on_model_usage(self, event: ModelUsageEvent) -> None:
        self.model_usage_events.append(event)


class MockMinimalHook(LifecycleHooks):
    def __init__(self) -> None:
        self.eval_start_events: list[EvalStartEvent] = []

    async def on_run_start(self, event: EvalStartEvent) -> None:
        self.eval_start_events.append(event)


@pytest.fixture
def hook() -> MockHook:
    @lifecycle_hook("test_hook_1")
    def get_hook_class() -> type[MockHook]:
        return MockHook

    obj = registry_lookup("lifecycle_hook", "test_hook_1")
    assert isinstance(obj, MockHook)
    return obj


@pytest.fixture
def hook_2() -> MockHook:
    @lifecycle_hook("test_hook_2")
    def get_hook_class() -> type[MockHook]:
        return MockHook

    obj = registry_lookup("lifecycle_hook", "test_hook_2")
    assert isinstance(obj, MockHook)
    return obj


@pytest.fixture
def hook_minimal() -> MockMinimalHook:
    @lifecycle_hook("test_hook_minimal")
    def get_hook_class() -> type[MockMinimalHook]:
        return MockMinimalHook

    obj = registry_lookup("lifecycle_hook", "test_hook_minimal")
    assert isinstance(obj, MockMinimalHook)
    return obj


def test_can_run_eval_with_no_hooks() -> None:
    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))


def test_can_subscribe_to_events(hook: MockHook) -> None:
    hook.assert_no_events()

    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    assert len(hook.eval_start_events) == 1
    assert len(hook.eval_end_events) == 1
    assert hook.eval_start_events[0].run_id is not None
    assert len(hook.sample_started_events) == 2
    assert len(hook.sample_scored_events) == 2
    assert len(hook.model_usage_events) == 0


def test_can_subscribe_to_events_with_multiple_hooks(
    hook: MockHook, hook_2: MockHook
) -> None:
    hook.assert_no_events()
    hook_2.assert_no_events()

    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    for h in (hook, hook_2):
        assert len(h.eval_start_events) == 1
        assert len(h.eval_end_events) == 1
        assert h.eval_start_events[0].run_id is not None
        assert len(h.sample_started_events) == 2
        assert len(h.sample_scored_events) == 2
        assert len(h.model_usage_events) == 0


def test_hook_does_not_need_to_subscribe_to_all_events(
    hook_minimal: MockMinimalHook,
) -> None:
    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    assert len(hook_minimal.eval_start_events) == 1


# TODO: Check that not all hooks need to be subscribed to.
