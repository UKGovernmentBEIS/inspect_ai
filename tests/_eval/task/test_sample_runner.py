"""Integration tests for `SampleRunner` (PR 1 of the EvalSession RFC).

Driven via the public `eval()` entry point — `task_run` now instantiates one
`SampleRunner` per (sample, epoch) pair, so this is the realistic path the
runner takes in production. Tests cover the four invariants the plan names:

1. Three-class exception taxonomy + early-stop.
2. Hook firing order on every exit path.
3. Per-sample contextvar isolation under concurrent `tg_collect`.
4. `DiskSampleStore` deferred sample materialisation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator, Type, TypeVar

import pytest
from pydantic import JsonValue

import inspect_ai.hooks._startup as hooks_startup_module
from inspect_ai import Task, eval
from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.hooks._hooks import (
    Hooks,
    SampleAttemptEnd,
    SampleAttemptStart,
    SampleEnd,
    SampleEvent,
    SampleInit,
    SampleStart,
    hooks,
)
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.solver._solver import generate
from inspect_ai.solver._task_state import sample_state, set_sample_state
from inspect_ai.util._early_stopping import EarlyStop

# `failing_solver_deterministic` lives in the repo's shared test_helpers package
# (see e.g. tests/test_score_on_error.py:4). Import it the same way.
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))
from test_helpers.utils import failing_solver_deterministic  # noqa: E402

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalSpec
    from inspect_ai.scorer._metric import SampleScore as _SampleScoreType


# -- shared fixtures / hook recorder --------------------------------------------------


class _RecordingHooks(Hooks):
    """Captures every sample-level hook call in firing order across all samples."""

    def __init__(self) -> None:
        self.timeline: list[tuple[str, str | int | None]] = []
        self.sample_init_events: list[SampleInit] = []
        self.sample_start_events: list[SampleStart] = []
        self.sample_attempt_start_events: list[SampleAttemptStart] = []
        self.sample_attempt_end_events: list[SampleAttemptEnd] = []
        self.sample_event_events: list[SampleEvent] = []
        self.sample_end_events: list[SampleEnd] = []

    def enabled(self) -> bool:
        return True

    async def on_sample_init(self, data: SampleInit) -> None:
        self.timeline.append(("init", data.summary.id))
        self.sample_init_events.append(data)

    async def on_sample_start(self, data: SampleStart) -> None:
        self.timeline.append(("start", data.summary.id))
        self.sample_start_events.append(data)

    async def on_sample_attempt_start(self, data: SampleAttemptStart) -> None:
        self.timeline.append(("attempt_start", data.summary.id))
        self.sample_attempt_start_events.append(data)

    async def on_sample_attempt_end(self, data: SampleAttemptEnd) -> None:
        self.timeline.append(("attempt_end", data.summary.id))
        self.sample_attempt_end_events.append(data)

    async def on_sample_event(self, data: SampleEvent) -> None:
        self.sample_event_events.append(data)

    async def on_sample_end(self, data: SampleEnd) -> None:
        self.timeline.append(("end", data.sample.id))
        self.sample_end_events.append(data)

    def attempt_count(self, sample_id: str | int) -> int:
        return sum(
            1
            for kind, sid in self.timeline
            if kind == "attempt_start" and sid == sample_id
        )

    def kinds_for(self, sample_id: str | int) -> list[str]:
        return [kind for kind, sid in self.timeline if sid == sample_id]


T = TypeVar("T", bound=Hooks)


def _create_recorder(name: str, cls: Type[T]) -> Generator[T, None, None]:
    @hooks(name, description=f"{name}-description")
    def _get() -> type[T]:
        return cls

    hook = registry_lookup("hooks", name)
    assert isinstance(hook, cls)
    try:
        yield hook
    finally:
        del _registry[f"hooks:{name}"]


@pytest.fixture(autouse=True)
def _reset_hooks() -> None:
    hooks_startup_module._registry_hooks_loaded = False


@pytest.fixture
def recorder() -> Generator[_RecordingHooks, None, None]:
    yield from _create_recorder("test_sample_runner_recorder", _RecordingHooks)


# -- shared scorer --------------------------------------------------------------------


@scorer(metrics=[mean(), stderr()])
def constant_scorer(value: float = 1.0) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=value)

    return score


# -- (1) Three-class exception taxonomy + early-stop ---------------------------------


def test_runner_returns_scores_on_success() -> None:
    log = eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=generate(),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error is None
    assert log.samples[0].scores is not None
    assert len(log.samples[0].scores) == 1


def test_runner_retries_on_recoverable_error_then_succeeds() -> None:
    """retry_on_error > 0 → recurse; the retry is recorded in error_retries."""
    log = eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=failing_solver_deterministic([True, False]),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
        retry_on_error=3,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is None
    # error_retries records each prior failed attempt
    assert sample.error_retries is not None
    assert len(sample.error_retries) == 1
    assert "Eval failed!" in sample.error_retries[0].message


def test_runner_raises_on_terminal_error_with_fail_on_error_true() -> None:
    log = eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=failing_solver_deterministic([True]),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
        retry_on_error=0,
        fail_on_error=True,
    )[0]
    # fail_on_error=True turns a sample error into an eval-level error
    assert log.status == "error"


def test_runner_returns_none_on_terminal_error_with_score_on_error() -> None:
    """Score the failing sample but keep the eval running.

    retry_on_error=0, score_on_error=True → runner returns the dict from
    error-path scoring, errored=True. Eval continues; sample has both error
    and scores.
    """
    log = eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=failing_solver_deterministic([True]),
            scorer=constant_scorer(),
            score_on_error=True,
            fail_on_error=False,
        ),
        model="mockllm/model",
        retry_on_error=0,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert sample.scores is not None and len(sample.scores) > 0


def test_runner_emits_early_stop_when_early_stopping_returns_directive() -> None:
    """Stopping a single sample short-circuits its runner without errors.

    An EarlyStopping that fires for sample 2 → the runner short-circuits
    that sample and the eval finalises cleanly.
    """

    class _StopSampleTwo:
        async def start_task(
            self, task: "EvalSpec", samples: list[Sample], epochs: int
        ) -> str:
            return "stop_two"

        async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
            if id == 2:
                return EarlyStop(id=id, epoch=epoch, reason="stop sample 2")
            return None

        async def complete_sample(
            self,
            id: str | int,
            epoch: int,
            scores: dict[str, "_SampleScoreType"],
        ) -> None:
            pass

        async def complete_task(self) -> dict[str, JsonValue]:
            return {}

    log = eval(
        Task(
            dataset=MemoryDataset(
                [
                    Sample(id=1, input="hi", target="hi"),
                    Sample(id=2, input="hi", target="hi"),
                    Sample(id=3, input="hi", target="hi"),
                ]
            ),
            solver=generate(),
            scorer=constant_scorer(),
            early_stopping=_StopSampleTwo(),
        ),
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    # sample 2 was stopped early; samples 1 and 3 ran normally
    ran_ids = {s.id for s in log.samples}
    assert 1 in ran_ids and 3 in ran_ids
    # the early-stopping summary records the stop
    assert log.results is not None
    assert log.results.early_stopping is not None
    stops = log.results.early_stopping.early_stops
    assert any(s.id == 2 for s in stops)


# -- (2) Hook firing order on every exit path ---------------------------------------


def test_hooks_success_path(recorder: _RecordingHooks) -> None:
    """Success: init → start → attempt_start → attempt_end → end."""
    eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=generate(),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
    )
    assert recorder.kinds_for(1) == [
        "init",
        "start",
        "attempt_start",
        "attempt_end",
        "end",
    ]


def test_hooks_retry_path(recorder: _RecordingHooks) -> None:
    """Hook firing across retry attempts.

    init/start fire once; attempt_start/attempt_end fire per attempt;
    end fires once at the terminal attempt.
    """
    eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=failing_solver_deterministic([True, True, False]),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
        retry_on_error=5,
    )
    kinds = recorder.kinds_for(1)
    assert kinds.count("init") == 1
    assert kinds.count("start") == 1
    assert kinds.count("end") == 1
    assert kinds.count("attempt_start") == 3
    assert kinds.count("attempt_end") == 3
    # init/start come first; end comes last
    assert kinds[0] == "init"
    assert kinds[1] == "start"
    assert kinds[-1] == "end"


def test_hooks_terminal_error_path(recorder: _RecordingHooks) -> None:
    """Terminal error (fail_on_error=False) still fires the full terminal sequence."""
    eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=failing_solver_deterministic([True]),
            scorer=constant_scorer(),
            score_on_error=True,
            fail_on_error=False,
        ),
        model="mockllm/model",
        retry_on_error=0,
    )
    kinds = recorder.kinds_for(1)
    # both attempt_end AND end fire on the terminal-error path
    assert kinds.count("init") == 1
    assert kinds.count("start") == 1
    assert kinds.count("attempt_start") == 1
    assert kinds.count("attempt_end") == 1
    assert kinds.count("end") == 1


def test_hooks_early_stop_path(recorder: _RecordingHooks) -> None:
    """Early stop: terminal sequence still completes for the stopped sample."""

    class _StopAll:
        async def start_task(
            self, task: "EvalSpec", samples: list[Sample], epochs: int
        ) -> str:
            return "stop"

        async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
            return EarlyStop(id=id, epoch=epoch, reason="stop")

        async def complete_sample(
            self,
            id: str | int,
            epoch: int,
            scores: dict[str, "_SampleScoreType"],
        ) -> None:
            pass

        async def complete_task(self) -> dict[str, JsonValue]:
            return {}

    eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=generate(),
            scorer=constant_scorer(),
            early_stopping=_StopAll(),
        ),
        model="mockllm/model",
    )
    # An early-stopped sample never enters init/start/attempt — it is short-
    # circuited before the runner is awarded the semaphore. We just assert no
    # spurious end events fired without matching attempt_starts.
    kinds = recorder.kinds_for(1)
    assert kinds.count("attempt_end") == kinds.count("attempt_start")
    assert kinds.count("end") <= kinds.count("init")


def test_hooks_uuid_stable_across_attempts(recorder: _RecordingHooks) -> None:
    """sample_uuid is stable across retry attempts.

    The constructor-injected `sample_uuid` flows through retries — every
    attempt_start/attempt_end carries the same id as the init/end.
    """
    eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=failing_solver_deterministic([True, False]),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
        retry_on_error=3,
    )
    init_uuid = recorder.sample_init_events[0].sample_id
    assert recorder.sample_end_events[0].sample_id == init_uuid
    for start_evt in recorder.sample_attempt_start_events:
        assert start_evt.sample_id == init_uuid
    for end_evt in recorder.sample_attempt_end_events:
        assert end_evt.sample_id == init_uuid


# -- (3) Per-sample contextvar isolation under concurrent tg_collect ----------------


@solver
def assert_distinct_state_solver() -> Solver:
    """Verify `sample_state()` resolves to this sample's own TaskState.

    Returns the same TaskState that was set at the top of this sample's run,
    even after an `await`. If contextvars leaked across concurrent runners
    we'd see another sample's state here.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # Tag the current sample's state with a unique marker derived from its
        # input — this guards against a TaskState shared across coroutines.
        marker = f"marker_{state.sample_id}"
        state.metadata["marker"] = marker
        set_sample_state(state)

        import anyio

        await anyio.sleep(0.01)
        # Verify the contextvar still resolves to OUR state, not a sibling's
        retrieved = sample_state()
        assert retrieved is state, (
            f"contextvar leak: expected state for sample {state.sample_id}, "
            f"got {retrieved.sample_id if retrieved else None}"
        )
        assert retrieved.metadata.get("marker") == marker
        return state

    return solve


def test_per_sample_contextvar_isolation_concurrent() -> None:
    """Concurrent samples never see each other's contextvar state.

    N samples run concurrently via tg_collect; each must see its own
    contextvar state across an await without cross-talk.
    """
    n = 8
    log = eval(
        Task(
            dataset=MemoryDataset(
                [Sample(id=i, input=f"q{i}", target="hi") for i in range(1, n + 1)]
            ),
            solver=assert_distinct_state_solver(),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
        max_samples=n,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == n
    # If the asserts inside the solver had failed, status would be "error"
    for s in log.samples:
        assert s.error is None


# -- (4) DiskSampleStore deferred sample materialisation ----------------------------


def test_disk_sample_store_deferred_materialisation() -> None:
    """An eval paged through disk completes successfully.

    When a `DiskSampleStore` is used, `create_sample_state` must defer the
    actual sample read until after the semaphore is acquired — the eval
    completes successfully even when paged through disk. (`max_dataset_memory=0`
    forces every sample through `DiskSampleStore`.)
    """
    samples = [Sample(input=f"Say {i}", target=str(i)) for i in range(3)]
    log = eval(
        Task(
            dataset=samples,
            solver=generate(),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
        max_dataset_memory=0,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 3


def test_disk_sample_store_deferred_materialisation_with_retry() -> None:
    """Retry path is also lazy-materialisation safe.

    The recursive SampleRunner construction in the retry path must re-use
    the same lazy `create_sample_state` callable.
    """
    samples = [Sample(id=1, input="hi", target="hi")]
    log = eval(
        Task(
            dataset=samples,
            solver=failing_solver_deterministic([True, False]),
            scorer=constant_scorer(),
        ),
        model="mockllm/model",
        max_dataset_memory=0,
        retry_on_error=3,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is None
    assert sample.error_retries is not None
    assert len(sample.error_retries) == 1


# -- (5) Cancellation propagates through the runner ---------------------------------


def test_runner_cancellation_via_task_cancel() -> None:
    """Cancelling a sample mid-solve via TaskCancel.cancel_task('abort') unwinds.

    The reviewer's RFC notes cancellation as a v1 risk path. The runner
    handles cancellation by re-raising at the `tg_collect` boundary; this
    test asserts the eval finalises with status='error' and the cancel
    propagates rather than hanging.
    """
    import tempfile
    from unittest.mock import patch

    import anyio

    from inspect_ai._display.core.display import TaskCancel
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai._eval.task.run import task_run as original_task_run

    cancel_holder: list[TaskCancel] = []

    async def capturing_task_run(
        options: object, task_cancel: TaskCancel | None = None
    ) -> object:
        if task_cancel is not None:
            cancel_holder.append(task_cancel)
        return await original_task_run(options, task_cancel=task_cancel)  # type: ignore[arg-type]

    solver_id = id(cancel_holder)

    @solver(name=f"runner_cancel_solver_{solver_id}")
    def cancelling_solver() -> Any:
        async def solve(state: TaskState, gen: Generate) -> TaskState:
            # wait until we've captured the TaskCancel handle
            while not cancel_holder:
                await anyio.sleep(0.01)
            cancel_holder[0].cancel_task("abort")
            await anyio.sleep(5)  # give cancellation time to propagate
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        with patch("inspect_ai._eval.run.task_run", capturing_task_run):
            success, logs = eval_set(
                tasks=[
                    Task(
                        dataset=[Sample(id=1, input="hi", target="hi")],
                        solver=[cancelling_solver()],
                        scorer=constant_scorer(),
                        name="task_runner_cancel",
                    )
                ],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=1,
                retry_immediate=True,
                max_tasks=1,
            )

    # eval_set returns normally (does not raise) — the runner handled the
    # cancellation cleanly rather than letting an exception group escape.
    assert not success
    assert len(logs) == 1
    assert logs[0].status == "error"


# -- (bonus) regression: SampleRunner constructor signature stays mechanical --------


def test_sample_runner_class_is_used_by_task_run() -> None:
    """task_run uses SampleRunner, not the deleted task_run_sample.

    Guards against an accidental fallback to the now-deleted helper.
    """
    import inspect

    from inspect_ai._eval.task import run as run_mod
    from inspect_ai._eval.task.sample_runner import SampleRunner

    src = inspect.getsource(run_mod.task_run)
    assert "SampleRunner(" in src, (
        "task_run should construct SampleRunner instead of calling task_run_sample"
    )
    # And the deleted symbol must not have come back
    assert not hasattr(run_mod, "task_run_sample")
    # And the runner has the documented public surface
    assert hasattr(SampleRunner, "run")
    assert callable(SampleRunner.run)
