from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Type, TypeVar
from unittest.mock import patch

import pytest

import inspect_ai.hooks._hooks as hooks_module
import inspect_ai.hooks._startup as hooks_startup_module
from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.environ import environ_var
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import _registry, registry_info, registry_lookup
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event import TimelineEvent, timeline_build
from inspect_ai.hooks._hooks import (
    ApiKeyOverride,
    BeforeModelGenerate,
    Hooks,
    ModelRetry,
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
    any_hook_needs_full_sample,
    has_api_key_override,
    hooks,
    override_api_key,
)
from inspect_ai.hooks._startup import init_hooks
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import EvalSample
from inspect_ai.log._transcript import transcript
from inspect_ai.model import ModelOutput, get_model
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
        self.model_retry_events: list[ModelRetry] = []
        self.before_model_generate_events: list[BeforeModelGenerate] = []

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
        assert not self.model_retry_events
        assert not self.before_model_generate_events

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

    async def on_model_retry(self, data: ModelRetry) -> None:
        self.model_retry_events.append(data)

    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        self.before_model_generate_events.append(data)

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
    assert len(mock_hooks.before_model_generate_events) == 1
    before_gen = mock_hooks.before_model_generate_events[0]
    assert before_gen.model_name is not None
    assert len(before_gen.input) > 0
    assert before_gen.sample_id is not None
    assert before_gen.task_name is not None


def test_task_start_carries_plan_including_setup_steps(
    mock_hooks: MockHooks,
) -> None:
    task = Task(dataset=[Sample("sample_1")], setup=_setup_marker_solver())

    eval(task, model="mockllm/model")

    assert len(mock_hooks.task_start_events) == 1
    steps = [step.solver for step in mock_hooks.task_start_events[0].plan.steps]
    # resolve_plan unrolls setup onto the front, ahead of the solver
    assert "_setup_marker_solver" in steps[0]
    assert len(steps) > 1


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
        assert len(h.before_model_generate_events) == 1


def test_model_retry_hook(mock_hooks: MockHooks) -> None:
    import anyio

    from inspect_ai.hooks._hooks import emit_model_retry

    anyio.run(emit_model_retry, "mockllm/model", 2, 1.5)

    assert len(mock_hooks.model_retry_events) == 1
    retry = mock_hooks.model_retry_events[0]
    assert retry.model_name == "mockllm/model"
    assert retry.attempt == 2
    assert retry.wait_time == 1.5
    # no active sample in this context, so eval/sample ids are None
    assert retry.sample_id is None
    assert retry.eval_id is None
    # cause not provided, so it defaults to None
    assert retry.exception_type is None
    assert retry.status_code is None


def test_model_retry_hook_carries_cause(mock_hooks: MockHooks) -> None:
    import anyio

    from inspect_ai.hooks._hooks import emit_model_retry

    anyio.run(emit_model_retry, "mockllm/model", 1, 0.5, "RateLimitError", 429)

    assert len(mock_hooks.model_retry_events) == 1
    retry = mock_hooks.model_retry_events[0]
    assert retry.exception_type == "RateLimitError"
    assert retry.status_code == 429


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

    try:
        assert isinstance(TestHooksClass, type)
        instance = TestHooksClass()
        assert isinstance(instance, Hooks)
    finally:
        # Registration is a side effect of the decorator, not under test here;
        # clean it up so it doesn't leak into other tests via get_all_hooks().
        del _registry["hooks:test_hooks_class"]


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


@contextmanager
def _hook_context(name: str, hooks_class: Type[T]) -> Generator[T, None, None]:
    """`_create_mock_hooks` adapted for use as a `with` block in a test body."""
    yield from _create_mock_hooks(name, hooks_class)


@solver
def _emitting_solver(n: int = 4) -> Solver:
    """Emits enough transcript events to exceed a resident_tail of 1."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for i in range(n):
            transcript().info({"i": i})
        return state

    return solve


@solver
def _emitting_solver_with_model_response(n: int = 100) -> Solver:
    """Emits filler events, then a real generate() call.

    With a small resident tail, the filler events are evicted while the
    trailing model-call events stay resident — the shape needed to exercise
    a hook opt-out against a model response that's still in memory.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for i in range(n):
            transcript().info({"i": i})
        return await generate(state)

    return solve


@solver
def _timeline_adding_solver(n: int = 4) -> Solver:
    """Emits enough events to exceed a resident_tail of 1, then adds a timeline.

    The timeline wraps the still-resident transcript events, giving the
    reduced path a `timelines` field whose leaves are real Event objects.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for i in range(n):
            transcript().info({"i": i})
        transcript().add_timeline(
            timeline_build(list(transcript().events), name="test-timeline")
        )
        return state

    return solve


class _RecordingHook(Hooks):
    """Needs the full sample (the default) and records each on_sample_end."""

    def __init__(self) -> None:
        self.samples: list[EvalSample] = []

    async def on_sample_end(self, data: SampleEnd) -> None:
        self.samples.append(data.sample)


class _SummaryOnlyRecordingHook(_RecordingHook):
    """Opted out of full-sample materialization via needs_full_sample()."""

    def needs_full_sample(self) -> bool:
        return False


def _run_evicted_sample_eval(
    monkeypatch: pytest.MonkeyPatch, log_dir: str, solve: Solver | None = None
) -> None:
    """Run a one-sample eval whose transcript is bounded-evicted.

    Asserts the eviction precondition (the sample was NOT logged from
    memory): callers assert full-sample materialization, which holds
    trivially on the resident path, so a silently broken eviction setup
    (e.g. a renamed INSPECT_TRANSCRIPT_BOUNDED) would otherwise make those
    tests pass vacuously.
    """
    import inspect_ai._eval.task.run as run_module

    monkeypatch.setattr(run_module, "DEFAULT_RESIDENT_TAIL", 1)
    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")

    from_memory_calls: list[bool] = []
    original_log_sample = run_module.log_sample

    async def spying_log_sample(*args: Any, **kwargs: Any) -> EvalSample:
        # from_memory is keyword-only, so it is always present in kwargs
        from_memory_calls.append(kwargs["from_memory"])
        return await original_log_sample(*args, **kwargs)

    monkeypatch.setattr(run_module, "log_sample", spying_log_sample)
    eval(
        Task(dataset=[Sample("sample_1")], solver=[solve or _emitting_solver()]),
        model="mockllm/model",
        log_dir=log_dir,
        display="none",
    )
    assert from_memory_calls == [False], (
        "eviction precondition not met: the sample was logged from memory"
    )


def test_opted_out_hook_receives_event_less_sample_when_evicted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_hooks_registry,
) -> None:
    """The opted-out hook's sample carries neither raw events nor attachments.

    A >100-char model response inside the resident tail is the shape that
    catches attachments leaking independently of events: attachments are
    populated by the (still-resident) model event's condensing, not by the
    evicted-vs-resident events list itself, so a scenario with no long
    content can pass `attachments == {}` vacuously.

    `isolated_hooks_registry` keeps the reduction assertion deterministic: an
    installed extension's entry-point hook (whose `needs_full_sample()`
    defaults to `True`) would otherwise force full materialization for
    every hook, this one included.
    """
    import inspect_ai._eval.task.run as run_module

    monkeypatch.setattr(run_module, "DEFAULT_RESIDENT_TAIL", 20)
    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")
    # >100 chars: exceeds the condense threshold, so the response is pooled
    # as an attachment rather than kept inline
    long_response = "x" * 150

    with _hook_context("summary_only_hook", _SummaryOnlyRecordingHook) as hook:
        eval(
            Task(
                dataset=[Sample("sample_1")],
                solver=[_emitting_solver_with_model_response()],
            ),
            model=get_model(
                "mockllm/model",
                custom_outputs=[
                    ModelOutput.from_content("mockllm/model", long_response)
                ],
            ),
            log_dir=str(tmp_path),
            display="none",
        )

    assert len(hook.samples) == 1
    sample = hook.samples[0]
    assert sample.events == [] and sample.attachments == {}
    # the fields a summary-only consumer actually reads remain intact
    assert sample.output.completion == long_response
    assert sample.messages
    assert sample.total_time is not None


def test_opted_out_hook_receives_timeline_less_sample_when_evicted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_hooks_registry,
) -> None:
    """The opted-out hook's sample carries no timelines, but the log keeps them.

    `TimelineEvent.event` holds real Event objects (shared refs, not
    copies), so timelines riding through the reduction would hand the hook
    the full event tree that emptying `events` was meant to withhold — and
    retaining the sample would pin that memory. The written log must be
    unaffected: it draws timelines from the same `EvalSample` before the
    reduction branch, so clearing them any earlier (e.g. in
    `create_eval_sample`) would silently drop them from the log.
    """
    with _hook_context("timeline_summary_only_hook", _SummaryOnlyRecordingHook) as hook:
        _run_evicted_sample_eval(
            monkeypatch, str(tmp_path), solve=_timeline_adding_solver()
        )

    assert len(hook.samples) == 1
    sample = hook.samples[0]
    assert sample.events == []
    assert sample.timelines is None

    log = read_eval_log(str(next(tmp_path.glob("*.eval"))))
    assert log.samples is not None
    logged = log.samples[0]
    assert logged.timelines is not None
    assert logged.timelines[0].name == "test-timeline"
    # the timeline's UUID refs rebind to the logged events on read-back
    logged_event_ids = {event.uuid for event in logged.events}
    timeline_event_ids = {
        item.event.uuid
        for item in logged.timelines[0].root.content
        if isinstance(item, TimelineEvent)
    }
    assert timeline_event_ids and timeline_event_ids <= logged_event_ids


def test_default_hook_still_receives_full_sample_when_evicted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _hook_context("full_sample_hook", _RecordingHook) as hook:
        _run_evicted_sample_eval(monkeypatch, str(tmp_path))

    assert len(hook.samples) == 1
    assert len(hook.samples[0].events) > 0


def test_mixed_hooks_both_receive_full_sample_when_one_needs_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One opted-out + one default hook: needs_full_sample() is a floor, not per-hook.

    `materialize_full_sample` is computed once for the sample from all enabled hooks
    combined (`any_hook_needs_full_sample()`), and every
    hook is dispatched the same `SampleEnd.sample` object. So a single
    full-sample hook forces materialization for everyone on the sample,
    including hooks that opted out.
    """
    with (
        _hook_context(
            "mixed_summary_only_hook", _SummaryOnlyRecordingHook
        ) as summary_hook,
        _hook_context("mixed_full_sample_hook", _RecordingHook) as full_hook,
    ):
        _run_evicted_sample_eval(monkeypatch, str(tmp_path))

    assert len(summary_hook.samples) == 1
    assert len(full_hook.samples) == 1
    assert len(summary_hook.samples[0].events) > 0
    assert summary_hook.samples[0] is full_hook.samples[0]


def test_any_hook_needs_full_sample_predicate(isolated_hooks_registry) -> None:
    """Only hooks that are enabled and haven't opted out count."""

    class OptedOutHook(Hooks):
        def needs_full_sample(self) -> bool:
            return False

    class DisabledHook(Hooks):
        def enabled(self) -> bool:
            return False

    class FullSampleHook(Hooks):
        pass

    assert not any_hook_needs_full_sample()
    with _hook_context("predicate_opted_out_hook", OptedOutHook):
        assert not any_hook_needs_full_sample()
        with _hook_context("predicate_disabled_hook", DisabledHook):
            assert not any_hook_needs_full_sample()
            with _hook_context("predicate_full_sample_hook", FullSampleHook):
                assert any_hook_needs_full_sample()


class _RaisingEnabledHook(Hooks):
    def enabled(self) -> bool:
        raise RuntimeError("enabled() failed")


class _RaisingNeedsFullSampleHook(Hooks):
    def needs_full_sample(self) -> bool:
        raise RuntimeError("needs_full_sample() failed")


@pytest.mark.parametrize(
    "hook_class",
    [_RaisingEnabledHook, _RaisingNeedsFullSampleHook],
    ids=["enabled", "needs_full_sample"],
)
def test_any_hook_needs_full_sample_guards_raising_hook(
    isolated_hooks_registry, hook_class: type[Hooks]
) -> None:
    """A raising predicate method is logged and counted as needing the full sample."""
    with _hook_context("predicate_raising_hook", hook_class):
        with patch.object(hooks_module.logger, "warning") as warning:
            assert any_hook_needs_full_sample()
    assert hook_class.__name__ in str(warning.call_args)


def test_opted_out_hook_unaffected_on_non_evicted_path(tmp_path: Path) -> None:
    with _hook_context(
        "summary_only_hook_non_evicted", _SummaryOnlyRecordingHook
    ) as hook:
        eval(
            Task(dataset=[Sample("sample_1")]),
            model="mockllm/model",
            log_dir=str(tmp_path),
        )

    assert len(hook.samples) == 1
    assert len(hook.samples[0].events) > 0


@solver
def _setup_marker_solver() -> Solver:
    """No-op setup step, so the plan has a setup entry to find."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


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
