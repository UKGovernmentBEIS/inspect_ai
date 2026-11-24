import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Generator, Type, TypeVar
from unittest.mock import patch

import anyio
import anyio.lowlevel
import pytest
from pydantic import JsonValue

import inspect_ai.hooks._startup as hooks_startup_module
from inspect_ai import SampleSource, TaskSource, eval, eval_async
from inspect_ai._control.cancel import cancel_task
from inspect_ai._eval.task.task import Task
from inspect_ai._util._async import current_async_backend
from inspect_ai._util.entrypoints import (
    clear_entry_points_state,
    ensure_entry_points,
    entry_point_load_errors,
)
from inspect_ai._util.environ import environ_var
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import _registry, registry_info, registry_lookup
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event import InfoEvent, TimelineEvent, timeline_build
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
    has_api_key_override,
    hooks,
    override_api_key,
)
from inspect_ai.hooks._startup import _load_registry_hooks, init_hooks
from inspect_ai.log import EvalLog, list_eval_logs_async, read_eval_log_async
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import EvalSample, EvalSpec
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import EvalRecorder, ZipLogFile
from inspect_ai.log._transcript import transcript
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import Metric, SampleScore, match, metric
from inspect_ai.solver._solver import Generate, Solver, generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import EarlyStop, LimitExceededError


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


class AwaitingRunHooks(Hooks):
    """Run hooks that await, so cancellation can reach them."""

    def __init__(self) -> None:
        self.run_start_suspended: anyio.Event | None = None
        self.run_end_events: list[RunEnd] = []

    async def on_run_start(self, data: RunStart) -> None:
        if self.run_start_suspended is not None:
            self.run_start_suspended.set()
            await anyio.sleep_forever()

    async def on_run_end(self, data: RunEnd) -> None:
        await anyio.lowlevel.checkpoint()
        self.run_end_events.append(data)


class DisablingHooks(MockHooks):
    """Mock hooks that disable themselves once their task start is entered."""

    async def on_task_start(self, data: TaskStart) -> None:
        await super().on_task_start(data)
        self.should_enable = False


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
def disabling_hooks() -> Generator[DisablingHooks, None, None]:
    yield from _create_mock_hooks("test_disabling_hooks", DisablingHooks)


@pytest.fixture
def hooks_minimal() -> Generator[MockMinimalHooks, None, None]:
    yield from _create_mock_hooks("test_hooks_minimal", MockMinimalHooks)


@pytest.fixture
def awaiting_run_hooks() -> Generator[AwaitingRunHooks, None, None]:
    yield from _create_mock_hooks("test_awaiting_run_hooks", AwaitingRunHooks)


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


async def test_task_end_reaches_hook_disabled_after_task_start(
    disabling_hooks: DisablingHooks,
) -> None:
    # a hook whose on_task_start was entered still gets its one on_task_end
    # after enabled() turns false, while its other callbacks stay filtered
    log = await eval_async(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert [start.eval_id for start in disabling_hooks.task_start_events] == [
        log[0].eval.eval_id
    ]
    assert [
        (end.eval_id, end.log.status) for end in disabling_hooks.task_end_events
    ] == [(log[0].eval.eval_id, "success")]
    assert len(disabling_hooks.run_start_events) == 1
    assert not disabling_hooks.sample_start_events
    assert not disabling_hooks.sample_end_events
    assert not disabling_hooks.model_usage_events
    assert not disabling_hooks.run_end_events


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


async def test_run_end_hook_runs_when_cancelled_during_run_start(
    awaiting_run_hooks: AwaitingRunHooks,
) -> None:
    awaiting_run_hooks.run_start_suspended = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(_eval_async_one_sample)
        await awaiting_run_hooks.run_start_suspended.wait()
        tg.cancel_scope.cancel()

    (run_end,) = awaiting_run_hooks.run_end_events
    assert isinstance(run_end.exception, anyio.get_cancelled_exc_class())
    assert run_end.logs == []

    # the cancelled run no longer counts as running
    awaiting_run_hooks.run_start_suspended = None
    (log,) = await _eval_async_one_sample()
    assert log.status == "success"
    assert len(awaiting_run_hooks.run_end_events) == 2


async def test_run_end_hook_finishes_once_when_samples_are_cancelled(
    awaiting_run_hooks: AwaitingRunHooks, tmp_path: Path
) -> None:
    sample_started = anyio.Event()

    @solver
    def wait_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sample_started.set()
            await anyio.sleep_forever()
            return state

        return solve

    async with anyio.create_task_group() as tg:
        tg.start_soon(_eval_async_one_sample, wait_solver(), str(tmp_path))
        await sample_started.wait()
        tg.cancel_scope.cancel()

    (log_info,) = await list_eval_logs_async(str(tmp_path))
    log = await read_eval_log_async(log_info.name, header_only=True)
    assert log.status == "cancelled"
    (run_end,) = awaiting_run_hooks.run_end_events
    if current_async_backend() == "trio":
        # the run is finished shielded and gets its log
        assert run_end.exception is None
        assert [log.status for log in run_end.logs] == ["cancelled"]
    else:
        # the cancellation cuts the hook short; it runs again with it
        assert isinstance(run_end.exception, anyio.get_cancelled_exc_class())
        assert run_end.logs == []

    (log,) = await _eval_async_one_sample()
    assert log.status == "success"
    assert len(awaiting_run_hooks.run_end_events) == 2


def test_task_end_hook_runs_when_task_is_aborted(mock_hooks: MockHooks) -> None:
    # `inspect ctl task cancel` aborts a task: its log ends with an error status,
    # and on_task_end must still be called with that log
    victim_running = anyio.Event()

    @solver
    def wait_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            victim_running.set()
            await anyio.sleep_forever()
            return state

        return solve

    @solver
    def cancel_victim_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await victim_running.wait()
            (victim,) = [
                event
                for event in mock_hooks.task_start_events
                if event.spec.task == "victim"
            ]
            cancel_task(victim.spec.task_id)
            return state

        return solve

    logs = eval(
        [
            Task(dataset=[Sample("sample_1")], solver=wait_solver(), name="victim"),
            Task(
                dataset=[Sample("sample_1")],
                solver=cancel_victim_solver(),
                name="canceller",
            ),
        ],
        model="mockllm/model",
        max_tasks=2,
    )

    assert {log.eval.task: log.status for log in logs} == {
        "victim": "error",
        "canceller": "success",
    }
    ended = sorted(
        (event.log.eval.task, event.log.status) for event in mock_hooks.task_end_events
    )
    assert ended == [("canceller", "success"), ("victim", "error")]


async def test_task_end_hook_runs_when_task_is_cancelled(
    mock_hooks: MockHooks, tmp_path: Path
) -> None:
    sample_started = anyio.Event()

    @solver
    def wait_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sample_started.set()
            await anyio.sleep_forever()
            return state

        return solve

    async with anyio.create_task_group() as tg:
        tg.start_soon(_eval_async_one_sample, wait_solver(), str(tmp_path))
        await sample_started.wait()
        tg.cancel_scope.cancel()

    (task_end,) = mock_hooks.task_end_events
    assert task_end.log.status == "cancelled"


def test_task_end_hook_runs_when_task_raises(mock_hooks: MockHooks) -> None:
    # an exception escaping the task (here, while computing results) ends it
    # with an error log, which on_task_end must receive
    with patch(
        "inspect_ai._eval.task.run.eval_results", side_effect=RuntimeError("boom")
    ):
        (log,) = eval(
            Task(dataset=[Sample("sample_1")], solver=generate(), scorer=match()),
            model="mockllm/model",
        )

    assert log.status == "error"
    (task_end,) = mock_hooks.task_end_events
    assert task_end.log.status == "error"
    assert task_end.log.error is not None
    assert "boom" in task_end.log.error.message


def test_task_end_hook_not_called_without_task_start(mock_hooks: MockHooks) -> None:
    # a task that fails before on_task_start was called gets an error log but
    # no end hook, so hooks never see an end without its start
    with patch(
        "inspect_ai._eval.task.run.register_eval", side_effect=RuntimeError("boom")
    ):
        (log,) = eval(
            Task(dataset=[Sample("sample_1")], solver=generate()),
            model="mockllm/model",
        )

    assert log.status == "error"
    assert mock_hooks.task_start_events == []
    assert mock_hooks.task_end_events == []


def test_task_end_hook_runs_for_each_retry_attempt(mock_hooks: MockHooks) -> None:
    # each task retry attempt is its own start/end pair, with that attempt's log
    (log,) = eval(
        Task(dataset=[Sample("sample_1")], solver=_fail_n_times_solver(2)),
        model="mockllm/model",
        task_retry_attempts=1,
    )

    assert log.status == "success"
    assert len(mock_hooks.task_start_events) == 2
    assert [event.log.status for event in mock_hooks.task_end_events] == [
        "error",
        "success",
    ]
    assert [event.eval_id for event in mock_hooks.task_end_events] == [
        event.eval_id for event in mock_hooks.task_start_events
    ]


def test_task_end_hook_runs_before_debug_errors_reraise(
    mock_hooks: MockHooks,
) -> None:
    with patch(
        "inspect_ai._eval.task.run.eval_results", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError, match="boom"):
            eval(
                Task(dataset=[Sample("sample_1")], solver=generate(), scorer=match()),
                model="mockllm/model",
                debug_errors=True,
            )

    (task_end,) = mock_hooks.task_end_events
    assert task_end.log.status == "error"
    assert task_end.log.error is not None
    assert "boom" in task_end.log.error.message


def test_task_end_hook_runs_when_log_write_fails(mock_hooks: MockHooks) -> None:
    # with no final log written, the hook gets the errored log that eval returns
    with patch(
        "inspect_ai._eval.task.run._finish_task_log",
        side_effect=OSError("log storage unreachable"),
    ):
        (log,) = eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert log.status == "error"
    assert log.error is not None
    assert "log storage unreachable" in log.error.message
    (task_end,) = mock_hooks.task_end_events
    assert task_end.log.status == "error"
    assert task_end.log.error is not None
    assert task_end.log.error.message == log.error.message


class TaskPairHooks(Hooks):
    """Records task starts and ends, and can raise a limit or block in them."""

    def __init__(self) -> None:
        self.task_start_events: list[TaskStart] = []
        self.task_end_events: list[TaskEnd] = []
        self.start_limit = False
        self.end_limit = False
        self.start_blocked: anyio.Event | None = None
        self.end_entered: anyio.Event | None = None
        self.end_release: anyio.Event | None = None
        self.end_cancelled_task: str | None = None

    async def on_task_start(self, data: TaskStart) -> None:
        self.task_start_events.append(data)
        if self.start_limit:
            raise LimitExceededError("custom", value=1, limit=0)
        if self.start_blocked is not None:
            self.start_blocked.set()
            await anyio.sleep_forever()

    async def on_task_end(self, data: TaskEnd) -> None:
        self.task_end_events.append(data)
        if self.end_limit:
            raise LimitExceededError("custom", value=1, limit=0)
        if data.log.eval.task == self.end_cancelled_task:
            raise await _captured_cancellation()
        if self.end_entered is not None and self.end_release is not None:
            self.end_entered.set()
            await self.end_release.wait()


async def _captured_cancellation() -> BaseException:
    """A cancellation exception caught from a scope that has since exited."""
    with anyio.CancelScope() as scope:
        scope.cancel()
        try:
            await anyio.lowlevel.checkpoint()
        except anyio.get_cancelled_exc_class() as ex:
            return ex
    raise AssertionError("cancelled scope did not raise")


@pytest.fixture
def first_hooks() -> Generator[TaskPairHooks, None, None]:
    # request before mock_hooks so these hooks are called first
    yield from _create_mock_hooks("test_first_hooks", TaskPairHooks)


@pytest.fixture
def second_hooks(
    first_hooks: TaskPairHooks,
) -> Generator[TaskPairHooks, None, None]:
    # registered after first_hooks; request before mock_hooks
    yield from _create_mock_hooks("test_second_hooks", TaskPairHooks)


@solver
def _abort_task_solver(hooks: MockHooks, skip_first: bool = False) -> Solver:
    """Aborts its own task; with `skip_first`, the first sample completes."""
    runs = 0

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        nonlocal runs
        runs += 1
        if skip_first and runs == 1:
            return state
        (start,) = hooks.task_start_events
        cancel_task(start.spec.task_id)
        await anyio.sleep_forever()
        return state

    return solve


async def test_task_end_hook_error_does_not_replace_aborted_task_log(
    first_hooks: TaskPairHooks, mock_hooks: MockHooks
) -> None:
    # a hook that raises in the shielded cancel path must not stop the aborted
    # task's log from being returned, or later hooks from getting their end
    first_hooks.end_limit = True
    with anyio.fail_after(60):
        (log,) = await eval_async(
            Task(dataset=[Sample("sample_1")], solver=_abort_task_solver(mock_hooks)),
            model="mockllm/model",
            ctl_server=False,
        )

    assert log.status == "error"
    assert log.error is not None
    assert "Task cancelled by user" in log.error.message
    for hooks_ in (first_hooks, mock_hooks):
        (task_end,) = hooks_.task_end_events
        assert task_end.log.status == "error"


async def test_task_end_hook_runs_when_cancel_results_fail(
    mock_hooks: MockHooks,
) -> None:
    # a metric that fails on the partial scores of an aborted task makes the
    # cancel handler raise before its log is written; the hook still gets the
    # errored log eval returns
    @metric
    def failing_metric() -> Metric:
        def compute(scores: list[SampleScore]) -> float:
            raise RuntimeError("metric failed")

        return compute

    with anyio.fail_after(60):
        (log,) = await eval_async(
            Task(
                dataset=[Sample("a"), Sample("b")],
                # max_samples=1: the second sample (which aborts) starts only
                # after the first has been scored
                solver=_abort_task_solver(mock_hooks, skip_first=True),
                scorer=match(),
                metrics=[failing_metric()],
            ),
            model="mockllm/model",
            max_samples=1,
            score_display=False,
            ctl_server=False,
        )

    assert log.status == "error"
    assert log.error is not None
    assert "metric failed" in log.error.message
    (task_end,) = mock_hooks.task_end_events
    assert task_end.log.status == "error"
    assert task_end.log.error is not None
    assert task_end.log.error.message == log.error.message


class _FailingEarlyStopping:
    """Fails its task at startup, before any sample runs."""

    async def start_task(
        self, task: EvalSpec, samples: list[Sample], epochs: int
    ) -> str:
        raise RuntimeError("early stopping failed")

    async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
        return None

    async def complete_sample(
        self, id: str | int, epoch: int, scores: dict[str, SampleScore]
    ) -> None:
        pass

    async def complete_task(self) -> dict[str, JsonValue]:
        return {}


def _victim_and_queued_tasks() -> list[Task]:
    """A task that fails at startup, then one queued behind it."""
    return [
        Task(
            dataset=[Sample("a")],
            early_stopping=_FailingEarlyStopping(),
            name="victim",
        ),
        Task(dataset=[Sample("b")], name="queued"),
    ]


async def _eval_victim_and_queued(
    tasks: list[Task] | TaskSource, log_dir: Path, **kwargs: Any
) -> list[EvalLog]:
    return await eval_async(
        tasks,
        model="mockllm/model",
        max_tasks=1,
        log_dir=str(log_dir),
        ctl_server=False,
        **kwargs,
    )


async def _assert_victim_log_kept(
    logs: list[EvalLog],
    *hooks: TaskPairHooks | MockHooks,
    error: str = "early stopping failed",
) -> None:
    """The victim's written error log is returned and given to every hook."""
    assert {log.eval.task: log.status for log in logs} == {
        "victim": "error",
        "queued": "success",
    }
    (victim,) = [log for log in logs if log.eval.task == "victim"]
    assert victim.error is not None
    assert error in victim.error.message
    written = await read_eval_log_async(victim.location, header_only=True)
    assert written.status == "error"
    assert written.error is not None
    assert written.error.message == victim.error.message
    for hooks_ in hooks:
        assert sorted(
            (
                event.log.eval.task,
                event.log.status,
                event.log.error.message if event.log.error else None,
            )
            for event in hooks_.task_end_events
        ) == [("queued", "success", None), ("victim", "error", victim.error.message)]


@pytest.mark.parametrize(
    "consumer", [None, "task_source", "task_source_error", "legacy_telemetry"]
)
async def test_task_end_hook_abort_during_error_end_keeps_log(
    first_hooks: TaskPairHooks,
    mock_hooks: MockHooks,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    consumer: str | None,
) -> None:
    # an abort landing while an errored task's end hook runs must not discard
    # its written log, change the log later hooks get, or stop queued tasks,
    # even when a completion consumer awaits or fails after the end hooks
    first_hooks.end_entered = anyio.Event()
    first_hooks.end_release = anyio.Event()

    async def abort_during_end_hook() -> None:
        assert first_hooks.end_entered is not None
        assert first_hooks.end_release is not None
        await first_hooks.end_entered.wait()
        (start,) = mock_hooks.task_start_events
        assert start.spec.task == "victim"
        result = cancel_task(start.spec.task_id)
        assert result is not None and result.get("changed") is True
        first_hooks.end_release.set()

    async def task_complete(log: EvalLog) -> list[Task] | None:
        if consumer == "task_source_error" and log.eval.task == "victim":
            raise RuntimeError("completion callback failure")
        await anyio.lowlevel.checkpoint()
        return None

    async def send_telemetry(type: str, json: str) -> bool:
        await anyio.lowlevel.checkpoint()
        return True

    if consumer == "legacy_telemetry":
        monkeypatch.setattr("inspect_ai.hooks._legacy._send_telemetry", send_telemetry)

    tasks = _victim_and_queued_tasks()
    logs: list[EvalLog] = []

    async def run_eval() -> None:
        logs.extend(
            await _eval_victim_and_queued(
                TaskSource.from_tasks(tasks, task_complete=task_complete)
                if consumer in ("task_source", "task_source_error")
                else tasks,
                tmp_path,
            )
        )

    with anyio.fail_after(60):
        async with anyio.create_task_group() as tg:
            tg.start_soon(abort_during_end_hook)
            tg.start_soon(run_eval)

    await _assert_victim_log_kept(logs, first_hooks, mock_hooks)


@pytest.mark.parametrize("failure", ["task_complete_error", "end_hook_limit"])
async def test_successful_task_keeps_log_after_completion_failure(
    first_hooks: TaskPairHooks,
    mock_hooks: MockHooks,
    tmp_path: Path,
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a successful task whose TaskSource.task_complete raises, or whose end
    # hook raises LimitExceededError, returns its written success log and is
    # not retried, even with a retry budget
    completed: list[EvalLog] = []

    async def task_complete(log: EvalLog) -> list[Task] | None:
        completed.append(log)
        if failure == "task_complete_error":
            raise RuntimeError("completion callback failure")
        return None

    first_hooks.end_limit = failure == "end_hook_limit"
    caplog.set_level("ERROR", logger="inspect_ai._eval")
    with anyio.fail_after(60):
        (log,) = await eval_async(
            TaskSource.from_tasks(
                [Task(dataset=[Sample("a")], name="succeeds")],
                task_complete=task_complete,
            ),
            model="mockllm/model",
            log_dir=str(tmp_path),
            task_retry_attempts=1,
            ctl_server=False,
        )

    assert log.status == "success"
    assert log.error is None
    written = await read_eval_log_async(log.location, header_only=True)
    assert written.status == "success"
    assert written.error is None
    assert [log.eval.eval_id for log in completed] == [log.eval.eval_id]
    # the logged error keeps the suppressed exception's traceback
    logged = (
        "task_complete() raised"
        if failure == "task_complete_error"
        else ("error after writing its log")
    )
    (record,) = [r for r in caplog.records if logged in r.getMessage()]
    assert record.exc_info is not None and record.exc_info[2] is not None
    for hooks_ in (first_hooks, mock_hooks):
        assert [start.eval_id for start in hooks_.task_start_events] == [
            log.eval.eval_id
        ]
        assert [
            (end.eval_id, end.log.status, end.log.error)
            for end in hooks_.task_end_events
        ] == [(log.eval.eval_id, "success", None)]


@pytest.mark.parametrize("cancelling", [1, 2])
async def test_task_end_hook_raising_cancellation_keeps_log(
    first_hooks: TaskPairHooks,
    second_hooks: TaskPairHooks,
    mock_hooks: MockHooks,
    tmp_path: Path,
    cancelling: int,
) -> None:
    # end hooks raising a cancellation exception of their own, with nothing
    # cancelled, must not discard the written log or stop queued tasks; every
    # later hook gets the written log and a raising hook gets no second end
    for hooks_ in (first_hooks, second_hooks)[:cancelling]:
        hooks_.end_cancelled_task = "victim"
    with anyio.fail_after(60):
        logs = await _eval_victim_and_queued(_victim_and_queued_tasks(), tmp_path)

    await _assert_victim_log_kept(logs, first_hooks, second_hooks, mock_hooks)


async def test_task_end_hook_raising_cancellation_keeps_write_error(
    first_hooks: TaskPairHooks,
    mock_hooks: MockHooks,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # with the victim's final log write failing, an end hook raising a
    # cancellation exception must not replace the write error, stop the
    # later hook's end, or stop queued tasks
    recorder_log_finish = EvalRecorder.log_finish

    async def log_finish(
        self: EvalRecorder, eval: EvalSpec, *args: Any, **kwargs: Any
    ) -> EvalLog:
        if eval.task == "victim":
            raise OSError("log storage unreachable")
        return await recorder_log_finish(self, eval, *args, **kwargs)

    monkeypatch.setattr(EvalRecorder, "log_finish", log_finish)
    first_hooks.end_cancelled_task = "victim"
    with anyio.fail_after(60):
        logs = await _eval_victim_and_queued(_victim_and_queued_tasks(), tmp_path)

    assert {log.eval.task: log.status for log in logs} == {
        "victim": "error",
        "queued": "success",
    }
    (victim,) = [log for log in logs if log.eval.task == "victim"]
    assert victim.error is not None
    assert "log storage unreachable" in victim.error.message
    for hooks_ in (first_hooks, mock_hooks):
        assert sorted(
            (
                event.log.eval.task,
                event.log.status,
                event.log.error.message if event.log.error else None,
            )
            for event in hooks_.task_end_events
        ) == [("queued", "success", None), ("victim", "error", victim.error.message)]


def _abort_victim(eval: EvalSpec) -> None:
    if eval.task == "victim":
        result = cancel_task(eval.task_id)
        assert result is not None and result.get("changed") is True


async def _failing_next_samples() -> list[Sample] | None:
    raise RuntimeError("sample source failed")


@pytest.mark.parametrize("abort_at", ["durable_flush", "recorder_return"])
async def test_task_end_hook_abort_after_log_write_keeps_log(
    first_hooks: TaskPairHooks,
    mock_hooks: MockHooks,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    abort_at: str,
) -> None:
    # an abort landing once the log is durably written, either before the
    # recorder closes and returns it or while TaskLogger.log_finish still
    # cleans up, must not discard that log or skip releasing the realtime
    # buffer: its database is deleted and its shared sync worker stopped.
    # The victim is source-driven, so it stays abortable after its sample
    # runs (which starts the sync worker), then fails when the source is
    # asked for more samples.
    buffers: list[SampleBufferDatabase] = []
    sync_workers: list[threading.Thread] = []
    buffer_init = SampleBufferDatabase.__init__
    buffer_sync = SampleBufferDatabase._sync

    def init(self: SampleBufferDatabase, *args: Any, **kwargs: Any) -> None:
        buffer_init(self, *args, **kwargs)
        buffers.append(self)

    def sync(self: SampleBufferDatabase) -> None:
        buffer_sync(self)
        if "_victim_" in self.location and self._sync_thread is not None:
            sync_workers.append(self._sync_thread)

    monkeypatch.setattr(SampleBufferDatabase, "__init__", init)
    monkeypatch.setattr(SampleBufferDatabase, "_sync", sync)
    if abort_at == "durable_flush":
        zip_flush = ZipLogFile.flush

        async def flush(self: ZipLogFile, *, fsync: bool = True) -> None:
            await zip_flush(self, fsync=fsync)
            if fsync and self.log_start is not None:
                _abort_victim(self.log_start.eval)

        monkeypatch.setattr(ZipLogFile, "flush", flush)
    else:
        recorder_log_finish = EvalRecorder.log_finish

        async def log_finish(
            self: EvalRecorder, eval: EvalSpec, *args: Any, **kwargs: Any
        ) -> EvalLog:
            log = await recorder_log_finish(self, eval, *args, **kwargs)
            _abort_victim(eval)
            return log

        monkeypatch.setattr(EvalRecorder, "log_finish", log_finish)
    victim = Task(
        dataset=SampleSource.from_samples(
            [Sample("a")], next_samples=_failing_next_samples
        ),
        name="victim",
    )
    with anyio.fail_after(60):
        logs = await _eval_victim_and_queued(
            [victim, Task(dataset=[Sample("b")], name="queued")],
            tmp_path,
            log_shared=1,
        )

    await _assert_victim_log_kept(
        logs, first_hooks, mock_hooks, error="sample source failed"
    )
    (victim_buffer,) = [b for b in buffers if "_victim_" in b.location]
    assert not victim_buffer.db_path.exists()
    assert sync_workers
    assert not any(worker.is_alive() for worker in sync_workers)


def test_task_end_hook_only_for_entered_start_hooks(
    first_hooks: TaskPairHooks, mock_hooks: MockHooks
) -> None:
    # a limit raised by the first start hook skips the later start hooks, so
    # only the first gets an end
    first_hooks.start_limit = True
    (log,) = eval(Task(dataset=[Sample("sample_1")]), model="mockllm/model")

    assert log.status == "error"
    (task_end,) = first_hooks.task_end_events
    assert task_end.log.status == "error"
    assert mock_hooks.task_start_events == []
    assert mock_hooks.task_end_events == []


async def test_task_end_hook_when_cancelled_during_start_hook(
    first_hooks: TaskPairHooks, mock_hooks: MockHooks, tmp_path: Path
) -> None:
    first_hooks.start_blocked = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(_eval_async_one_sample, generate(), str(tmp_path))
        await first_hooks.start_blocked.wait()
        tg.cancel_scope.cancel()

    (task_end,) = first_hooks.task_end_events
    assert task_end.log.status == "cancelled"
    assert mock_hooks.task_start_events == []
    assert mock_hooks.task_end_events == []


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


class _FakeEntryPoint:
    """Stand-in for an `inspect_ai` entry point that registers a hook on load."""

    def __init__(self, name: str, hook_name: str) -> None:
        self.name = name
        self.value = f"{name}:hooks"
        self._hook_name = hook_name

    def load(self) -> None:
        @hooks(self._hook_name, description=f"{self._hook_name}-description")
        def get_hooks_class() -> Type[MockMinimalHooks]:
            return MockMinimalHooks


def test_entry_point_hooks_load_when_a_hook_is_already_registered(
    mock_hooks: MockHooks,
) -> None:
    # registry_find() only scans entry points when its own scan finds nothing, so
    # any hook registered before startup (e.g. by the INSPECT_TELEMETRY package)
    # used to hide every entry-point hook from the one-shot load.
    entry_point_hook_name = "test_hooks_entry_point"
    entry_point = _FakeEntryPoint("test_hooks_package", entry_point_hook_name)

    clear_entry_points_state()
    try:
        with patch(
            "inspect_ai._util.entrypoints.entry_points", return_value=[entry_point]
        ):
            loaded = _load_registry_hooks()
    finally:
        _registry.pop(f"hooks:{entry_point_hook_name}", None)
        clear_entry_points_state()
        ensure_entry_points()

    loaded_names = {registry_info(hook).name for hook in loaded}
    assert "test_hooks" in loaded_names
    assert entry_point_hook_name in loaded_names


def test_required_entry_point_hook_not_reported_missing_when_a_hook_is_already_registered(
    mock_hooks: MockHooks,
) -> None:
    # The loud symptom of the same bug: with the entry-point hook hidden,
    # INSPECT_REQUIRED_HOOKS verification raised a PrerequisiteError naming a
    # hook that was in fact installed.
    entry_point_hook_name = "test_hooks_entry_point_required"
    entry_point = _FakeEntryPoint("test_hooks_package_required", entry_point_hook_name)

    clear_entry_points_state()
    try:
        with patch(
            "inspect_ai._util.entrypoints.entry_points", return_value=[entry_point]
        ):
            with environ_var("INSPECT_REQUIRED_HOOKS", entry_point_hook_name):
                loaded = _load_registry_hooks()
    finally:
        _registry.pop(f"hooks:{entry_point_hook_name}", None)
        clear_entry_points_state()
        ensure_entry_points()

    assert entry_point_hook_name in {registry_info(hook).name for hook in loaded}


class _FailingEntryPoint:
    """Stand-in for an `inspect_ai` entry point whose module fails to import."""

    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value

    def load(self) -> None:
        raise ModuleNotFoundError("No module named 'inspect_ai._does_not_exist'")


@contextmanager
def _entry_points(*eps: object) -> Generator[None, None, None]:
    clear_entry_points_state()
    try:
        with patch("inspect_ai._util.entrypoints.entry_points", return_value=list(eps)):
            yield
    finally:
        clear_entry_points_state()
        ensure_entry_points()


@pytest.mark.parametrize(
    "entry_point",
    [
        # matched by the top-level module of the entry point value
        _FailingEntryPoint("broken_hooks_ep", "broken_hooks_pkg._registry"),
        # matched by the entry point name
        _FailingEntryPoint("broken_hooks_pkg", "other_module._registry"),
    ],
)
def test_required_hook_entry_point_load_error_raises_with_cause(
    entry_point: _FailingEntryPoint,
) -> None:
    with _entry_points(entry_point):
        with environ_var("INSPECT_REQUIRED_HOOKS", "broken_hooks_pkg/audit"):
            with pytest.raises(PrerequisiteError) as exc_info:
                _load_registry_hooks()
            # a repeat load still raises rather than treating hooks as loaded
            with pytest.raises(PrerequisiteError):
                _load_registry_hooks()

    message = str(exc_info.value)
    assert "broken_hooks_pkg/audit" in message
    assert f"'{entry_point.value}'" in message
    assert (
        "ModuleNotFoundError: No module named 'inspect_ai._does_not_exist'" in message
    )
    assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)


def test_entry_point_load_error_cleared_when_retry_succeeds() -> None:
    entry_point = _FailingEntryPoint("flaky_hooks_pkg", "flaky_hooks_pkg._registry")
    with _entry_points(entry_point):
        ensure_entry_points()
        assert entry_point in entry_point_load_errors()
        with patch.object(entry_point, "load"):
            ensure_entry_points()
        assert entry_point not in entry_point_load_errors()


@pytest.mark.parametrize("required_hooks", ["", "test_hooks"])
def test_unrelated_entry_point_load_error_only_warns(
    required_hooks: str,
    mock_hooks: MockHooks,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry_point = _FailingEntryPoint("broken_extension", "broken_extension._registry")
    with _entry_points(entry_point):
        with environ_var("INSPECT_REQUIRED_HOOKS", required_hooks):
            loaded = _load_registry_hooks()

    assert "test_hooks" in {registry_info(hook).name for hook in loaded}
    assert "loading entrypoints from 'broken_extension._registry'" in caplog.text


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
        # a repeat call still raises rather than treating hooks as loaded
        with pytest.raises(PrerequisiteError):
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


async def _eval_async_one_sample(
    solver: Solver = generate(), log_dir: str | None = None
) -> list[EvalLog]:
    return await eval_async(
        Task(dataset=[Sample("sample_1")], solver=solver),
        model="mockllm/model",
        log_dir=log_dir,
        ctl_server=False,
    )


@contextmanager
def _hook_context(name: str, hooks_class: Type[T]) -> Generator[T, None, None]:
    yield from _create_mock_hooks(name, hooks_class)


@solver
def _emitting_solver_with_model_response() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for i in range(100):
            transcript().info({"i": i})
        assert transcript().history.resident_events_truncated
        state = await generate(state)
        transcript().add_timeline(
            timeline_build(list(transcript().events), name="test-timeline")
        )
        return state

    return solve


class _RecordingHook(Hooks):
    def __init__(self) -> None:
        self.samples: list[EvalSample] = []

    async def on_sample_end(self, data: SampleEnd) -> None:
        self.samples.append(data.sample)


class _SummaryOnlyRecordingHook(_RecordingHook):
    def needs_full_sample(self) -> bool:
        return False


class _DisabledRecordingHook(_RecordingHook):
    def enabled(self) -> bool:
        return False


class _RaisingNeedsFullSampleHook(_RecordingHook):
    def needs_full_sample(self) -> bool:
        raise RuntimeError("needs_full_sample() failed")


@pytest.mark.parametrize(
    ("other_hook_class", "expect_full"),
    [
        pytest.param(None, False, id="summary-only"),
        pytest.param(MockMinimalHooks, False, id="no-sample-end"),
        pytest.param(_DisabledRecordingHook, False, id="disabled"),
        pytest.param(_RecordingHook, True, id="mixed"),
        pytest.param(_RaisingNeedsFullSampleHook, True, id="predicate-error"),
    ],
)
def test_opted_out_hook_receives_event_less_sample_when_evicted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_hooks_registry: None,
    caplog: pytest.LogCaptureFixture,
    other_hook_class: type[Hooks] | None,
    expect_full: bool,
) -> None:
    import inspect_ai._eval.task.run as run_module

    monkeypatch.setattr(run_module, "DEFAULT_RESIDENT_TAIL", 20)
    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")
    # The final response stays resident and exceeds the attachment threshold.
    long_response = "x" * 150
    other_context = (
        _hook_context("other_finalization_hook", other_hook_class)
        if other_hook_class is not None
        else nullcontext(None)
    )
    with (
        _hook_context("summary_only_hook", _SummaryOnlyRecordingHook) as hook,
        other_context as other,
    ):
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
    if expect_full:
        assert sample.events and sample.attachments and sample.timelines
        assert isinstance(other, _RecordingHook) and other.samples == [sample]
    else:
        assert sample.events == []
        assert sample.attachments == {}
        assert sample.timelines is None
        if isinstance(other, _RecordingHook):
            assert other.samples == []
    if isinstance(other, MockMinimalHooks):
        assert len(other.run_start_events) == 1
    assert sample.output.completion == long_response
    assert sample.messages
    assert sample.total_time is not None
    if other_hook_class is _RaisingNeedsFullSampleHook:
        assert "needs_full_sample() failed" in caplog.text

    log = read_eval_log(str(next(tmp_path.glob("*.eval"))))
    assert log.status == "success"
    assert log.samples is not None
    logged = log.samples[0]
    assert [
        event.data["i"]
        for event in logged.events
        if isinstance(event, InfoEvent)
        and isinstance(event.data, dict)
        and "i" in event.data
    ] == list(range(100))
    assert long_response in logged.attachments.values()
    assert logged.timelines is not None
    assert logged.timelines[0].name == "test-timeline"
    timeline_event_ids = {
        item.event.uuid
        for item in logged.timelines[0].root.content
        if isinstance(item, TimelineEvent)
    }
    assert timeline_event_ids and timeline_event_ids <= {
        event.uuid for event in logged.events
    }


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
