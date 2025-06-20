import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.dataset._dataset import Sample
from inspect_ai.util._lifecycle import (
    EvalEndEvent,
    EvalStartEvent,
    LifecycleHook,
    ModelUsageEvent,
    SampleScoredEvent,
    SampleStartedEvent,
    lifecycle_hook,
)


class TestLifecycleHook(LifecycleHook):
    def __init__(self) -> None:
        global hook_instance
        hook_instance = self
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

    async def on_eval_start(self, event: EvalStartEvent) -> None:
        self.eval_start_events.append(event)

    async def on_eval_end(self, event: EvalEndEvent) -> None:
        self.eval_end_events.append(event)

    async def on_sample_started(self, event: SampleStartedEvent) -> None:
        self.sample_started_events.append(event)

    async def on_sample_scored(self, event: SampleScoredEvent) -> None:
        self.sample_scored_events.append(event)

    async def on_model_usage(self, event: ModelUsageEvent) -> None:
        self.model_usage_events.append(event)


@pytest.fixture
def hook() -> TestLifecycleHook:
    global hook_instance

    @lifecycle_hook("test_hook_1")
    def get_hook_class() -> type[TestLifecycleHook]:
        return TestLifecycleHook

    return hook_instance


@pytest.fixture
def hook_2() -> TestLifecycleHook:
    global hook_instance

    @lifecycle_hook("test_hook_2")
    def get_hook_class() -> type[TestLifecycleHook]:
        return TestLifecycleHook

    return hook_instance


def test_can_run_eval_with_no_hooks() -> None:
    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))


def test_can_subscribe_to_events(hook: TestLifecycleHook) -> None:
    hook.assert_no_events()

    eval(Task(dataset=[Sample("hello"), Sample("bye")], model="mockllm/model"))

    assert len(hook.eval_start_events) == 1
    assert len(hook.eval_end_events) == 1
    assert hook.eval_start_events[0].run_id is not None
    assert len(hook.sample_started_events) == 2
    assert len(hook.sample_scored_events) == 2
    assert len(hook.model_usage_events) == 0


def test_can_subscribe_to_events_with_multiple_hooks(
    hook: TestLifecycleHook, hook_2: TestLifecycleHook
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


hook_instance: TestLifecycleHook

# TODO: Check that not all hooks need to be subscribed to.
