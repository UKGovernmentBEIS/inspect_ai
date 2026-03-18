from typing import Generator, Type, TypeVar
from unittest.mock import patch

import pytest

import inspect_ai.hooks._startup as hooks_startup_module
from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.environ import environ_var
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import _registry, registry_info, registry_lookup
from inspect_ai.dataset._dataset import Sample
from inspect_ai.hooks._hooks import (
    ApiKeyOverride,
    Hooks,
    ModelUsageData,
    RunEnd,
    RunStart,
    SampleAttemptEnd,
    SampleAttemptStart,
    SampleEnd,
    SampleEvent,
    SampleInit,
    SampleStart,
    TaskEnd,
    TaskStart,
    has_api_key_override,
    hooks,
    override_api_key,
)
from inspect_ai.hooks._startup import init_hooks
from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState


class MockHooks(Hooks):
    def __init__(self) -> None:
        self.should_enable = True
        self.run_start_events: list[RunStart] = []
        self.run_end_events: list[RunEnd] = []
        self.task_start_events: list[TaskStart] = []
        self.task_end_events: list[TaskEnd] = []
        self.sample_init_events: list[SampleInit] = []
        self.sample_start_events: list[SampleStart] = []
        self.sample_attempt_start_events: list[SampleAttemptStart] = []
        self.sample_attempt_end_events: list[SampleAttemptEnd] = []
        self.sample_event_events: list[SampleEvent] = []
        self.sample_end_events: list[SampleEnd] = []
        self.model_usage_events: list[ModelUsageData] = []

    def assert_no_events(self) -> None:
        assert not self.run_start_events
        assert not self.run_end_events
        assert not self.task_start_events
        assert not self.task_end_events
        assert not self.sample_init_events
        assert not self.sample_start_events
        assert not self.sample_attempt_start_events
        assert not self.sample_attempt_end_events
        assert not self.sample_event_events
        assert not self.sample_end_events
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

    async def on_sample_init(self, data: SampleInit) -> None:
        self.sample_init_events.append(data)

    async def on_sample_start(self, data: SampleStart) -> None:
        self.sample_start_events.append(data)

    async def on_sample_attempt_start(self, data: SampleAttemptStart) -> None:
        self.sample_attempt_start_events.append(data)

    async def on_sample_attempt_end(self, data: SampleAttemptEnd) -> None:
        self.sample_attempt_end_events.append(data)

    async def on_sample_event(self, data: SampleEvent) -> None:
        self.sample_event_events.append(data)

    async def on_sample_end(self, data: SampleEnd) -> None:
        self.sample_end_events.append(data)

    async def on_model_usage(self, data: ModelUsageData) -> None:
        self.model_usage_events.append(data)

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        return f"mocked-{data.env_var_name}-{data.value}"


class MockMinimalHooks(Hooks):
    def __init__(self) -> None:
        self.run_start_events: list[RunStart] = []

    async def on_run_start(self, data: RunStart) -> None:
        self.run_start_events.append(data)


@pytest.fixture(autouse=True)
def reset_hooks() -> None:
    # Reset the _registry_hooks_loaded flag before each test, which ensures that
    # _load_registry_hooks() is called for each test (required for tests which verify
    # INSPECT_REQUIRED_HOOKS).
    hooks_startup_module._registry_hooks_loaded = False


@pytest.fixture
def mock_hooks() -> Generator[MockHooks, None, None]:
    yield from _create_mock_hooks("test_hooks", MockHooks)


@pytest.fixture
def hooks_2() -> Generator[MockHooks, None, None]:
    yield from _create_mock_hooks("test_hooks_2", MockHooks)


@pytest.fixture
def hooks_minimal() -> Generator[MockMinimalHooks, None, None]:
    yield from _create_mock_hooks("test_hooks_minimal", MockMinimalHooks)


def test_can_run_eval_with_no_hooks() -> None:
    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")


def test_respects_enabled(mock_hooks: MockHooks) -> None:
    mock_hooks.assert_no_events()

    mock_hooks.should_enable = False
    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    mock_hooks.assert_no_events()

    mock_hooks.should_enable = True
    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert len(mock_hooks.run_start_events) == 1


def test_can_subscribe_to_events(mock_hooks: MockHooks) -> None:
    mock_hooks.assert_no_events()

    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert len(mock_hooks.run_start_events) == 1
    assert mock_hooks.run_start_events[0].run_id is not None
    assert len(mock_hooks.run_end_events) == 1
    assert len(mock_hooks.task_start_events) == 1
    assert len(mock_hooks.task_end_events) == 1
    assert len(mock_hooks.sample_init_events) == 1
    assert len(mock_hooks.sample_start_events) == 1
    assert len(mock_hooks.sample_attempt_start_events) == 1
    assert len(mock_hooks.sample_attempt_end_events) == 1
    assert len(mock_hooks.sample_end_events) == 1
    assert len(mock_hooks.model_usage_events) == 1


def test_can_subscribe_to_events_with_multiple_hooks(
    mock_hooks: MockHooks, hooks_2: MockHooks
) -> None:
    mock_hooks.assert_no_events()
    hooks_2.assert_no_events()

    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    for h in (mock_hooks, hooks_2):
        assert len(h.run_start_events) == 1
        assert h.run_start_events[0].run_id is not None
        assert len(h.run_end_events) == 1
        assert len(h.task_start_events) == 1
        assert len(h.task_end_events) == 1
        assert len(h.sample_init_events) == 1
        assert len(h.sample_start_events) == 1
        assert len(h.sample_attempt_start_events) == 1
        assert len(h.sample_attempt_end_events) == 1
        assert len(h.sample_end_events) == 1
        assert len(h.model_usage_events) == 1


def test_hooks_on_multiple_tasks(mock_hooks: MockHooks) -> None:
    eval(
        [
            Task(dataset=[Sample("task_1_sample_1")]),
            Task(dataset=[Sample("task_2_sample_1")]),
        ],
        model="mockllm/model",
    )

    assert len(mock_hooks.run_start_events) == 1
    assert len(mock_hooks.run_end_events) == 1
    assert len(mock_hooks.task_start_events) == 2
    assert len(mock_hooks.task_end_events) == 2
    assert len(mock_hooks.sample_init_events) == 2
    assert len(mock_hooks.sample_start_events) == 2
    assert len(mock_hooks.sample_attempt_start_events) == 2
    assert len(mock_hooks.sample_attempt_end_events) == 2
    assert len(mock_hooks.sample_end_events) == 2


def test_hooks_with_multiple_samples(mock_hooks: MockHooks) -> None:
    eval(
        [
            Task(dataset=[Sample("sample_1"), Sample("sample_2")]),
        ],
        model="mockllm/model",
    )

    assert len(mock_hooks.run_start_events) == 1
    assert len(mock_hooks.run_end_events) == 1
    assert len(mock_hooks.task_start_events) == 1
    assert len(mock_hooks.task_end_events) == 1
    assert len(mock_hooks.sample_init_events) == 2
    assert len(mock_hooks.sample_start_events) == 2
    assert len(mock_hooks.sample_attempt_start_events) == 2
    assert len(mock_hooks.sample_attempt_end_events) == 2
    assert len(mock_hooks.sample_end_events) == 2


def test_hooks_with_multiple_epochs(mock_hooks: MockHooks) -> None:
    eval(
        Task(dataset=[Sample("sample_1")]),
        model="mockllm/model",
        epochs=3,
    )

    assert len(mock_hooks.sample_init_events) == 3
    assert len(mock_hooks.sample_start_events) == 3
    assert len(mock_hooks.sample_attempt_start_events) == 3
    assert len(mock_hooks.sample_attempt_end_events) == 3
    assert len(mock_hooks.sample_end_events) == 3


def test_hooks_with_sample_retries(mock_hooks: MockHooks) -> None:
    eval(
        Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(2)),
        model="mockllm/model",
        retry_on_error=10,
    )

    # _fail_n_times_solver(2) fails once, succeeds on 2nd attempt.
    # Sample-level hooks fire once regardless of retries.
    assert len(mock_hooks.sample_init_events) == 1
    assert len(mock_hooks.sample_start_events) == 1
    assert len(mock_hooks.sample_end_events) == 1

    # Attempt-level hooks fire once per attempt.
    assert len(mock_hooks.sample_attempt_start_events) == 2
    assert len(mock_hooks.sample_attempt_end_events) == 2

    # UUID should be consistent across all hooks
    init_id = mock_hooks.sample_init_events[0].sample_id
    assert mock_hooks.sample_start_events[0].sample_id == init_id
    assert mock_hooks.sample_end_events[0].sample_id == init_id
    for start_evt in mock_hooks.sample_attempt_start_events:
        assert start_evt.sample_id == init_id
    for end_evt in mock_hooks.sample_attempt_end_events:
        assert end_evt.sample_id == init_id


def test_hooks_sample_uuid_stable_across_multiple_retries(
    mock_hooks: MockHooks,
) -> None:
    eval(
        Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(5)),
        model="mockllm/model",
        retry_on_error=10,
    )

    assert len(mock_hooks.sample_init_events) == 1
    assert len(mock_hooks.sample_end_events) == 1

    # _fail_n_times_solver(5) fails 4 times, succeeds on 5th → 5 attempts
    assert len(mock_hooks.sample_attempt_start_events) == 5
    assert len(mock_hooks.sample_attempt_end_events) == 5

    init_id = mock_hooks.sample_init_events[0].sample_id
    assert mock_hooks.sample_start_events[0].sample_id == init_id
    assert mock_hooks.sample_end_events[0].sample_id == init_id
    # All mid-sample events also carry the same UUID
    for sample_evt in mock_hooks.sample_event_events:
        assert sample_evt.sample_id == init_id
    for start_evt in mock_hooks.sample_attempt_start_events:
        assert start_evt.sample_id == init_id
    for end_evt in mock_hooks.sample_attempt_end_events:
        assert end_evt.sample_id == init_id


def test_hooks_sample_uuid_stable_on_retry_then_fail(
    mock_hooks: MockHooks,
) -> None:
    eval(
        Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(10)),
        model="mockllm/model",
        retry_on_error=3,
    )

    assert len(mock_hooks.sample_init_events) == 1
    assert len(mock_hooks.sample_end_events) == 1

    # _fail_n_times_solver(10) with retry_on_error=3 → 4 attempts, all fail
    assert len(mock_hooks.sample_attempt_start_events) == 4
    assert len(mock_hooks.sample_attempt_end_events) == 4

    init_id = mock_hooks.sample_init_events[0].sample_id
    assert mock_hooks.sample_start_events[0].sample_id == init_id
    assert mock_hooks.sample_end_events[0].sample_id == init_id
    for start_evt in mock_hooks.sample_attempt_start_events:
        assert start_evt.sample_id == init_id
    for end_evt in mock_hooks.sample_attempt_end_events:
        assert end_evt.sample_id == init_id


def test_hooks_sample_uuid_stable_multiple_samples_with_retries(
    mock_hooks: MockHooks,
) -> None:
    eval(
        Task(
            dataset=[Sample("s1"), Sample("s2")],
            solver=_fail_n_times_solver(2),
        ),
        model="mockllm/model",
        retry_on_error=5,
    )

    assert len(mock_hooks.sample_init_events) == 2
    assert len(mock_hooks.sample_end_events) == 2
    # The two samples have different UUIDs
    init_ids = {evt.sample_id for evt in mock_hooks.sample_init_events}
    assert len(init_ids) == 2
    # Each init UUID appears in the end events
    end_ids = {evt.sample_id for evt in mock_hooks.sample_end_events}
    assert init_ids == end_ids

    # Attempt hooks are properly paired
    starts = [(e.sample_id, e.attempt) for e in mock_hooks.sample_attempt_start_events]
    ends = [(e.sample_id, e.attempt) for e in mock_hooks.sample_attempt_end_events]
    assert starts == ends


def test_attempt_hooks_with_retries_then_success(mock_hooks: MockHooks) -> None:
    eval(
        Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(3)),
        model="mockllm/model",
        retry_on_error=10,
    )

    # _fail_n_times_solver(3) fails twice, succeeds on 3rd call → 3 attempts
    assert len(mock_hooks.sample_attempt_start_events) == 3
    assert len(mock_hooks.sample_attempt_end_events) == 3

    # attempt numbers are sequential and 1-based
    for i, start_evt in enumerate(mock_hooks.sample_attempt_start_events):
        assert start_evt.attempt == i + 1
    for i, end_evt in enumerate(mock_hooks.sample_attempt_end_events):
        assert end_evt.attempt == i + 1

    # first two attempts failed and will be retried
    for end_evt in mock_hooks.sample_attempt_end_events[:2]:
        assert end_evt.error is not None
        assert end_evt.will_retry is True

    # last attempt succeeded
    last = mock_hooks.sample_attempt_end_events[2]
    assert last.error is None
    assert last.will_retry is False


def test_attempt_hooks_retries_exhausted(mock_hooks: MockHooks) -> None:
    eval(
        Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(100)),
        model="mockllm/model",
        retry_on_error=2,
    )

    # 3 total attempts: original + 2 retries, all fail
    assert len(mock_hooks.sample_attempt_start_events) == 3
    assert len(mock_hooks.sample_attempt_end_events) == 3

    # first two: error with will_retry=True
    for evt in mock_hooks.sample_attempt_end_events[:2]:
        assert evt.error is not None
        assert evt.will_retry is True

    # last: error with will_retry=False (retries exhausted)
    last = mock_hooks.sample_attempt_end_events[2]
    assert last.error is not None
    assert last.will_retry is False


def test_hooks_with_error_and_no_retries(mock_hooks: MockHooks) -> None:
    eval(
        Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(10)),
        model="mockllm/model",
        retry_on_error=0,
    )

    # Will fail on first attempt without any retries.
    assert len(mock_hooks.sample_init_events) == 1
    assert len(mock_hooks.sample_start_events) == 1
    assert len(mock_hooks.sample_attempt_start_events) == 1
    assert len(mock_hooks.sample_attempt_end_events) == 1
    assert len(mock_hooks.sample_end_events) == 1

    end = mock_hooks.sample_attempt_end_events[0]
    assert end.attempt == 1
    assert end.error is not None
    assert end.will_retry is False


def test_hooks_with_error_passes_exception_to_run_end(mock_hooks: MockHooks) -> None:
    with pytest.raises(RuntimeError, match="test"):
        with patch("inspect_ai._eval.eval.eval_init", side_effect=RuntimeError("test")):
            eval(
                Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(1)),
                model="mockllm/model",
                retry_on_error=0,
            )

    assert len(mock_hooks.run_end_events) == 1
    assert mock_hooks.run_end_events[0].exception is not None


def test_hooks_with_base_exception_passes_exception_to_run_end(
    mock_hooks: MockHooks,
) -> None:
    with pytest.raises(KeyboardInterrupt):
        with patch("inspect_ai._eval.eval.eval_init", side_effect=KeyboardInterrupt()):
            eval(
                Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(1)),
                model="mockllm/model",
                retry_on_error=0,
            )

    assert len(mock_hooks.run_end_events) == 1
    assert mock_hooks.run_end_events[0].exception is not None


def test_hooks_do_not_need_to_subscribe_to_all_events(
    hooks_minimal: MockMinimalHooks,
) -> None:
    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert len(hooks_minimal.run_start_events) == 1


def test_has_api_key_override_true(mock_hooks: MockHooks) -> None:
    res = has_api_key_override()
    assert res is True


def test_has_api_key_override_false(hooks_minimal: MockMinimalHooks) -> None:
    res = has_api_key_override()
    assert res is False


def test_has_api_key_override_no_hooks() -> None:
    res = has_api_key_override()
    assert res is False


def test_has_api_key_override_multiple_hooks(
    mock_hooks: MockHooks, hooks_minimal: MockMinimalHooks
) -> None:
    res = has_api_key_override()
    assert res is True


def test_api_key_override(mock_hooks: MockHooks) -> None:
    overridden = override_api_key("TEST_VAR", "test_value")

    assert overridden == "mocked-TEST_VAR-test_value"


def test_api_key_override_falls_back_to_legacy(mock_hooks: MockHooks) -> None:
    def legacy_hook_override(var: str, value: str) -> str | None:
        return f"legacy-{var}-{value}"

    mock_hooks.should_enable = False

    with environ_var("INSPECT_API_KEY_OVERRIDE", "._legacy_hook_override"):
        with patch(
            "inspect_ai.hooks._hooks.override_api_key_legacy", legacy_hook_override
        ):
            overridden = override_api_key("TEST_VAR", "test_value")

    assert overridden == "legacy-TEST_VAR-test_value"


def test_init_hooks_can_be_called_multiple_times(mock_hooks: MockHooks) -> None:
    # Ensure that init_hooks can be called multiple times without issues.
    init_hooks()
    init_hooks()

    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert len(mock_hooks.run_start_events) == 1


def test_hooks_name_and_description(mock_hooks: MockHooks) -> None:
    info = registry_info(mock_hooks)

    assert info.name == "test_hooks"
    assert info.metadata["description"] == "test_hooks-description"


def test_hooks_decorator_returns_class() -> None:
    @hooks(name="test_hooks_class", description="test")
    class TestHooksClass(Hooks):
        pass

    assert isinstance(TestHooksClass, type)
    instance = TestHooksClass()
    assert isinstance(instance, Hooks)


def test_required_hooks_when_all_installed(
    monkeypatch: pytest.MonkeyPatch, mock_hooks: MockHooks, hooks_2: MockHooks
) -> None:
    with environ_var("INSPECT_REQUIRED_HOOKS", "test_hooks"):
        init_hooks()


def test_required_hooks_when_one_missing(
    monkeypatch: pytest.MonkeyPatch, mock_hooks: MockHooks
) -> None:
    with environ_var("INSPECT_REQUIRED_HOOKS", "test_hooks,fake"):
        with pytest.raises(PrerequisiteError) as exc_info:
            init_hooks()

    assert "missing: {'fake'}" in str(exc_info.value)


def test_sample_events_are_emitted(mock_hooks: MockHooks) -> None:
    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    # A basic eval should produce at least one sample event (e.g. SampleInitEvent,
    # ModelEvent, ScoreEvent, etc.)
    assert len(mock_hooks.sample_event_events) > 0

    # All events should reference the same sample/run/eval ids
    first = mock_hooks.sample_event_events[0]
    for evt in mock_hooks.sample_event_events:
        assert evt.run_id == first.run_id
        assert evt.eval_id == first.eval_id
        assert evt.sample_id == first.sample_id


def test_sample_events_with_multiple_samples(mock_hooks: MockHooks) -> None:
    eval(
        Task(dataset=[Sample("sample_1"), Sample("sample_2")]),
        model="mockllm/model",
    )

    # Events should be emitted for both samples
    sample_ids = {evt.sample_id for evt in mock_hooks.sample_event_events}
    assert len(sample_ids) == 2


def test_sample_events_with_multiple_hooks(
    mock_hooks: MockHooks, hooks_2: MockHooks
) -> None:
    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    # Both hooks should receive the same sample events
    assert len(mock_hooks.sample_event_events) > 0
    assert len(mock_hooks.sample_event_events) == len(hooks_2.sample_event_events)


def test_sample_events_arrive_before_sample_end(mock_hooks: MockHooks) -> None:
    """Verify that all sample events are drained before sample_end fires."""
    eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert len(mock_hooks.sample_event_events) > 0
    assert len(mock_hooks.sample_end_events) == 1

    # The sample_end event should share the same sample_id as the sample events
    end_sample_id = mock_hooks.sample_end_events[0].sample_id
    for evt in mock_hooks.sample_event_events:
        assert evt.sample_id == end_sample_id


def test_no_attempt_end_without_attempt_start(mock_hooks: MockHooks) -> None:
    """Verify that attempt_end is NOT emitted when a failure occurs before attempt_start."""
    with patch(
        "inspect_ai.hooks._hooks.emit_sample_start",
        side_effect=RuntimeError("simulated pre-attempt failure"),
    ):
        eval(
            Task(dataset=[Sample("sample_1")]),
            model="mockllm/model",
        )

    # sample_init should still have been emitted (it happens before the patched call)
    assert len(mock_hooks.sample_init_events) == 1

    # attempt_start should NOT have been emitted (failure happened before it)
    assert len(mock_hooks.sample_attempt_start_events) == 0

    # attempt_end must NOT be emitted without a matching attempt_start
    assert len(mock_hooks.sample_attempt_end_events) == 0


T = TypeVar("T", bound=Hooks)


def _create_mock_hooks(name: str, hooks_class: Type[T]) -> Generator[T, None, None]:
    @hooks(name, description=f"{name}-description")
    def get_hooks_class() -> type[T]:
        return hooks_class

    hook = registry_lookup("hooks", name)
    assert isinstance(hook, hooks_class)
    try:
        yield hook
    finally:
        # Remove the hook from the registry to avoid conflicts in other tests.
        del _registry[f"hooks:{name}"]


@solver
def _fail_n_times_solver(target_failures: int) -> Solver:
    """Fails N times, then succeeds."""
    attempts = 0

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        nonlocal attempts
        attempts += 1
        if attempts < target_failures:
            raise RuntimeError(f"Simulated failure {attempts}")
        return state

    return solve
