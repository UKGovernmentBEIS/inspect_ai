"""Tests for a run's task records, its scheduling loop, and preparing tasks.

The loop tests drive `TaskDispatcher` without a full eval: tasks are real
resolved tasks, but their loggers are fakes, preparing a task returns the
sandbox configs (here plain strings) the test gives it, those configs are set
up by a real `SetupCache` whose setups the test finishes, and running a task
is replaced by a scripted `_run_task`, so each test controls exactly when every
setup and every task finishes and how. The end-to-end tests at the bottom run
real evals with a sandbox provider whose `task_init` the test controls.
"""

import functools
import gc
import os
import weakref
from operator import contains
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Literal, cast, overload

import anyio
import pytest
from typing_extensions import override

from inspect_ai import Epochs, Task, TaskSource, enqueue_task, eval, eval_async
from inspect_ai._control.cancel import cancel_task, drain_task
from inspect_ai._control.eval_state import (
    abandon_task_retry,
    reset_retry_abandoned,
    task_retry_abandoned,
)
from inspect_ai._control.max_tasks import (
    reset_max_tasks_override,
    set_max_tasks_override,
    task_dispatcher_stats,
)
from inspect_ai._control.pause import _task_gate, reset_task_pause_gates
from inspect_ai._display import display
from inspect_ai._display.core.display import CancelType, TaskSpec
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.run import (
    _TASK_OVERRIDABLE,
    TaskDispatcher,
    TaskRunResult,
    open_log,
    wants_retry,
)
from inspect_ai._eval.task.enqueue import (
    ConfiguredTask,
    RunTasks,
    TaskRecord,
    clear_run_tasks,
    register_run_tasks,
)
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._eval.task.run import TaskRunOptions
from inspect_ai._eval.task.setup_cache import SetupCache
from inspect_ai._eval.task.tasks import Tasks
from inspect_ai._util._async import Wake
from inspect_ai._util.error import EvalError, PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalSample,
    EvalSpec,
    read_eval_log,
)
from inspect_ai.log._log import EvalStatus
from inspect_ai.model import Model, get_model
from inspect_ai.model._model import ModelName
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    sandboxenv,
)
from inspect_ai.util._display import init_display_type


def _done(cache: SetupCache[Any], keys: list[str]) -> bool:
    """Whether every key has been set up."""
    return all(key in cache._jobs and cache._jobs[key].succeeded for key in keys)


def _task(name: str) -> Task:
    return Task(name=name, dataset=[Sample(input="x", target="y")])


def _resolve(names: list[str], models: list[Model]) -> list[ResolvedTask]:
    return [
        resolved
        for model in models
        for resolved in resolve_tasks(
            [_task(n) for n in names], {}, model, None, None, None
        )
    ]


def _label(task: ResolvedTask) -> str:
    return f"{task.task.name}@{str(task.model).split('/')[-1]}"


class FakeLogger:
    """The parts of `TaskLogger` the scheduling loop touches."""

    def __init__(self, label: str, attempt: int) -> None:
        self.label = label
        self.attempt = attempt
        self.eval = EvalSpec(
            created="2026-01-01T00:00:00+00:00",
            task=label,
            task_id=f"id-{label}",
            model="mockllm/model",
            dataset=EvalDataset(),
            config=EvalConfig(),
        )
        self.initialised = False
        self.finished = False
        self.discarded = 0
        self.destination_written = False
        self.location = ""
        self.recorder = SimpleNamespace(close_seed_source=self._close_seed_source)

    async def _close_seed_source(self, eval: EvalSpec) -> None:
        pass

    async def init(self) -> None:
        self.initialised = True
        self.location = f"{self.label}.eval"

    async def reinit(self) -> None:
        self.attempt += 1
        self.finished = False
        self.eval = self.eval.model_copy(
            update=dict(eval_id=f"{self.label}-{self.attempt}")
        )

    async def discard(self, **kwargs: Any) -> None:
        self.discarded += 1

    def header_log(self, error: EvalError) -> EvalLog:
        return EvalLog(eval=self.eval, status="error", error=error)


def _options_for(task: ResolvedTask) -> Callable[[TaskLogger], TaskRunOptions]:
    return lambda logger: _options(task, cast(FakeLogger, logger))


def _options(task: ResolvedTask, logger: FakeLogger) -> TaskRunOptions:
    return TaskRunOptions(
        task=task.task,
        model=task.model,
        model_roles=None,
        sandbox=None,
        checkpoint=None,
        eval_checkpoint=None,
        logger=cast(TaskLogger, logger),
        eval_wd=".",
    )


class Harness:
    """A dispatcher whose tasks are set up and run by script, recording what happens."""

    def __init__(
        self,
        models: list[Model],
        *,
        parallel: int = 1,
        retries: int = 0,
    ) -> None:
        self.parallel = parallel
        self.retries = retries
        self.events: list[str] = []
        self.loggers: dict[str, list[FakeLogger]] = {}
        self.finish: dict[str, anyio.Event] = {}
        self.started: dict[str, anyio.Event] = {}
        self.fail_next: set[str] = set()
        self.keys: dict[str, list[str]] = {}
        """Sandbox configs per task label (none by default)."""
        self.resolving: dict[str, anyio.Event] = {}
        self.resolve_errors: dict[str, Exception] = {}
        self.setup_release: dict[str, anyio.Event] = {}
        self.setup_errors: dict[str, Exception] = {}
        self.setup_began: dict[str, anyio.Event] = {}
        self.configured: list[list[str]] = []
        self.task_ids: dict[str, str] = {}
        self.queued_groups: list[list[str]] = []
        """The labels of each group of records queued, the seed's first."""

        def resolve(tasks: Tasks) -> list[ResolvedTask]:
            return [
                resolved
                for model in models
                for resolved in resolve_tasks(tasks, {}, model, None, None, None)
            ]

        self.tasks = _RecordingTasks(
            self,
            "run",
            resolve,
            self.configure,
            self.prepare,
            changed=Wake(),
            sequence_order=parallel == 1,
        )
        self.setups: SetupCache[str] = SetupCache(
            self.setup, on_done=self.tasks.changed.set
        )
        """Sets up sandbox configs (here plain strings) by script."""

    def configure(self, group: list[ResolvedTask]) -> list[ConfiguredTask]:
        for task in group:
            if task.task.name.startswith("invalid"):
                raise PrerequisiteError(f"invalid task {task.task.name}")
        self.configured.append([_label(t) for t in group])
        configured = []
        for task in group:
            label = _label(task)
            self.task_ids[label] = task.id
            self.loggers[label] = []
            self.finish[label] = anyio.Event()
            self.started[label] = anyio.Event()
            configured.append(
                ConfiguredTask(
                    task,
                    TaskSpec(label, ModelName(task.model), None),
                    _options_for(task),
                    functools.partial(self.new_logger, label),
                    functools.partial(lambda t: t.task.dataset, task),
                )
            )
        return configured

    async def prepare(self, configured: ConfiguredTask) -> tuple[str, ...]:
        """A task's sandbox configs, once ``resolving`` lets them be known."""
        label = _label(configured.resolved)
        self.events.append(f"resolve {label}")
        gate = self.resolving.get(label)
        if gate is not None:
            await gate.wait()
        error = self.resolve_errors.pop(label, None)
        if error is not None:
            raise error
        return tuple(self.keys.get(label, []))

    def new_logger(self, label: str) -> TaskLogger:
        logger = FakeLogger(label, len(self.loggers[label]) + 1)
        self.loggers[label].append(logger)
        return cast(TaskLogger, logger)

    def setup_began_event(self, key: str) -> anyio.Event:
        return self.setup_began.setdefault(key, anyio.Event())

    def finish_setup(self, key: str, error: Exception | None = None) -> None:
        if error is not None:
            self.setup_errors[key] = error
        self.setup_release.setdefault(key, anyio.Event()).set()

    async def setup(self, key: str) -> None:
        self.events.append(f"setup {key}")
        self.setup_began_event(key).set()
        await self.setup_release.setdefault(key, anyio.Event()).wait()
        del self.setup_release[key]
        self.setup_began.pop(key, None)
        error = self.setup_errors.pop(key, None)
        if error is not None:
            self.events.append(f"setup {key} failed")
            raise error
        self.events.append(f"setup {key} done")

    async def run_task(
        self,
        options: TaskRunOptions,
        *,
        retry: bool,
        can_retry: bool,
        on_log: Callable[[EvalLog], None] = lambda log: None,
    ) -> TaskRunResult:
        await open_log(options.logger, retry=retry)
        logger = cast(FakeLogger, options.logger)
        label = logger.label
        if task_retry_abandoned(self.task_ids[label]):
            # as task_run bails an attempt abandoned before it registers
            self.events.append(f"abandoned {label}")
            return TaskRunResult(None, None)
        if options.setup_failure is not None:
            self.events.append(f"failed {label}")
            logger.finished = True
            return TaskRunResult(
                EvalLog(
                    eval=logger.eval,
                    status="error",
                    error=EvalError(
                        message=str(options.setup_failure.error),
                        traceback="",
                        traceback_ansi="",
                    ),
                ),
                None,
            )
        self.events.append(f"start {label}")
        self.started[label].set()
        await self.finish[label].wait()
        self.finish[label] = anyio.Event()
        status: EvalStatus = "error" if label in self.fail_next else "success"
        self.fail_next.discard(label)
        self.events.append(f"end {label} {status}")
        logger.finished = True
        return TaskRunResult(EvalLog(eval=logger.eval, status=status), None)

    def dispatcher(self, source: TaskSource | None = None) -> TaskDispatcher:
        return TaskDispatcher(
            self.tasks,
            self.setups,
            lambda: None,
            parallel=self.parallel,
            retries=self.retries,
            next_tasks=source.next_tasks if source else None,
            debug_errors=False,
        )

    async def seed(self, tasks: list[ResolvedTask]) -> list[TaskRecord]:
        """Seed records, as after the seed start-up (no setups, loggers created)."""
        seed = await self.tasks.create(tasks)
        self.tasks.enqueue(seed)
        for record in seed:
            record.setup_keys = ()
            record.logger = self.new_logger(_labels([record])[0])
        return seed

    async def dispatch(
        self, seed: list[ResolvedTask], dispatcher: TaskDispatcher | None = None
    ) -> list[EvalLog]:
        """Queue the seed and run the loop (inside the setup cache)."""
        await self.seed(seed)
        return await (dispatcher or self.dispatcher()).run()

    async def run(
        self, seed: list[ResolvedTask], source: TaskSource | None = None
    ) -> list[EvalLog]:
        async with self.setups:
            return await self.dispatch(seed, self.dispatcher(source))


class _RecordingTasks(RunTasks):
    """Records each group of records queued."""

    def __init__(self, harness: Harness, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.harness = harness

    @override
    def enqueue(self, records: list[TaskRecord]) -> None:
        self.harness.queued_groups.append(_labels(records))
        super().enqueue(records)

    @override
    def enqueue_ahead(self, records: list[TaskRecord]) -> None:
        self.harness.queued_groups.append(_labels(records))
        super().enqueue_ahead(records)


def _labels(records: list[TaskRecord]) -> list[str]:
    return [f"{r.task}@{str(r.model).split('/')[-1]}" for r in records]


@pytest.fixture(autouse=True)
def _setup() -> Any:
    init_display_type("none")
    yield
    reset_max_tasks_override()


def _install(monkeypatch: pytest.MonkeyPatch, harness: Harness) -> None:
    monkeypatch.setattr("inspect_ai._eval.run._run_task", harness.run_task)


async def _wait_until(predicate: Callable[[], bool]) -> None:
    with anyio.fail_after(10):
        while not predicate():
            await anyio.sleep(0)


async def _wait_started(harness: Harness, *labels: str) -> None:
    with anyio.fail_after(10):
        for label in labels:
            # a task added mid-run has no event until it is configured
            while label not in harness.started:
                await anyio.sleep(0)
            await harness.started[label].wait()


async def _wait_stats(in_flight: int, pending: int) -> None:
    # the loop's state is published through the dispatcher stats; poll it
    # (each iteration yields to the loop)
    await _wait_until(
        lambda: (stats := task_dispatcher_stats()) is not None
        and (stats.in_flight, stats.pending) == (in_flight, pending)
    )


def _starts(harness: Harness) -> list[str]:
    return [e.split()[1] for e in harness.events if e.startswith("start")]


# ------------------------------------------------------------- settings


def test_task_overridable_settings_exist_on_task_and_eval_config() -> None:
    # TaskSettings resolves these by name (getattr/setattr)
    task = Task(dataset=[Sample(input="x")])
    for name in _TASK_OVERRIDABLE:
        assert name in EvalConfig.model_fields
        assert hasattr(task, name)


# ------------------------------------------------------------- RunTasks


async def test_run_tasks_queue_added_tasks_in_the_order_added() -> None:
    harness = Harness([get_model("mockllm/m1")])
    run_tasks = harness.tasks
    await run_tasks.add([_task("a")])
    await run_tasks.add([_task("w1"), _task("w2")])
    assert run_tasks.changed._event.is_set()
    assert _labels(run_tasks.queued) == ["a@m1", "w1@m1", "w2@m1"]
    assert run_tasks.records == run_tasks.queued


async def test_run_tasks_add_ahead_queues_and_lists_ahead_of_the_queued() -> None:
    harness = Harness([get_model("mockllm/m1")], parallel=2)
    run_tasks = harness.tasks
    [started] = await run_tasks.add([_task("a")])
    run_tasks.start(started)
    await run_tasks.add([_task("w1"), _task("w2")])
    await run_tasks.add_ahead([_task("b1"), _task("b2")])
    assert _labels(run_tasks.queued) == ["b1@m1", "b2@m1", "w1@m1", "w2@m1"]
    assert _labels(run_tasks.records) == ["a@m1", "b1@m1", "b2@m1", "w1@m1", "w2@m1"]


async def test_run_tasks_add_creates_records_and_raises_on_invalid_tasks() -> None:
    harness = Harness([get_model("mockllm/m1")])
    [record] = await harness.tasks.add([_task("a")])
    assert record.configured is not None
    # configured as it is added, so an invalid task raises to whoever added
    # it, and no task of that call is queued
    with pytest.raises(PrerequisiteError, match="invalid task invalid_b"):
        await harness.tasks.add([_task("c"), _task("invalid_b")])
    assert _labels(harness.tasks.queued) == ["a@m1"]


async def test_run_tasks_close_refuses_add_and_ends_unstarted() -> None:
    m1 = get_model("mockllm/m1")
    resolved: list[Tasks] = []
    harness = Harness([m1])

    def resolve(tasks: Tasks) -> list[ResolvedTask]:
        resolved.append(tasks)
        return _resolve(["x"], [m1])

    run_tasks = RunTasks(
        "run",
        resolve,
        harness.configure,
        harness.prepare,
        changed=Wake(),
        sequence_order=False,
    )
    [added] = await run_tasks.add([_task("w")])
    [queued] = await run_tasks.create(_resolve(["ready"], [m1]))
    run_tasks.enqueue([queued])
    run_tasks.close()
    assert run_tasks.queued == [] and added.ended and queued.ended
    with pytest.raises(RuntimeError, match="run 'run' has finished dispatching"):
        await run_tasks.add([_task("late")])


async def test_record_state_follows_the_record() -> None:
    m1 = get_model("mockllm/m1")
    run_tasks = Harness([m1]).tasks
    [queued] = await run_tasks.add([_task("q")])
    [started] = await run_tasks.add([_task("s")])
    run_tasks.start(started)
    records = [queued, started]
    assert [run_tasks.state(r) for r in records] == ["queued", "running"]
    run_tasks.close()
    assert [run_tasks.state(r) for r in records] == ["ended", "ended"]


async def test_record_drops_its_task_when_it_ends() -> None:
    harness = Harness([get_model("mockllm/m1")])
    [record] = await harness.tasks.add([_task("a")])
    task = weakref.ref(cast(ConfiguredTask, record.configured).resolved.task)
    harness.tasks.queued.remove(record)
    harness.tasks.end(record)
    gc.collect()
    assert record.configured is None
    assert record.ended and record.log is None
    assert task() is None


# ------------------------------------------------------------- pick and retry


async def _records(labels: list[tuple[str, Model]]) -> list[TaskRecord]:
    harness = Harness([])
    return [
        (await harness.tasks.create(_resolve([name], [model])))[0]
        for name, model in labels
    ]


async def test_earliest_of_least_busy_model_then_queue_order() -> None:
    m1, m2 = get_model("mockllm/m1"), get_model("mockllm/m2")
    harness = Harness([m1], parallel=2)
    dispatcher = harness.dispatcher()
    queued = await harness.seed(_resolve(["a", "b"], [m1]) + _resolve(["c", "d"], [m2]))
    for record in queued:
        record.setups = []
    assert dispatcher.earliest_of_least_busy_model() is queued[0]
    harness.tasks.start(queued[0])
    assert dispatcher.earliest_of_least_busy_model() is queued[2]
    harness.tasks.start(queued[2])
    assert dispatcher.earliest_of_least_busy_model() is queued[1]
    # a record whose setups are not done is not prepared
    queued[1].setups = None
    queued[3].setups = None
    assert dispatcher.earliest_of_least_busy_model() is None


@pytest.mark.parametrize(
    "cancel_type,status,retries,expected",
    [
        (None, "error", 1, True),
        (None, "error", 0, False),
        (None, "success", 1, False),
        ("retry", "error", 1, True),
        ("retry", "success", 1, True),
        ("retry", "error", 0, False),
        ("abort", "error", 1, False),
        ("drain", "error", 1, False),
        ("score", "error", 1, False),
        ("error", "error", 1, False),
        # the run was cancelled
        ("retry", "cancelled", 1, False),
    ],
)
async def test_wants_retry(
    cancel_type: CancelType, status: EvalStatus, retries: int, expected: bool
) -> None:
    [record] = await _records([("a", get_model("mockllm/m1"))])
    task_log = EvalLog(eval=FakeLogger("a", 1).eval, status=status)
    assert wants_retry(cancel_type, task_log, record, retries) is expected


async def test_wants_retry_not_after_operator_abandoned_it() -> None:
    [record] = await _records([("a", get_model("mockllm/m1"))])
    abandon_task_retry(record.task_id)
    try:
        task_log = EvalLog(eval=FakeLogger("a", 1).eval, status="error")
        assert not wants_retry(None, task_log, record, 1)
    finally:
        reset_retry_abandoned()


# ------------------------------------------------------------- the idle rule


class _ScriptedSource(TaskSource):
    """``next_tasks()`` returns the scripted batches in order; one call too many raises."""

    def __init__(self, batches: list[list[str] | None]) -> None:
        self.batches = list(batches)

    async def next_tasks(self) -> list[Task] | None:
        batch = self.batches.pop(0)
        return None if batch is None else [_task(n) for n in batch]


@pytest.mark.parametrize(
    "source,idle_groups",
    [
        # the source is asked until it returns None
        ([["s1", "s2"], ["s3"], None], [["s1", "s2"], ["s3"]]),
        # an empty batch ends the source
        ([[]], []),
        # without a source there is nothing to add
        (None, []),
    ],
)
async def test_dispatcher_idle_rule(
    source: list[list[str] | None] | None, idle_groups: list[list[str]]
) -> None:
    # the loop's side of the tasks, without running any: add_tasks_from_source
    # adds the source's next batch until it returns nothing
    scripted = None if source is None else _ScriptedSource(source)
    harness = Harness([get_model("mockllm/m1")], parallel=2)
    dispatcher = harness.dispatcher(scripted)
    while await dispatcher.add_tasks_from_source():
        pass

    groups = [[label.split("@")[0] for label in g] for g in harness.queued_groups]
    assert groups == idle_groups
    # every scripted batch was asked for, and none beyond (a further call raises)
    assert scripted is None or scripted.batches == []


async def test_dispatcher_runs_tasks_added_during_final_next_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # next_tasks() blocks; a task added meanwhile is queued, so the run goes
    # on once it returns None, and the ended source is never asked again
    entered = anyio.Event()
    release = anyio.Event()

    class BlockingSource(TaskSource):
        calls = 0

        async def next_tasks(self) -> list[Task] | None:
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("next_tasks() called after it returned None")
            entered.set()
            await release.wait()
            return None

    m1 = get_model("mockllm/m1")
    source = BlockingSource()
    harness = Harness([m1], parallel=2)
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        harness.finish["a@m1"].set()
        await entered.wait()
        await harness.tasks.add([_task("w")])
        release.set()
        await _wait_started(harness, "w@m1")
        harness.finish["w@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]), source)

    assert [log.eval.task for log in logs] == ["a@m1", "w@m1"]
    assert source.calls == 1
    with pytest.raises(RuntimeError, match="finished dispatching"):
        await harness.tasks.add([_task("late")])


# ------------------------------------------------------------- the loop


async def test_loop_balances_models(monkeypatch: pytest.MonkeyPatch) -> None:
    m1, m2 = get_model("mockllm/m1"), get_model("mockllm/m2")
    harness = Harness([m1, m2], parallel=2)
    _install(monkeypatch, harness)

    async def drive() -> None:
        # the least-used model goes first: c@m2 starts before b@m1
        await _wait_started(harness, "a@m1", "c@m2")
        await _wait_stats(in_flight=2, pending=1)
        harness.finish["a@m1"].set()
        await _wait_started(harness, "b@m1")
        harness.finish["c@m2"].set()
        harness.finish["b@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a", "b"], [m1]) + _resolve(["c"], [m2]))

    assert set(_starts(harness)[:2]) == {"a@m1", "c@m2"}
    assert [log.eval.task for log in logs] == ["a@m1", "b@m1", "c@m2"]


async def test_loop_sequence_order_at_launch_limit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1, m2 = get_model("mockllm/m1"), get_model("mockllm/m2")
    harness = Harness([m1, m2], parallel=1)
    _install(monkeypatch, harness)
    order = ["a@m1", "a@m2", "b@m1", "b@m2", "c@m1", "c@m2", "d@m1", "d@m2"]

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await harness.tasks.add([_task("c"), _task("d")])
        for label in order:
            await _wait_started(harness, label)
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await harness.run(_resolve(["a", "b"], [m1, m2]))

    assert _starts(harness) == order


async def test_loop_reads_max_tasks_live(monkeypatch: pytest.MonkeyPatch) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await _wait_stats(in_flight=1, pending=2)
        set_max_tasks_override(3)
        # raising the limit starts the queued tasks while `a` still runs
        await _wait_started(harness, "b@m1", "c@m1")
        await _wait_stats(in_flight=3, pending=0)
        # lowering never preempts: all three keep running
        set_max_tasks_override(1)
        for label in ("a@m1", "b@m1", "c@m1"):
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a", "b", "c"], [m1]))

    assert [log.status for log in logs] == ["success"] * 3


async def test_retry_runs_in_its_slot_and_reinitialises_its_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a's retry starts in a's slot as its first attempt ends, ahead of b and
    # of c, added while a ran
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1, retries=1)
    _install(monkeypatch, harness)
    harness.fail_next.add("a@m1")

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await harness.tasks.add([_task("c")])
        harness.started["a@m1"] = anyio.Event()
        harness.finish["a@m1"].set()
        await _wait_started(harness, "a@m1")
        await _wait_stats(in_flight=1, pending=2)
        harness.finish["a@m1"].set()
        for label in ("b@m1", "c@m1"):
            await _wait_started(harness, label)
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a", "b"], [m1]))

    assert _starts(harness) == ["a@m1", "a@m1", "b@m1", "c@m1"]
    # the retry reinitialised the failed attempt's logger; the added task's
    # logger was made when it started
    assert [lg.attempt for lg in harness.loggers["a@m1"]] == [2]
    assert harness.loggers["c@m1"][0].initialised
    # the retry's log replaces the failed attempt's, in the task's position
    assert [(log.eval.task, log.status) for log in logs] == [
        ("a@m1", "success"),
        ("b@m1", "success"),
        ("c@m1", "success"),
    ]


async def test_retry_starts_before_tasks_its_failed_attempt_added(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a failing attempt adds a follow-up as it ends (as TaskSource.task_complete
    # does): the retry keeps the slot, so it runs before the follow-up
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1, retries=1)
    _install(monkeypatch, harness)
    harness.fail_next.add("a@m1")
    run_task = harness.run_task

    async def adding_run_task(
        options: TaskRunOptions, *, retry: bool, can_retry: bool, **kwargs: Any
    ) -> TaskRunResult:
        result = await run_task(options, retry=retry, can_retry=can_retry)
        if result.log is not None and result.log.status == "error":
            await harness.tasks.add([_task("f")])
        return result

    monkeypatch.setattr("inspect_ai._eval.run._run_task", adding_run_task)

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        harness.started["a@m1"] = anyio.Event()
        harness.finish["a@m1"].set()
        await _wait_started(harness, "a@m1")
        harness.finish["a@m1"].set()
        await _wait_started(harness, "f@m1")
        harness.finish["f@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await harness.run(_resolve(["a"], [m1]))
    assert _starts(harness) == ["a@m1", "a@m1", "f@m1"]


async def test_retry_waits_while_its_task_is_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a pause holds a retry back, as it holds a queued task
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1, retries=1)
    _install(monkeypatch, harness)
    harness.fail_next.add("a@m1")

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        task_id = harness.tasks.records[0].task_id
        _task_gate(task_id).pause()
        harness.started["a@m1"] = anyio.Event()
        harness.finish["a@m1"].set()
        await _wait_until(lambda: "end a@m1 error" in harness.events)
        for _ in range(10):
            await anyio.sleep(0)
        assert not harness.started["a@m1"].is_set()
        _task_gate(task_id).resume()
        await _wait_started(harness, "a@m1")
        harness.finish["a@m1"].set()

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(drive)
            logs = await harness.run(_resolve(["a"], [m1]))
    finally:
        reset_task_pause_gates()
    assert [(log.eval.task, log.status) for log in logs] == [("a@m1", "success")]


async def test_loop_asks_source_only_when_idle_until_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2)
    _install(monkeypatch, harness)
    calls: list[list[str]] = []

    class Source(TaskSource):
        async def next_tasks(self) -> list[Task] | None:
            calls.append([e for e in harness.events if not e.startswith("resolve")])
            if len(calls) == 1:
                # added while next_tasks() runs: queued behind its batch
                await harness.tasks.add([_task("late")])
                return [_task("n1"), _task("n2")]
            return None

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        harness.finish["a@m1"].set()
        await _wait_started(harness, "n1@m1", "n2@m1")
        harness.finish["n1@m1"].set()
        await _wait_started(harness, "late@m1")
        harness.finish["n2@m1"].set()
        harness.finish["late@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]), Source())

    # asked only when nothing was queued or running; not again after None
    assert len(calls) == 2
    assert calls[0] == ["start a@m1", "end a@m1 success"]
    # the batch was queued whole, when the call returned
    assert harness.queued_groups == [["a@m1"], ["late@m1"], ["n1@m1", "n2@m1"]]
    assert [log.eval.task for log in logs] == ["a@m1", "n1@m1", "n2@m1", "late@m1"]
    with pytest.raises(RuntimeError, match="finished dispatching"):
        await harness.tasks.add([_task("after_end")])


async def test_stats_count_queued_tasks_as_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await harness.tasks.add([_task("b")])
        await _wait_stats(in_flight=1, pending=1)
        await harness.tasks.add([_task("c"), _task("d")])
        await _wait_stats(in_flight=1, pending=3)
        for label in ("a@m1", "b@m1", "c@m1", "d@m1"):
            await _wait_started(harness, label)
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]))
    assert [log.eval.task for log in logs] == ["a@m1", "b@m1", "c@m1", "d@m1"]


# ------------------------------------------------------------- sandbox setups


async def test_ready_task_starts_while_an_older_tasks_setup_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the head-of-line case: `boxed` was added first, but its setup is still
    # running, so `plain` (nothing to set up) takes the free slot
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2)
    _install(monkeypatch, harness)
    harness.keys["boxed@m1"] = ["image"]

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await harness.tasks.add([_task("boxed")])
        await harness.tasks.add([_task("plain")])
        await harness.setup_began_event("image").wait()
        await _wait_started(harness, "plain@m1")
        harness.finish_setup("image")
        harness.finish["plain@m1"].set()
        await _wait_started(harness, "boxed@m1")
        harness.finish["boxed@m1"].set()
        harness.finish["a@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]))

    assert harness.events.index("start plain@m1") < harness.events.index(
        "setup image done"
    )
    assert _starts(harness) == ["a@m1", "plain@m1", "boxed@m1"]
    # logs keep the order the tasks were added in
    assert [log.eval.task for log in logs] == ["a@m1", "boxed@m1", "plain@m1"]


async def test_tasks_on_a_config_set_up_earlier_start_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=3)
    _install(monkeypatch, harness)
    harness.keys["b@m1"] = ["image"]
    harness.keys["c@m1"] = ["image"]
    harness.keys["d@m1"] = ["other"]

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await harness.tasks.add([_task("b")])
        await harness.setup_began_event("image").wait()
        harness.finish_setup("image")
        await _wait_started(harness, "b@m1")
        await harness.tasks.add([_task("d"), _task("c")])
        # c reuses b's setup; d waits for its own
        await _wait_started(harness, "c@m1")
        await harness.setup_began_event("other").wait()
        harness.finish_setup("other")
        for label in ("a@m1", "d@m1", "b@m1", "c@m1"):
            await _wait_started(harness, label)
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await harness.run(_resolve(["a"], [m1]))
    assert [e for e in harness.events if e.startswith("setup")].count(
        "setup image"
    ) == 1


async def test_failed_setup_ends_its_waiters_then_their_retry_sets_up_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # b and c wait for the same setup; when it fails both attempts end with
    # it, and their retries, in their slots, share one new setup
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=3, retries=1)
    _install(monkeypatch, harness)
    harness.keys["b@m1"] = ["image"]
    harness.keys["c@m1"] = ["image"]

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await harness.tasks.add([_task("b"), _task("c")])
        await harness.setup_began_event("image").wait()
        harness.finish_setup("image", RuntimeError("pull failed"))
        # both waiters fail at once
        await _wait_until(lambda: harness.events.count("failed c@m1") == 1)
        assert harness.events.count("failed b@m1") == 1
        await harness.setup_began_event("image").wait()
        harness.finish_setup("image")
        harness.finish["a@m1"].set()
        for label in ("b@m1", "c@m1"):
            await _wait_started(harness, label)
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]))

    # one setup for both waiters, forgotten when it failed, one for the retries
    assert [e for e in harness.events if e.startswith("setup image")] == [
        "setup image",
        "setup image failed",
        "setup image",
        "setup image done",
    ]
    assert [(log.eval.task, log.status) for log in logs] == [
        ("a@m1", "success"),
        ("b@m1", "success"),
        ("c@m1", "success"),
    ]


async def test_retry_sets_up_its_failed_config_ahead_of_waiting_setups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a's setup X fails while n's Y and m's Z wait; the worker moves on to Y,
    # and a's retry sets X up again ahead of Z
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=4, retries=1)
    _install(monkeypatch, harness)
    for name, key in (("a", "X"), ("n", "Y"), ("m", "Z")):
        harness.keys[f"{name}@m1"] = [key]

    async def drive() -> None:
        await _wait_started(harness, "s@m1")
        await harness.tasks.add([_task("a"), _task("n"), _task("m")])
        await harness.setup_began_event("X").wait()
        harness.finish_setup("X", RuntimeError("pull failed"))
        await harness.setup_began_event("Y").wait()
        await _wait_until(lambda: "X" in harness.setups._jobs)
        for key in ("Y", "X", "Z"):
            harness.finish_setup(key)
        for label in ("a@m1", "n@m1", "m@m1"):
            harness.finish[label].set()
        await _wait_until(
            lambda: {f"end {label}@m1 success" for label in "anm"}
            <= set(harness.events)
        )
        harness.finish["s@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await harness.run(_resolve(["s"], [m1]))
    setups = [e.split()[1] for e in harness.events if e.startswith("setup ")]
    assert setups[::2] == ["X", "Y", "X", "Z"]


async def test_failed_resolution_raises_to_whoever_adds_the_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # b's sandbox configs can't be resolved: neither b nor c, added with it,
    # is queued, and the run goes on
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2)
    _install(monkeypatch, harness)
    harness.resolve_errors["b@m1"] = ValueError("bad compose file")

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        with pytest.raises(ValueError, match="bad compose file"):
            await harness.tasks.add([_task("b"), _task("c")])
        harness.finish["a@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]))
    assert [(log.eval.task, log.status) for log in logs] == [("a@m1", "success")]
    assert _starts(harness) == ["a@m1"]


async def test_only_the_front_of_the_queue_is_set_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the front of the queue is the first max_tasks queued tasks: with a and b
    # in the two slots, t1 and t2 set up (one at a time, in queue order) and t3
    # waits until t1 starts; raising max_tasks widens the front at once
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2)
    _install(monkeypatch, harness)
    names = ["t1", "t2", "t3", "t4"]
    for name in names:
        harness.keys[f"{name}@m1"] = [name]

    def requested() -> list[str]:
        return sorted(cast(dict[str, Any], harness.setups._jobs))

    async def drive() -> None:
        await _wait_started(harness, "a@m1", "b@m1")
        await harness.tasks.add([_task(n) for n in names])
        for name in ["t1", "t2"]:
            await harness.setup_began_event(name).wait()
            harness.finish_setup(name)
        await _wait_until(lambda: _done(harness.setups, ["t1", "t2"]))
        assert requested() == ["t1", "t2"]
        harness.finish["a@m1"].set()
        await _wait_started(harness, "t1@m1")
        await harness.setup_began_event("t3").wait()
        assert requested() == ["t1", "t2", "t3"]
        set_max_tasks_override(3)
        await _wait_until(lambda: requested() == names)
        reset_max_tasks_override()
        harness.finish_setup("t3")
        await harness.setup_began_event("t4").wait()
        harness.finish_setup("t4")
        # one at a time, so each start has a cycle of its own
        for label in ("b@m1", "t1@m1", "t2@m1", "t3@m1", "t4@m1"):
            await _wait_started(harness, label)
            harness.finish[label].set()
            await _wait_until(
                functools.partial(contains, harness.events, f"end {label} success")
            )

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await harness.run(_resolve(["a", "b"], [m1]))
    assert [
        e for e in harness.events if e.startswith("setup") and e.endswith("done")
    ] == [f"setup {name} done" for name in names]
    # (a and b start in the same cycle, in either order)
    assert _starts(harness)[2:] == ["t1@m1", "t2@m1", "t3@m1", "t4@m1"]


async def test_task_behind_the_front_joins_setups_already_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # at max_tasks 1, `shared` is behind the front (`first` fills it) but
    # its config's job exists, so it holds it, and `plain` (no sandbox)
    # starts in the free slot while `first`'s setup runs
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)
    harness.keys["first@m1"] = ["image"]
    harness.keys["shared@m1"] = ["image"]
    harness.keys["other@m1"] = ["other"]

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        await harness.tasks.add(
            [_task("first"), _task("other"), _task("shared"), _task("plain")],
        )
        await harness.setup_began_event("image").wait()
        harness.finish["a@m1"].set()
        await _wait_started(harness, "plain@m1")
        jobs = cast(dict[str, Any], harness.setups._jobs)
        assert sorted(jobs) == ["image"]
        harness.finish_setup("image")
        harness.finish["plain@m1"].set()
        for label in ("first@m1", "shared@m1"):
            await _wait_started(harness, label)
            harness.finish[label].set()
        await harness.setup_began_event("other").wait()
        harness.finish_setup("other")
        await _wait_started(harness, "other@m1")
        harness.finish["other@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await harness.run(_resolve(["a"], [m1]))
    assert _starts(harness) == ["a@m1", "plain@m1", "first@m1", "shared@m1", "other@m1"]


@pytest.mark.parametrize("directive", [abandon_task_retry, cancel_task, drain_task])
async def test_abandoning_a_retry_between_attempts_keeps_the_failed_attempts_log(
    monkeypatch: pytest.MonkeyPatch, directive: Callable[[str], Any]
) -> None:
    # a's setup fails, and its retry waits in a's slot for the setup to run
    # again; a cancel or drain then abandons the retry. The harness's attempts
    # never register an EvalState, as an attempt whose log_start write
    # failed doesn't, so the directives find the task by its record
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2, retries=2)
    _install(monkeypatch, harness)
    harness.keys["a@m1"] = ["X"]
    results: list[Any] = []

    async def drive() -> None:
        await _wait_started(harness, "s@m1")
        [a] = await harness.tasks.add([_task("a")])
        await harness.setup_began_event("X").wait()
        harness.finish_setup("X", RuntimeError("pull failed"))
        await _wait_until(lambda: "failed a@m1" in harness.events)
        await harness.setup_began_event("X").wait()
        results.append(directive(a.task_id))
        harness.finish_setup("X")
        await _wait_until(lambda: a.ended)
        harness.finish["s@m1"].set()

    token = register_run_tasks(harness.tasks)
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(drive)
            logs = await harness.run(_resolve(["s"], [m1]))
    finally:
        clear_run_tasks(token)
        reset_retry_abandoned()
    if directive is not abandon_task_retry:
        assert results[0] is not None and results[0]["changed"]
        assert results[0].get("retry_abandoned")
    assert _starts(harness) == ["s@m1"]
    assert harness.events.count("failed a@m1") == 1
    assert [(log.eval.task, log.status) for log in logs] == [
        ("s@m1", "success"),
        ("a@m1", "error"),
    ]


def _not_started(record: TaskRecord) -> dict[str, Any]:
    """The fields of a cancel's reply for a task that has not started."""
    return {
        "ok": True,
        "task_id": record.task_id,
        "task": record.task,
        "eval_id": "",
        "dry_run": False,
        "in_flight": 0,
        "action": "cancel",
    }


async def test_tasks_cancelled_before_they_start_leave_the_display_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the display counts every queued task; a cancel ends one waiting to start
    # at once, and as it has no row, it leaves the count
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)
    counts: list[int] = []
    shown = display

    class Display:
        def __getattr__(self, name: str) -> Any:
            return getattr(shown(), name)

        def update_task_count(self, n: int) -> None:
            counts.append(n)

    monkeypatch.setattr("inspect_ai._eval.run.display", Display)
    monkeypatch.setattr("inspect_ai._eval.task.enqueue.display", Display)

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        [c] = await harness.tasks.add([_task("c")])
        for record in list(harness.tasks.queued):
            assert cancel_task(record.task_id) == {
                **_not_started(record),
                "changed": True,
                "not_started": True,
            }
            assert record.ended
        assert cancel_task(c.task_id) == {
            **_not_started(c),
            "changed": False,
            "reason": "task ended before it started",
        }
        harness.finish["a@m1"].set()

    token = register_run_tasks(harness.tasks)
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(drive)
            logs = await harness.run(_resolve(["a", "b"], [m1]))
    finally:
        clear_run_tasks(token)
    assert [(log.eval.task, log.status) for log in logs] == [("a@m1", "success")]
    # the seed's two rows, then c added, then b and c cancelled
    assert counts == [2, 1, -1, -1]


async def test_finished_added_task_is_released_while_the_run_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2)
    _install(monkeypatch, harness)
    refs: list[weakref.ref[Task]] = []

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        [b] = await harness.tasks.add([_task("b")])
        refs.append(weakref.ref(cast(ConfiguredTask, b.configured).resolved.task))
        del b
        await _wait_started(harness, "b@m1")
        harness.finish["b@m1"].set()
        await _wait_until(lambda: harness.tasks.records[1].configured is None)
        gc.collect()
        assert refs[0]() is None
        harness.finish["a@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await harness.run(_resolve(["a"], [m1]))


# ------------------------------------------------------------- cancellation


@pytest.mark.parametrize("during", ["setup", "resolution", "next_tasks"])
async def test_loop_cancel_while_readying_added_tasks_is_absorbed(
    monkeypatch: pytest.MonkeyPatch, during: str
) -> None:
    # a cancellation of the run while an added task is still being readied,
    # or while the loop awaits next_tasks(), returns the logs written so far,
    # as a cancellation anywhere else does; the running task's logger is
    # released and the unstarted task ends without a log
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)
    blocked = anyio.Event()
    harness.keys["c@m1"] = ["image"]
    if during == "resolution":
        harness.resolving["c@m1"] = anyio.Event()

    class Source(TaskSource):
        async def next_tasks(self) -> list[Task] | None:
            blocked.set()
            await anyio.sleep_forever()
            return None

    dispatcher = harness.dispatcher(Source() if during == "next_tasks" else None)
    returned: list[Any] = []
    with anyio.fail_after(10):
        with anyio.CancelScope() as scope:
            async with harness.setups, anyio.create_task_group() as tg:

                async def cancel_when_blocked() -> None:
                    await _wait_started(harness, "a@m1")
                    if during == "next_tasks":
                        harness.finish["a@m1"].set()
                        await blocked.wait()
                    elif during == "setup":
                        await harness.tasks.add([_task("c")])
                        await harness.setup_began_event("image").wait()
                    else:
                        tg.start_soon(harness.tasks.add, [_task("c")])
                        await _wait_until(lambda: "resolve c@m1" in harness.events)
                    scope.cancel()

                tg.start_soon(cancel_when_blocked)
                returned.append(
                    await harness.dispatch(_resolve(["a"], [m1]), dispatcher)
                )

    # a finished before next_tasks() was asked; otherwise it was running
    assert [log.eval.task for log in returned[0]] == (
        ["a@m1"] if during == "next_tasks" else []
    )
    assert all(record.ended for record in harness.tasks.records)
    assert _starts(harness) == ["a@m1"]
    assert harness.loggers["a@m1"][0].discarded == (0 if during == "next_tasks" else 1)
    assert task_dispatcher_stats() is None
    with pytest.raises(RuntimeError, match="finished dispatching"):
        await harness.tasks.add([_task("late")])


async def test_loop_cancel_while_tasks_run_or_wait_for_a_slot_is_absorbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)
    harness.keys["c@m1"] = ["image"]
    with anyio.fail_after(10):
        with anyio.CancelScope() as scope:
            async with harness.setups, anyio.create_task_group() as tg:

                async def cancel_when_running() -> None:
                    await _wait_started(harness, "a@m1")
                    # an added task set up and waiting for a slot does not
                    # stop the run from returning
                    await harness.tasks.add([_task("c")])
                    await harness.setup_began_event("image").wait()
                    harness.finish_setup("image")
                    await _wait_until(lambda: _done(harness.setups, ["image"]))
                    scope.cancel()

                tg.start_soon(cancel_when_running)
                logs = await harness.dispatch(_resolve(["a"], [m1]))
                # the task screen absorbs it: the run returns what it has
                assert logs == []
    # the running task's logger is released, the queued task never made one,
    # and every record has ended
    assert harness.loggers["a@m1"][0].discarded == 1
    assert harness.loggers["c@m1"] == []
    assert all(record.ended for record in harness.tasks.records)
    assert task_dispatcher_stats() is None


async def test_cancel_during_task_complete_keeps_the_written_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the task's log is written before TaskSource.task_complete runs, so a
    # cancellation of the run while the callback awaits still returns it
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    notified = anyio.Event()

    async def task_run(options: TaskRunOptions, task_cancel: Any) -> EvalLog:
        cast(FakeLogger, options.logger).finished = True
        return EvalLog(eval=options.logger.eval, status="success")

    async def notify_task_source(options: TaskRunOptions, eval_log: EvalLog) -> None:
        notified.set()
        await anyio.sleep_forever()

    monkeypatch.setattr("inspect_ai._eval.run.task_run", task_run)
    monkeypatch.setattr("inspect_ai._eval.run.notify_task_source", notify_task_source)
    returned: list[list[EvalLog]] = []
    with anyio.fail_after(10):
        with anyio.CancelScope() as scope:
            async with harness.setups, anyio.create_task_group() as tg:

                async def cancel_when_notified() -> None:
                    await notified.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_notified)
                returned.append(await harness.dispatch(_resolve(["a"], [m1])))
    assert [(log.eval.task, log.status) for log in returned[0]] == [("a@m1", "success")]


async def test_queued_seed_task_logger_is_never_initialised_when_the_run_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)
    with anyio.fail_after(10):
        with anyio.CancelScope() as scope:
            async with harness.setups, anyio.create_task_group() as tg:

                async def cancel_when_running() -> None:
                    await _wait_started(harness, "a@m1")
                    scope.cancel()

                tg.start_soon(cancel_when_running)
                await harness.dispatch(_resolve(["a", "b"], [m1]))
    # a seed logger is initialised as its task starts, so b's holds nothing
    [b_logger] = harness.loggers["b@m1"]
    assert not b_logger.initialised and b_logger.discarded == 0


# ------------------------------------------------------------- end to end

# what the box sandbox's task_init does, set per test
_box_init: dict[str, Any] = {}


@sandboxenv(name="task_dispatch_box")
class _Box(SandboxEnvironment):
    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        _box_init.setdefault("configs", []).append(config)
        hook = _box_init.get("task_init")
        if hook is not None:
            await hook()

    @override
    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        # set process-wide while task_init runs
        return dict(_box_init.get("env", {}))

    @override
    @classmethod
    def default_concurrency(cls) -> int | None:
        return 10

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        return {"default": _Box()}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        raise NotImplementedError

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        raise NotImplementedError

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _reset_box() -> Any:
    _box_init.clear()
    yield
    _box_init.clear()


@solver
def record(events: list[str], name: str) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        events.append(name)
        return state

    return solve


@solver
def record_and_set(events: list[str], name: str, ran: anyio.Event) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        events.append(name)
        ran.set()
        return state

    return solve


def _plain(name: str, events: list[str]) -> Task:
    return Task(name=name, dataset=[Sample(input="x")], solver=[record(events, name)])


def _boxed(name: str, events: list[str]) -> Task:
    return Task(
        name=name,
        dataset=[Sample(input="x")],
        solver=[record(events, name)],
        sandbox="task_dispatch_box",
    )


async def _init_waiting_for(sample_ran: anyio.Event, events: list[str]) -> None:
    # a negative check: task_init waits (bounded) for a sibling's sample, which
    # may only run once the group's start-up is done; reaching the bound is the
    # passing path
    events.append("init start")
    with anyio.move_on_after(2):
        await sample_ran.wait()
    events.append("init end")


_GROUP_RUNS = ["next_tasks", "enqueued", "final_next_tasks"]


def _group_run(how: str, group: list[Task]) -> Any:
    """A run in which ``group`` becomes ready together.

    ``next_tasks``: a TaskSource batch. ``enqueued``: added by the running
    seed. ``final_next_tasks``: added by a ``next_tasks()`` that then ends the
    source.
    """
    if how in ("next_tasks", "final_next_tasks"):

        class Source(TaskSource):
            calls = 0

            def initial_tasks(self) -> list[Task]:
                return [_plain("seed", [])]

            async def next_tasks(self) -> list[Task] | None:
                self.calls += 1
                if self.calls > 1:
                    return None
                if how == "next_tasks":
                    return group
                await enqueue_task(group)
                return None

        return Source()

    @solver
    def add_group() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await enqueue_task(group)
            return state

        return solve

    return Task(name="seed", dataset=[Sample(input="x")], solver=[add_group()])


@pytest.mark.parametrize("max_tasks", [1, 2])
def test_seed_sandbox_startup_failure_fails_before_any_task_runs(
    tmp_path: Path, max_tasks: int
) -> None:
    async def fail() -> None:
        raise PrerequisiteError("sandbox prerequisite missing")

    _box_init["task_init"] = fail
    events: list[str] = []
    with pytest.raises(PrerequisiteError, match="sandbox prerequisite missing"):
        eval(
            [_plain("a", events), _boxed("b", events)],
            model="mockllm/model",
            max_tasks=max_tasks,
            display="none",
            log_dir=str(tmp_path),
        )
    assert events == []
    assert list(tmp_path.glob("*.eval")) == []


def test_seed_configs_are_set_up_in_queue_and_sample_order(tmp_path: Path) -> None:
    def boxed(name: str, configs: list[str]) -> Task:
        return Task(
            name=name,
            dataset=[
                Sample(input="x", sandbox=("task_dispatch_box", config))
                for config in configs
            ],
        )

    eval(
        [boxed("a", ["c3", "c1", "c4", "c1"]), boxed("b", ["c5", "c9", "c2", "c6"])],
        model="mockllm/model",
        display="none",
        log_dir=str(tmp_path),
    )
    assert _box_init["configs"] == ["c3", "c1", "c4", "c5", "c9", "c2", "c6"]


async def test_running_sample_never_overlaps_seed_sandbox_startup(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    a_ran = anyio.Event()

    async def init() -> None:
        await _init_waiting_for(a_ran, events)

    _box_init["task_init"] = init
    a = Task(
        name="a",
        dataset=[Sample(input="x")],
        solver=[record_and_set(events, "a", a_ran)],
    )
    with anyio.fail_after(30):
        logs = await eval_async(
            [a, _boxed("b", events)],
            model="mockllm/model",
            max_tasks=2,
            log_dir=str(tmp_path),
        )
    assert [log.status for log in logs] == ["success", "success"]
    assert events[:2] == ["init start", "init end"]
    assert sorted(events[2:]) == ["a", "b"]


@pytest.mark.parametrize("how", _GROUP_RUNS)
async def test_added_task_runs_while_an_older_tasks_sandbox_setup_runs(
    tmp_path: Path, how: str
) -> None:
    # b was added first, but a (nothing to set up) does not wait behind b's
    # setup: it runs during it
    events: list[str] = []
    a_ran = anyio.Event()

    async def init() -> None:
        await _init_waiting_for(a_ran, events)

    _box_init["task_init"] = init
    a = Task(
        name="a",
        dataset=[Sample(input="x")],
        solver=[record_and_set(events, "a", a_ran)],
    )
    with anyio.fail_after(30):
        logs = await eval_async(
            _group_run(how, [_boxed("b", events), a]),
            model="mockllm/model",
            max_tasks=2,
            log_dir=str(tmp_path),
        )
    assert [log.status for log in logs] == ["success"] * 3
    assert events == ["init start", "a", "init end", "b"]


@pytest.mark.parametrize("how", _GROUP_RUNS)
async def test_group_sample_never_sees_sibling_task_init_environment(
    tmp_path: Path, how: str
) -> None:
    seen: list[str | None] = []
    a_ran = anyio.Event()

    @solver
    def record_env() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(os.environ.get("TASK_DISPATCH_BOX_ENV"))
            a_ran.set()
            return state

        return solve

    async def init() -> None:
        await _init_waiting_for(a_ran, [])

    _box_init["task_init"] = init
    _box_init["env"] = {"TASK_DISPATCH_BOX_ENV": "set-by-task-init"}
    assert "TASK_DISPATCH_BOX_ENV" not in os.environ
    group = [
        Task(name="a", dataset=[Sample(input="x")], solver=[record_env()]),
        _boxed("b", []),
    ]
    with anyio.fail_after(30):
        logs = await eval_async(
            _group_run(how, group),
            model="mockllm/model",
            max_tasks=2,
            log_dir=str(tmp_path),
        )
    assert [log.status for log in logs] == ["success"] * 3
    assert seen == [None]


@pytest.mark.parametrize("how", _GROUP_RUNS)
def test_added_task_sandbox_setup_failure_ends_only_that_task(
    tmp_path: Path, how: str
) -> None:
    # unlike the seed's, an added task's failed setup ends only that task,
    # with an error log on disk; its siblings and the run go on
    events: list[str] = []

    async def fail() -> None:
        raise PrerequisiteError("sandbox prerequisite missing")

    _box_init["task_init"] = fail
    logs = eval(
        _group_run(how, [_boxed("b", events), _plain("a", events)]),
        model="mockllm/model",
        max_tasks=3,
        display="none",
        log_dir=str(tmp_path),
    )
    assert sorted((log.eval.task, log.status) for log in logs) == [
        ("a", "success"),
        ("b", "error"),
        ("seed", "success"),
    ]
    b = next(log for log in logs if log.eval.task == "b")
    assert b.error is not None and "sandbox prerequisite missing" in b.error.message
    on_disk = read_eval_log(b.location, header_only=True)
    assert on_disk.status == "error" and on_disk.eval.task_id == b.eval.task_id
    assert events == ["a"]


@pytest.mark.parametrize("how", _GROUP_RUNS)
def test_added_task_log_created_after_its_sandbox_startup(
    tmp_path: Path, how: str
) -> None:
    # a task's `created` time (which also names its log file) follows its
    # sandbox start-up, as for the seed
    from inspect_ai._util.dateutil import iso_now

    init_end: list[str] = []

    async def init() -> None:
        # run into the next wall-clock second (`created` has 1s resolution)
        started = iso_now()
        while iso_now() == started:
            await anyio.sleep(0.05)
        init_end.append(iso_now())

    _box_init["task_init"] = init
    logs = eval(
        _group_run(how, [_boxed("b", [])]),
        model="mockllm/model",
        max_tasks=2,
        display="none",
        log_dir=str(tmp_path),
    )
    b = next(log for log in logs if log.eval.task == "b")
    assert b.status == "success"
    assert b.eval.created >= init_end[0]


async def test_cancel_during_seed_sandbox_startup_propagates(tmp_path: Path) -> None:
    # the task screen is not open during the seed's start-up, so a
    # cancellation then propagates out of eval_async
    entered = anyio.Event()

    async def block() -> None:
        entered.set()
        await anyio.sleep_forever()

    _box_init["task_init"] = block
    returned: list[Any] = []
    with anyio.fail_after(30):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_entered() -> None:
                    await entered.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_entered)
                returned.append(
                    await eval_async(
                        _boxed("b", []), model="mockllm/model", log_dir=str(tmp_path)
                    )
                )
    assert returned == []
    assert scope.cancelled_caught


def test_enqueue_task_during_seed_sandbox_startup(tmp_path: Path) -> None:
    # the run's queue is registered before the seed starts up, so a task
    # added from a sandbox's task_init joins the run
    async def add_task() -> None:
        await enqueue_task(Task(name="added", dataset=[Sample(input="x")]))

    _box_init["task_init"] = add_task
    logs = eval(
        _boxed("b", []), model="mockllm/model", display="none", log_dir=str(tmp_path)
    )
    assert [(log.eval.task, log.status) for log in logs] == [
        ("b", "success"),
        ("added", "success"),
    ]


def _retune_max_sandboxes(seen: dict[str, Any]) -> None:
    from inspect_ai._control.limits import _apply_process_knobs

    views = _apply_process_knobs(
        max_sandboxes=3,
        max_subprocesses=None,
        max_connections=None,
        model=None,
        dry_run=False,
    )
    seen["warnings"] = list(views.warnings)


@solver
def record_box_limit(seen: dict[str, Any]) -> Solver:
    from inspect_ai.util._concurrency import sandbox_limiters

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        seen["limit"] = sandbox_limiters()["task_dispatch_box"].concurrency
        return state

    return solve


def test_max_sandboxes_retune_reaches_queued_seed_task_sandbox(
    tmp_path: Path,
) -> None:
    # the seed's sandbox limiters exist from the start of the run, so a
    # `ctl config --max-sandboxes` retune reaches a sandbox type whose task
    # is still queued behind max_tasks
    seen: dict[str, Any] = {}

    @solver
    def retune() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            _retune_max_sandboxes(seen)
            return state

        return solve

    a = Task(name="a", dataset=[Sample(input="x")], solver=[retune()])
    b = Task(
        name="b",
        dataset=[Sample(input="x")],
        solver=[record_box_limit(seen)],
        sandbox="task_dispatch_box",
    )
    logs = eval(
        [a, b],
        model="mockllm/model",
        max_tasks=1,
        display="none",
        log_dir=str(tmp_path),
    )
    assert [log.status for log in logs] == ["success", "success"]
    assert seen == {"warnings": [], "limit": 3}


def test_max_sandboxes_retune_reaches_queued_added_task_sandbox(
    tmp_path: Path,
) -> None:
    # an added task starts up when it is taken, so a `ctl config
    # --max-sandboxes` retune reaches its sandbox type while it waits behind
    # max_tasks
    seen: dict[str, Any] = {}
    b_started_up = anyio.Event()

    async def init() -> None:
        b_started_up.set()

    _box_init["task_init"] = init

    @solver
    def add_and_retune() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await enqueue_task(
                Task(
                    name="b",
                    dataset=[Sample(input="x")],
                    solver=[record_box_limit(seen)],
                    sandbox="task_dispatch_box",
                ),
            )
            with anyio.fail_after(10):
                await b_started_up.wait()
            _retune_max_sandboxes(seen)
            return state

        return solve

    logs = eval(
        Task(name="a", dataset=[Sample(input="x")], solver=[add_and_retune()]),
        model="mockllm/model",
        max_tasks=1,
        display="none",
        log_dir=str(tmp_path),
    )
    assert [log.status for log in logs] == ["success", "success"]
    assert seen == {"warnings": [], "limit": 3}


def test_enqueued_task_with_invalid_config_raises_to_the_caller(
    tmp_path: Path,
) -> None:
    # enqueue_task configures the task, so its configuration (here a reducer
    # needing more epochs than the task has) raises to the caller, and the
    # run goes on
    caller_errors: list[str] = []

    @solver
    def add_invalid() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            try:
                await enqueue_task(
                    Task(
                        name="invalid",
                        dataset=[Sample(input="x")],
                        epochs=Epochs(2, "pass_at_5"),
                    ),
                )
            except PrerequisiteError as ex:
                caller_errors.append(str(ex))
            return state

        return solve

    parent = Task(name="parent", dataset=[Sample(input="x")], solver=[add_invalid()])
    logs = eval(parent, model="mockllm/model", display="none", log_dir=str(tmp_path))
    assert [(log.eval.task, log.status) for log in logs] == [("parent", "success")]
    assert len(caller_errors) == 1 and "pass_at_5" in caller_errors[0]


@pytest.mark.parametrize("added", [False, True])
def test_invalid_task_in_group_initialises_no_logger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, added: bool
) -> None:
    # the whole group is configured before any task of it is created, so an
    # invalid task leaves no log entry for its valid siblings
    inits: list[str] = []
    init = TaskLogger.init

    async def track_init(logger: TaskLogger) -> None:
        inits.append(logger.eval.task)
        await init(logger)

    monkeypatch.setattr(TaskLogger, "init", track_init)
    group = [
        Task(name="valid", dataset=[Sample(input="x")]),
        Task(
            name="invalid", dataset=[Sample(input="x")], epochs=Epochs(1, "pass_at_3")
        ),
    ]
    caller_errors: list[str] = []

    @solver
    def add_group() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            try:
                await enqueue_task(group)
            except PrerequisiteError as ex:
                caller_errors.append(str(ex))
            return state

        return solve

    if added:
        eval(
            Task(name="seed", dataset=[Sample(input="x")], solver=[add_group()]),
            model="mockllm/model",
            display="none",
            log_dir=str(tmp_path),
        )
        assert len(caller_errors) == 1 and "pass_at_3" in caller_errors[0]
    else:
        with pytest.raises(PrerequisiteError, match="pass_at_3"):
            eval(group, model="mockllm/model", display="none", log_dir=str(tmp_path))
    assert inits == (["seed"] if added else [])


def _dup_ids_task() -> Task:
    return Task(name="dup", dataset=[Sample(input="x", id=1), Sample(input="y", id=1)])


def test_invalid_follow_up_from_task_complete_fails_the_run(tmp_path: Path) -> None:
    # a follow-up returned by task_complete that can't run (duplicate sample
    # ids) raises where task_complete returns, which fails the run; the seed is
    # not charged with the error (nor retried for it)
    completes: list[str] = []

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [Task(name="seed", dataset=[Sample(input="x")])]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            completes.append(f"{log.eval.task}:{log.status}")
            if log.eval.task == "seed":
                return [_dup_ids_task()]
            return None

    with pytest.raises(PrerequisiteError, match="duplicate sample ids"):
        eval(
            Source(),
            model="mockllm/model",
            display="none",
            log_dir=str(tmp_path),
            task_retry_attempts=2,
        )
    assert completes == ["seed:success"]
    assert [
        read_eval_log(str(p), header_only=True).status for p in tmp_path.glob("*.eval")
    ] == ["success"]


def test_invalid_follow_up_from_sample_complete_is_handled_like_its_exceptions(
    tmp_path: Path,
) -> None:
    # returned by sample_complete, the follow-up raises where sample_complete
    # returns: the run treats it as it treats an exception sample_complete
    # raises itself (the seed errors, and no follow-up runs)
    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [Task(name="seed", dataset=[Sample(input="x")])]

        async def sample_complete(
            self, sample: EvalSample, task: Task
        ) -> list[Task] | None:
            return [_dup_ids_task()] if task.name == "seed" else None

    class Raising(Source):
        async def sample_complete(
            self, sample: EvalSample, task: Task
        ) -> list[Task] | None:
            raise PrerequisiteError("raised by sample_complete")

    def run(source: TaskSource) -> list[tuple[str, str]]:
        logs = eval(
            source, model="mockllm/model", display="none", log_dir=str(tmp_path)
        )
        return [(log.eval.task, log.status) for log in logs]

    assert run(Source()) == run(Raising()) == [("seed", "error")]


def test_tasks_enqueued_during_next_tasks_start_after_its_batch(
    tmp_path: Path,
) -> None:
    # tasks enqueued while next_tasks() runs are queued at once, and its batch
    # when it returns, ahead of them (in start order and in the results)
    started: list[str] = []

    class Source(TaskSource):
        calls = 0

        def initial_tasks(self) -> list[Task]:
            return [_plain("seed", started)]

        async def next_tasks(self) -> list[Task] | None:
            self.calls += 1
            if self.calls == 1:
                await enqueue_task(_plain("late", started))
                return [_plain("batch", started)]
            return None

    logs = eval(
        Source(),
        model="mockllm/model",
        display="none",
        log_dir=str(tmp_path),
        max_tasks=1,
    )
    assert started == ["seed", "batch", "late"]
    assert [log.eval.task for log in logs] == ["seed", "batch", "late"]
