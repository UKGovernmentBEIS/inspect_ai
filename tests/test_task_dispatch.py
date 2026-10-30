"""Tests for a run's queue, its scheduling loop and the start-up of task groups.

The loop tests drive `TaskDispatcher` without a full eval: tasks are real
resolved tasks, but their loggers are fakes, starting up a group only builds
run options, and running a task is replaced by a scripted `_run_task`, so each
test controls exactly when every task finishes and how. The end-to-end tests
at the bottom run real evals with a sandbox provider whose `task_init` the test
controls.
"""

import os
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast, overload

import anyio
import pytest
from typing_extensions import override

from inspect_ai import Epochs, Task, TaskSource, enqueue_task, eval, eval_async
from inspect_ai._control.max_tasks import (
    reset_max_tasks_override,
    set_max_tasks_override,
    task_dispatcher_stats,
)
from inspect_ai._display.core.display import CancelType
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.run import (
    _TASK_OVERRIDABLE,
    TaskDispatcher,
    TaskRunResult,
    pick_balanced,
    wants_retry,
)
from inspect_ai._eval.task.enqueue import Attempt, RunQueue, TaskStartPolicy
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._eval.task.run import TaskRunOptions
from inspect_ai._eval.task.tasks import Tasks
from inspect_ai._util.error import PrerequisiteError
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
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    sandboxenv,
)
from inspect_ai.util._display import init_display_type


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

    def __init__(self, label: str) -> None:
        self.label = label
        self.eval = EvalSpec(
            created="2026-01-01T00:00:00+00:00",
            task=label,
            task_id=f"id-{label}",
            model="mockllm/model",
            dataset=EvalDataset(),
            config=EvalConfig(),
        )
        self.finished = False
        self.discarded = 0
        self.reinits = 0
        self.destination_written = False
        self.location = f"{label}.eval"
        self.recorder = SimpleNamespace(close_seed_source=self._close_seed_source)

    async def _close_seed_source(self, eval: EvalSpec) -> None:
        pass

    async def discard(self, **kwargs: Any) -> None:
        self.discarded += 1

    async def reinit(self) -> None:
        self.reinits += 1
        self.eval = self.eval.model_copy(update=dict(eval_id=f"{self.label}-r"))


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
    """A dispatcher whose tasks start up and run by script, recording what happens."""

    def __init__(
        self,
        models: list[Model],
        *,
        parallel: int = 1,
        retries: int = 0,
        default_start: TaskStartPolicy = "after_batch",
    ) -> None:
        self.parallel = parallel
        self.retries = retries
        self.events: list[str] = []
        self.loggers: dict[str, FakeLogger] = {}
        self.finish: dict[str, anyio.Event] = {}
        self.started: dict[str, anyio.Event] = {}
        self.fail_next: set[str] = set()
        # (labels started up together, events so far) per start-up
        self.start_ups: list[tuple[list[str], list[str]]] = []

        def resolve(tasks: Tasks) -> list[ResolvedTask]:
            return [
                resolved
                for model in models
                for resolved in resolve_tasks(tasks, {}, model, None, None, None)
            ]

        self.queue = RunQueue("run", resolve, default_start)

    async def start_up(self, group: list[ResolvedTask]) -> list[TaskRunOptions]:
        if self.parallel == 1:
            group = sorted(group, key=lambda t: t.sequence)
        for task in group:
            if task.task.name.startswith("invalid"):
                raise PrerequisiteError(f"invalid task {task.task.name}")
        self.start_ups.append(([_label(t) for t in group], list(self.events)))
        options = []
        for task in group:
            label = _label(task)
            self.loggers[label] = FakeLogger(label)
            self.finish[label] = anyio.Event()
            self.started[label] = anyio.Event()
            options.append(_options(task, self.loggers[label]))
        return options

    async def run_task(
        self, options: TaskRunOptions, can_retry: bool = False
    ) -> TaskRunResult:
        logger = cast(FakeLogger, options.logger)
        label = logger.label
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
            self.queue,
            self.start_up,
            parallel=self.parallel,
            task_retry_attempts=self.retries,
            source=source,
            debug_errors=False,
        )

    async def run(
        self, seed: list[ResolvedTask], source: TaskSource | None = None
    ) -> list[EvalLog]:
        options = await self.start_up(seed)
        self.start_ups.clear()
        return await self.dispatcher(source).run(options)


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch) -> Any:
    # these tests cover the default mode, where each group starts up its
    # sandboxes before any of it runs
    monkeypatch.delenv("INSPECT_TASK_SETUP_IN_SLOT", raising=False)
    init_display_type("none")
    yield
    reset_max_tasks_override()


def _install(monkeypatch: pytest.MonkeyPatch, harness: Harness) -> None:
    monkeypatch.setattr("inspect_ai._eval.run._run_task", harness.run_task)


async def _wait_started(harness: Harness, *labels: str) -> None:
    with anyio.fail_after(10):
        for label in labels:
            # a task added mid-run has no event until it has started up
            while label not in harness.started:
                await anyio.sleep(0)
            await harness.started[label].wait()


async def _wait_stats(in_flight: int, pending: int) -> None:
    # the loop's state is published through the dispatcher stats; poll it
    # (each iteration yields to the loop)
    with anyio.fail_after(10):
        while True:
            stats = task_dispatcher_stats()
            if stats is not None and (stats.in_flight, stats.pending) == (
                in_flight,
                pending,
            ):
                return
            await anyio.sleep(0)


def _starts(harness: Harness) -> list[str]:
    return [e.split()[1] for e in harness.events if e.startswith("start")]


# ------------------------------------------------------------- settings


def test_task_overridable_settings_exist_on_task_and_eval_config() -> None:
    # TaskSettings resolves these by name (getattr/setattr)
    task = Task(dataset=[Sample(input="x")])
    for name in _TASK_OVERRIDABLE:
        assert name in EvalConfig.model_fields
        assert hasattr(task, name)


# ------------------------------------------------------------- RunQueue


def test_run_queue_files_added_tasks_by_start_policy() -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], default_start="after_batch")
    queue = harness.queue
    queue.put([_task("a")])
    queue.put([_task("w1"), _task("w2")], start="when_free")
    queue.put([_task("b")], start="after_batch")
    assert queue.wake._event.is_set()
    assert [_label(t) for t in queue.take("when_free")] == ["w1@m1", "w2@m1"]
    assert queue.take("when_free") == []
    assert [_label(t) for t in queue.take("after_batch")] == ["a@m1", "b@m1"]


def test_run_queue_default_start_in_task_source_run_is_when_free() -> None:
    queue = Harness([get_model("mockllm/m1")], default_start="when_free").queue
    queue.put([_task("a")])
    assert [t.task.name for t in queue.take("when_free")] == ["a"]


def test_run_queue_close_refuses_put_and_returns_ready() -> None:
    m1 = get_model("mockllm/m1")
    resolved: list[Tasks] = []

    def resolve(tasks: Tasks) -> list[ResolvedTask]:
        resolved.append(tasks)
        return _resolve(["x"], [m1])

    queue = RunQueue("run", resolve, "when_free")
    queue.put([_task("w")])
    task = _resolve(["ready"], [m1])[0]
    attempt = Attempt(0, _options(task, FakeLogger("ready@m1")), 0)
    queue.ready.append(attempt)
    assert queue.close() == [attempt]
    assert queue.ready == []
    assert queue.take("when_free") == []
    with pytest.raises(RuntimeError, match="run 'run' has finished dispatching"):
        queue.put([_task("late")])
    # refused before resolution
    assert len(resolved) == 1


# ------------------------------------------------------------- pick_balanced


def _attempts(labels: list[tuple[str, Model]]) -> list[Attempt]:
    attempts = []
    for i, (name, model) in enumerate(labels):
        task = _resolve([name], [model])[0]
        attempts.append(Attempt(i, _options(task, FakeLogger(_label(task))), 0))
    return attempts


def test_pick_balanced_prefers_least_used_model_then_queue_order() -> None:
    m1, m2 = get_model("mockllm/m1"), get_model("mockllm/m2")
    ready = _attempts([("a", m1), ("b", m1), ("c", m2), ("d", m2)])
    assert pick_balanced(ready, Counter()) is ready[0]
    assert pick_balanced(ready, Counter({m1: 1})) is ready[2]
    assert pick_balanced(ready, Counter({m1: 1, m2: 1})) is ready[0]


def test_pick_balanced_skips_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    m1, m2 = get_model("mockllm/m1"), get_model("mockllm/m2")
    ready = _attempts([("a", m1), ("b", m2)])
    paused: set[str] = {"id-a@m1"}
    monkeypatch.setattr(
        "inspect_ai._eval.run.task_dispatch_paused",
        lambda task_id, model=None: task_id in paused,
    )
    assert pick_balanced(ready, Counter()) is ready[1]
    paused.add("id-b@m2")
    assert pick_balanced(ready, Counter()) is None


# ------------------------------------------------------------- wants_retry


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
    ],
)
def test_wants_retry(
    cancel_type: CancelType, status: EvalStatus, retries: int, expected: bool
) -> None:
    [attempt] = _attempts([("a", get_model("mockllm/m1"))])
    attempt = attempt._replace(retries_remaining=retries)
    task_log = EvalLog(eval=attempt.options.logger.eval, status=status)
    assert wants_retry(cancel_type, task_log, attempt) is expected


def test_wants_retry_not_after_operator_abandoned_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [attempt] = _attempts([("a", get_model("mockllm/m1"))])
    attempt = attempt._replace(retries_remaining=1)
    task_log = EvalLog(eval=attempt.options.logger.eval, status="error")
    monkeypatch.setattr(
        "inspect_ai._eval.run.task_retry_abandoned", lambda task_id: True
    )
    assert not wants_retry(None, task_log, attempt)


# ------------------------------------------------------------- the idle rule


class _ScriptedSource(TaskSource):
    """``next_tasks()`` returns the scripted batches in order; one call too many raises."""

    def __init__(self, batches: list[list[str] | None]) -> None:
        self.batches = list(batches)

    async def next_tasks(self) -> list[Task] | None:
        batch = self.batches.pop(0)
        return None if batch is None else [_task(n) for n in batch]


@pytest.mark.parametrize(
    "source,added,admitted,idle_groups",
    [
        # after_batch tasks before the source's batches
        (
            [["s1"], None],
            [("a", "after_batch"), ("w", "when_free")],
            ["w"],
            [["a"], ["s1"]],
        ),
        # the source is asked until it returns None
        ([["s1", "s2"], ["s3"], None], [], [], [["s1", "s2"], ["s3"]]),
        # an empty batch ends the source
        ([[]], [], [], []),
        # without a source: after_batch tasks, then nothing
        (None, [("a", None), ("w", "when_free")], ["w"], [["a"]]),
        (None, [], [], []),
    ],
)
async def test_dispatcher_idle_rule(
    source: list[list[str] | None] | None,
    added: list[tuple[str, TaskStartPolicy | None]],
    admitted: list[str],
    idle_groups: list[list[str]],
) -> None:
    # the loop's side of the queue, without running tasks: the cycle takes
    # when_free tasks, and add_when_idle adds the rest once idle
    scripted = None if source is None else _ScriptedSource(source)
    harness = Harness([get_model("mockllm/m1")], parallel=2)
    dispatcher = harness.dispatcher(scripted)
    for name, start in added:
        harness.queue.put([_task(name)], start=start)

    await dispatcher.add_group(harness.queue.take("when_free"))
    while await dispatcher.add_when_idle():
        pass

    groups = [
        [label.split("@")[0] for label in labels] for labels, _ in harness.start_ups
    ]
    assert groups == ([admitted] if admitted else []) + idle_groups
    # every scripted batch was asked for, and none beyond (a further call raises)
    assert scripted is None or scripted.batches == []


async def test_dispatcher_idle_takes_when_free_before_after_batch() -> None:
    # when_free tasks added after the cycle took them (during an await later
    # in the cycle) start before after_batch tasks and before next_tasks()
    source = _ScriptedSource([["s1"], None])
    harness = Harness([get_model("mockllm/m1")], parallel=2)
    dispatcher = harness.dispatcher(source)
    harness.queue.put([_task("a")], start="after_batch")
    harness.queue.put([_task("w")], start="when_free")
    while await dispatcher.add_when_idle():
        pass
    assert [labels for labels, _ in harness.start_ups] == [
        ["w@m1"],
        ["a@m1"],
        ["s1@m1"],
    ]
    assert source.batches == []


async def test_dispatcher_runs_tasks_added_during_final_next_tasks() -> None:
    # next_tasks() blocks; tasks added meanwhile keep their start policy once
    # it returns None, and the ended source is never asked again
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

    source = BlockingSource()
    harness = Harness([get_model("mockllm/m1")], parallel=2)
    dispatcher = harness.dispatcher(source)
    first: list[bool] = []

    async def idle() -> None:
        first.append(await dispatcher.add_when_idle())

    async with anyio.create_task_group() as tg:
        tg.start_soon(idle)
        await entered.wait()
        harness.queue.put([_task("w")], start="when_free")
        harness.queue.put([_task("a")], start="after_batch")
        release.set()

    assert first == [True] and harness.start_ups == []
    while await dispatcher.add_when_idle():
        pass
    assert [labels for labels, _ in harness.start_ups] == [["w@m1"], ["a@m1"]]
    assert source.calls == 1


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

    assert set(harness.events[:2]) == {"start a@m1", "start c@m2"}
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
        harness.queue.put([_task("c"), _task("d")], start="when_free")
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


async def test_loop_retry_queues_behind_ready_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1, retries=1)
    _install(monkeypatch, harness)
    harness.fail_next.add("a@m1")

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        harness.queue.put([_task("c")], start="when_free")
        # c has started up and is ready behind b (pending also counts a task
        # still starting up)
        with anyio.fail_after(10):
            while len(harness.queue.ready) != 2:
                await anyio.sleep(0)
        harness.finish["a@m1"].set()
        await _wait_started(harness, "b@m1")
        harness.finish["b@m1"].set()
        await _wait_started(harness, "c@m1")
        harness.started["a@m1"] = anyio.Event()
        harness.finish["c@m1"].set()
        await _wait_started(harness, "a@m1")
        harness.finish["a@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a", "b"], [m1]))

    assert _starts(harness) == ["a@m1", "b@m1", "c@m1", "a@m1"]
    # the retry reused the first attempt's start-up, after a logger reinit
    assert [labels for labels, _ in harness.start_ups] == [["c@m1"]]
    assert harness.loggers["a@m1"].reinits == 1
    # the retry's log replaces the failed attempt's, in the task's position
    assert [(log.eval.task, log.status) for log in logs] == [
        ("a@m1", "success"),
        ("b@m1", "success"),
        ("c@m1", "success"),
    ]


async def test_loop_after_batch_waits_for_later_when_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # an after_batch task waits until nothing is ready or running, including
    # when_free tasks added after it
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=3)
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_started(harness, "a@m1", "b@m1")
        harness.queue.put([_task("held")], start="after_batch")
        harness.queue.put([_task("free")], start="when_free")
        await _wait_started(harness, "free@m1")
        # the held task counts as pending
        await _wait_stats(in_flight=3, pending=1)
        harness.finish["a@m1"].set()
        harness.finish["b@m1"].set()
        await _wait_stats(in_flight=1, pending=1)
        harness.queue.put([_task("later")], start="when_free")
        await _wait_started(harness, "later@m1")
        harness.finish["free@m1"].set()
        await _wait_stats(in_flight=1, pending=1)
        assert "held@m1" not in harness.started
        harness.finish["later@m1"].set()
        await _wait_started(harness, "held@m1")
        harness.finish["held@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a", "b"], [m1]))

    assert harness.events.index("start held@m1") > harness.events.index(
        "end later@m1 success"
    )
    assert [log.eval.task for log in logs] == [
        "a@m1",
        "b@m1",
        "free@m1",
        "later@m1",
        "held@m1",
    ]
    # the run closed its queue
    with pytest.raises(RuntimeError, match="finished dispatching"):
        harness.queue.put([_task("late")], start="when_free")


async def test_loop_asks_source_only_when_idle_until_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2, default_start="when_free")
    _install(monkeypatch, harness)
    calls: list[list[str]] = []

    class Source(TaskSource):
        async def next_tasks(self) -> list[Task] | None:
            calls.append(list(harness.events))
            if len(calls) == 1:
                # added while next_tasks() runs: follows its batch
                harness.queue.put([_task("late_free")], start="when_free")
                return [_task("n1"), _task("n2")]
            return None

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        harness.finish["a@m1"].set()
        await _wait_started(harness, "n1@m1", "n2@m1")
        harness.finish["n1@m1"].set()
        await _wait_started(harness, "late_free@m1")
        harness.finish["n2@m1"].set()
        harness.finish["late_free@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]), Source())

    # asked only when nothing was ready or running; not again after None
    assert len(calls) == 2
    assert calls[0] == ["start a@m1", "end a@m1 success"]
    # the batch started up whole, before the task added during the call
    assert [labels for labels, _ in harness.start_ups] == [
        ["n1@m1", "n2@m1"],
        ["late_free@m1"],
    ]
    assert harness.start_ups[0][1] == ["start a@m1", "end a@m1 success"]
    assert [log.eval.task for log in logs] == [
        "a@m1",
        "n1@m1",
        "n2@m1",
        "late_free@m1",
    ]
    with pytest.raises(RuntimeError, match="finished dispatching"):
        harness.queue.put([_task("after_end")])


async def test_loop_starts_up_added_group_whole_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=3, retries=1)
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        harness.queue.put([_task("b"), _task("c")], start="when_free")
        await _wait_started(harness, "b@m1", "c@m1")
        harness.fail_next.add("b@m1")
        harness.started["b@m1"] = anyio.Event()
        harness.finish["b@m1"].set()
        await _wait_started(harness, "b@m1")
        for label in ("a@m1", "b@m1", "c@m1"):
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["a"], [m1]))

    # the group started up in one go, before either task started; b's retry
    # reused that start-up
    assert harness.start_ups == [(["b@m1", "c@m1"], ["start a@m1"])]
    assert [(log.eval.task, log.status) for log in logs] == [
        ("a@m1", "success"),
        ("b@m1", "success"),
        ("c@m1", "success"),
    ]


async def test_stats_count_tasks_waiting_and_starting_up_as_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the control channel's pending count covers added tasks not yet taken and
    # a group being started up, not only ready attempts
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)
    starting = anyio.Event()
    release = anyio.Event()
    start_up = harness.start_up

    async def slow_start_up(group: list[ResolvedTask]) -> list[TaskRunOptions]:
        starting.set()
        await release.wait()
        return await start_up(group)

    seed = await harness.start_up(_resolve(["a"], [m1]))
    monkeypatch.setattr(harness, "start_up", slow_start_up)

    async def drive() -> None:
        await _wait_started(harness, "a@m1")
        harness.queue.put([_task("held")], start="after_batch")
        await _wait_stats(in_flight=1, pending=1)
        harness.queue.put([_task("b"), _task("c")], start="when_free")
        await starting.wait()
        await _wait_stats(in_flight=1, pending=3)
        release.set()
        await _wait_stats(in_flight=1, pending=3)
        for label in ("a@m1", "b@m1", "c@m1", "held@m1"):
            await _wait_started(harness, label)
            harness.finish[label].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.dispatcher().run(seed)
    assert [log.eval.task for log in logs] == ["a@m1", "b@m1", "c@m1", "held@m1"]


class _FakeSetup:
    """A task's own sandbox setup (slot mode), finished by the test."""

    def __init__(self, harness: "LaneHarness", label: str) -> None:
        self.harness = harness
        self.label = label
        self.done = False

    def started(self) -> bool:
        return self.done

    async def __call__(self) -> None:
        harness = self.harness
        if self.done:
            harness.events.append(f"setup-done {self.label}")
            return
        harness.events.append(f"setup {self.label}")
        harness.in_setup[self.label].set()
        await harness.setup_finish[self.label].wait()
        harness.setup_finish[self.label] = anyio.Event()
        if self.label in harness.fail_setup:
            harness.fail_setup.discard(self.label)
            raise RuntimeError(f"setup of {self.label} failed")
        self.done = True
        harness.events.append(f"set-up {self.label}")


class LaneHarness(Harness):
    """A harness whose tasks named ``box*`` set up their own sandboxes."""

    def __init__(self, models: list[Model], **kwargs: Any) -> None:
        super().__init__(models, **kwargs)
        self.in_setup: dict[str, anyio.Event] = {}
        self.setup_finish: dict[str, anyio.Event] = {}
        self.fail_setup: set[str] = set()

    async def start_up(self, group: list[ResolvedTask]) -> list[TaskRunOptions]:
        options = await super().start_up(group)
        for i, task_options in enumerate(options):
            label = cast(FakeLogger, task_options.logger).label
            if label.startswith("box"):
                self.in_setup[label] = anyio.Event()
                self.setup_finish[label] = anyio.Event()
                options[i] = replace(
                    task_options, sandbox_setup=_FakeSetup(self, label)
                )
        return options

    async def run_task(
        self, options: TaskRunOptions, can_retry: bool = False
    ) -> TaskRunResult:
        # as task_run: the task starts, then sets up, then (in the setup lane)
        # waits for its task slot, then runs
        logger = cast(FakeLogger, options.logger)
        label = logger.label
        if options.sandbox_setup is not None:
            self.events.append(f"start {label}")
            try:
                await options.sandbox_setup()
            except RuntimeError:
                self.events.append(f"end {label} error")
                logger.finished = True
                return TaskRunResult(EvalLog(eval=logger.eval, status="error"), None)
            if options.wait_for_task_slot is not None:
                await options.wait_for_task_slot()
            self.events.append(f"slot {label}")
        return await super().run_task(options, can_retry)


async def _wait_in_setup(harness: LaneHarness, label: str) -> None:
    with anyio.fail_after(10):
        while label not in harness.in_setup:
            await anyio.sleep(0)
        await harness.in_setup[label].wait()
    harness.in_setup[label] = anyio.Event()


async def _wait_event(harness: Harness, event: str) -> None:
    with anyio.fail_after(10):
        while event not in harness.events:
            await anyio.sleep(0)


async def test_setup_lane_sets_up_one_task_at_a_time_outside_the_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # max_tasks=1. box1 sets up in the lane while plain1 runs in the slot;
    # box2 waits for the lane, unstarted. Once set up, box1 waits for the slot
    # and still holds the lane; when plain1 ends, box1 takes the slot ahead of
    # plain2 (it started first), and box2 enters the lane
    m1 = get_model("mockllm/m1")
    harness = LaneHarness([m1], parallel=1)
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_in_setup(harness, "box1@m1")
        await _wait_started(harness, "plain1@m1")
        await _wait_stats(in_flight=2, pending=2)
        harness.setup_finish["box1@m1"].set()
        await _wait_event(harness, "set-up box1@m1")
        harness.finish["plain1@m1"].set()
        await _wait_started(harness, "box1@m1")
        await _wait_in_setup(harness, "box2@m1")
        await _wait_stats(in_flight=2, pending=1)
        harness.setup_finish["box2@m1"].set()
        await _wait_event(harness, "set-up box2@m1")
        harness.finish["box1@m1"].set()
        await _wait_started(harness, "box2@m1")
        harness.finish["box2@m1"].set()
        await _wait_started(harness, "plain2@m1")
        harness.finish["plain2@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["box1", "plain1", "box2", "plain2"], [m1]))

    def of(task: str) -> list[str]:
        return [e.split()[0] for e in harness.events if e.split()[1] == task]

    assert of("box1@m1") == ["start", "setup", "set-up", "slot", "start", "end"]
    assert of("box2@m1") == ["start", "setup", "set-up", "slot", "start", "end"]
    assert of("plain1@m1") == ["start", "end"]
    assert of("plain2@m1") == ["start", "end"]
    order = harness.events.index
    # box1, set up, waits for the slot plain1 holds and keeps the lane: box2
    # enters the lane only once box1 has the slot; the slot goes to the
    # set-up lane task before plain2
    assert order("end plain1@m1 success") < order("slot box1@m1")
    assert order("end plain1@m1 success") < order("start box2@m1")
    assert order("end box1@m1 success") < order("slot box2@m1")
    assert order("end box2@m1 success") < order("start plain2@m1")
    assert [log.status for log in logs] == ["success"] * 4


async def test_setup_lane_failed_setup_frees_the_lane_and_its_retry_sets_up_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = LaneHarness([m1], parallel=1, retries=1)
    harness.fail_setup.add("box1@m1")
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_in_setup(harness, "box1@m1")
        harness.setup_finish["box1@m1"].set()
        # the retry still has setup to do, so it goes through the lane again
        await _wait_in_setup(harness, "box1@m1")
        harness.setup_finish["box1@m1"].set()
        await _wait_started(harness, "box1@m1")
        harness.finish["box1@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["box1"], [m1]))

    assert harness.events == [
        "start box1@m1",
        "setup box1@m1",
        "end box1@m1 error",
        "start box1@m1",
        "setup box1@m1",
        "set-up box1@m1",
        "slot box1@m1",
        "start box1@m1",
        "end box1@m1 success",
    ]
    assert [log.status for log in logs] == ["success"]


async def test_retry_whose_setup_finished_takes_a_slot_beside_the_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # max_tasks=1. box1 sets up, runs and fails; its retry has no setup left,
    # so it takes the slot while box2 sets up in the lane
    m1 = get_model("mockllm/m1")
    harness = LaneHarness([m1], parallel=1, retries=1)
    harness.fail_next.add("box1@m1")
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_in_setup(harness, "box1@m1")
        harness.setup_finish["box1@m1"].set()
        await _wait_started(harness, "box1@m1")
        await _wait_in_setup(harness, "box2@m1")
        harness.finish["box1@m1"].set()
        await _wait_event(harness, "setup-done box1@m1")
        await _wait_started(harness, "box1@m1")
        harness.finish["box1@m1"].set()
        harness.setup_finish["box2@m1"].set()
        await _wait_started(harness, "box2@m1")
        harness.finish["box2@m1"].set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        logs = await harness.run(_resolve(["box1", "box2"], [m1]))

    retry_start = harness.events.index("setup-done box1@m1")
    assert harness.events.index("setup box2@m1") < retry_start
    assert harness.events.index("slot box2@m1") > retry_start
    assert [log.status for log in logs] == ["success", "success"]


class _CancellingHarness(LaneHarness):
    """A lane harness in which a task can end with a ``cancelled`` log."""

    def __init__(self, models: list[Model], **kwargs: Any) -> None:
        super().__init__(models, **kwargs)
        self.cancel_next: set[str] = set()

    async def run_task(
        self, options: TaskRunOptions, can_retry: bool = False
    ) -> TaskRunResult:
        logger = cast(FakeLogger, options.logger)
        label = logger.label
        if label not in self.cancel_next:
            return await super().run_task(options, can_retry)
        self.events.append(f"start {label}")
        self.started[label].set()
        await self.finish[label].wait()
        self.events.append(f"end {label} cancelled")
        logger.finished = True
        return TaskRunResult(EvalLog(eval=logger.eval, status="cancelled"), None)


@pytest.mark.parametrize("set_up_first", [True, False])
async def test_lane_task_still_gets_a_slot_after_dispatch_stops(
    monkeypatch: pytest.MonkeyPatch, set_up_first: bool
) -> None:
    # max_tasks=1: plain1 runs in the slot, box1 sets up in the lane. plain1
    # ends cancelled, which stops dispatch (no more attempts start). box1 has
    # started, so it is still given the slot and ends (from review round 6 B).
    # A hang would end at fail_after, whose cancellation the dispatcher
    # absorbs: box1's log would then be missing
    m1 = get_model("mockllm/m1")
    harness = _CancellingHarness([m1], parallel=1)
    harness.cancel_next.add("plain1@m1")
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_in_setup(harness, "box1@m1")
        await _wait_started(harness, "plain1@m1")
        if set_up_first:
            harness.setup_finish["box1@m1"].set()
            await _wait_event(harness, "set-up box1@m1")
            harness.finish["plain1@m1"].set()
        else:
            harness.finish["plain1@m1"].set()
            await _wait_event(harness, "end plain1@m1 cancelled")
            harness.setup_finish["box1@m1"].set()
        await _wait_event(harness, "slot box1@m1")
        await _wait_started(harness, "box1@m1")
        harness.finish["box1@m1"].set()

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(drive)
            logs = await harness.run(_resolve(["box1", "plain1", "plain2"], [m1]))

    assert [(log.eval.task, log.status) for log in logs] == [
        ("box1@m1", "success"),
        ("plain1@m1", "cancelled"),
    ]
    assert "start plain2@m1" not in harness.events


async def test_lane_task_of_a_paused_task_waits_for_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # max_tasks=1: box@m1 sets up in the lane while plain@m2 runs; m1 is then
    # paused. When plain@m2 ends, the set-up box@m1 is passed over, as a
    # paused ready attempt is, and plain2@m2 takes the slot; box@m1 takes it
    # after the resume (from review round 6 B)
    from inspect_ai._control.pause import fire_dispatch_wakers

    m1, m2 = get_model("mockllm/m1"), get_model("mockllm/m2")
    harness = LaneHarness([m1, m2], parallel=1)
    paused: set[str] = set()
    monkeypatch.setattr(
        "inspect_ai._eval.run.task_dispatch_paused",
        lambda task_id, model=None: model in paused,
    )
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_in_setup(harness, "box@m1")
        await _wait_started(harness, "plain@m2")
        paused.add("mockllm/m1")
        harness.setup_finish["box@m1"].set()
        await _wait_event(harness, "set-up box@m1")
        harness.finish["plain@m2"].set()
        await _wait_started(harness, "plain2@m2")
        harness.events.append("resume")
        paused.clear()
        fire_dispatch_wakers()
        harness.finish["plain2@m2"].set()
        await _wait_started(harness, "box@m1")
        harness.finish["box@m1"].set()

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(drive)
            await harness.run(
                _resolve(["box"], [m1]) + _resolve(["plain", "plain2"], [m2])
            )

    assert harness.events.index("resume") < harness.events.index("slot box@m1")


async def test_lane_task_counts_for_its_model_only_once_in_a_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # model balancing counts tasks running in slots: while box@m1 sets up, the
    # slot goes to the earliest ready task (plain@m1), not to plain@m2 as if
    # m1 were busy
    m1, m2 = get_model("mockllm/m1"), get_model("mockllm/m2")
    harness = LaneHarness([m1, m2], parallel=1)
    _install(monkeypatch, harness)

    async def drive() -> None:
        await _wait_in_setup(harness, "box@m1")
        await _wait_started(harness, "plain@m1")
        harness.finish["plain@m1"].set()
        harness.setup_finish["box@m1"].set()
        await _wait_started(harness, "box@m1")
        harness.finish["box@m1"].set()
        await _wait_started(harness, "plain@m2")
        harness.finish["plain@m2"].set()

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(drive)
            await harness.run(_resolve(["box"], [m1]) + _resolve(["plain"], [m1, m2]))

    starts = _starts(harness)
    assert starts.index("plain@m1") < starts.index("plain@m2")


@pytest.mark.parametrize("during", ["start_up", "next_tasks"])
async def test_loop_cancel_while_adding_tasks_propagates(
    monkeypatch: pytest.MonkeyPatch, during: str
) -> None:
    # a cancellation of the run while the loop starts up an added group or
    # awaits next_tasks() propagates (the interrupted tasks have no log); the
    # running task's log entry and the ready tasks' entries are released
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1, default_start="when_free")
    _install(monkeypatch, harness)
    blocked = anyio.Event()

    async def blocking_start_up(group: list[ResolvedTask]) -> list[TaskRunOptions]:
        blocked.set()
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    class Source(TaskSource):
        async def next_tasks(self) -> list[Task] | None:
            blocked.set()
            await anyio.sleep_forever()
            return None

    seed = await harness.start_up(_resolve(["a", "b"], [m1]))
    if during == "start_up":
        monkeypatch.setattr(harness, "start_up", blocking_start_up)
    dispatcher = harness.dispatcher(Source() if during == "next_tasks" else None)
    returned: list[Any] = []
    with anyio.fail_after(10):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_blocked() -> None:
                    await _wait_started(harness, "a@m1")
                    if during == "start_up":
                        harness.queue.put([_task("c")])
                    else:
                        harness.finish["a@m1"].set()
                        await _wait_started(harness, "b@m1")
                        harness.finish["b@m1"].set()
                    await blocked.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_blocked)
                returned.append(await dispatcher.run(seed))

    assert returned == []
    assert scope.cancelled_caught
    if during == "start_up":
        assert harness.events == ["start a@m1"]
        assert harness.loggers["a@m1"].discarded == 1
        assert harness.loggers["b@m1"].discarded == 1
    assert task_dispatcher_stats() is None
    with pytest.raises(RuntimeError, match="finished dispatching"):
        harness.queue.put([_task("late")])


async def test_loop_cancel_while_tasks_run_is_absorbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1)
    _install(monkeypatch, harness)
    seed = await harness.start_up(_resolve(["a", "b"], [m1]))
    with anyio.fail_after(10):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_running() -> None:
                    await _wait_started(harness, "a@m1")
                    scope.cancel()

                tg.start_soon(cancel_when_running)
                logs = await harness.dispatcher().run(seed)
                # the task screen absorbs it: the run returns what it has
                assert logs == []
    # the queued task's entry was discarded
    assert harness.loggers["b@m1"].discarded == 1


async def test_loop_cancel_while_retry_reinitialises_discards_its_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a cancellation of the run while a failed attempt's logger reinitialises
    # for its retry releases that logger (the retry never reaches the queue)
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=1, retries=1)
    _install(monkeypatch, harness)
    harness.fail_next.add("a@m1")
    seed = await harness.start_up(_resolve(["a"], [m1]))
    logger = harness.loggers["a@m1"]
    reinitialising = anyio.Event()

    async def blocking_reinit() -> None:
        logger.finished = False
        reinitialising.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(logger, "reinit", blocking_reinit)
    with anyio.fail_after(10):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_reinitialising() -> None:
                    await _wait_started(harness, "a@m1")
                    harness.finish["a@m1"].set()
                    await reinitialising.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_reinitialising)
                await harness.dispatcher().run(seed)

    assert logger.discarded == 1
    assert task_dispatcher_stats() is None


@pytest.mark.parametrize("invalid", [False, True])
async def test_loop_added_group_start_up_failure_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, invalid: bool
) -> None:
    m1 = get_model("mockllm/m1")
    harness = Harness([m1], parallel=2)
    _install(monkeypatch, harness)

    async def failing_start_up(group: list[ResolvedTask]) -> list[TaskRunOptions]:
        raise RuntimeError("sandbox startup failed")

    seed = await harness.start_up(_resolve(["a"], [m1]))
    if not invalid:
        monkeypatch.setattr(harness, "start_up", failing_start_up)

    async def add_tasks() -> None:
        await _wait_started(harness, "a@m1")
        # the put itself succeeds
        harness.queue.put([_task("invalid_b"), _task("c")], start="when_free")

    with anyio.fail_after(10):
        with pytest.raises(ExceptionGroup) as excinfo:
            async with anyio.create_task_group() as tg:
                tg.start_soon(add_tasks)
                await harness.dispatcher().run(seed)

    if invalid:
        assert excinfo.group_contains(PrerequisiteError, match="invalid task")
    else:
        assert excinfo.group_contains(RuntimeError, match="sandbox startup failed")
    # the running task was cancelled and its entry released; the group never
    # started
    assert harness.events == ["start a@m1"]
    assert harness.loggers["a@m1"].discarded == 1
    assert task_dispatcher_stats() is None


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


_GROUP_RUNS = ["next_tasks", "after_batch", "when_free", "final_next_tasks"]


def _group_run(how: str, group: list[Task]) -> Any:
    """A run in which ``group`` becomes ready together.

    ``next_tasks``: a TaskSource batch. ``after_batch`` / ``when_free``: added
    by the running seed with that start policy. ``final_next_tasks``: added
    (``when_free``) by a ``next_tasks()`` that then ends the source.
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
                enqueue_task(group, start="when_free")
                return None

        return Source()

    start: TaskStartPolicy = "after_batch" if how == "after_batch" else "when_free"

    @solver
    def add_group() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(group, start=start)
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
async def test_group_sandbox_startup_does_not_overlap_its_samples(
    tmp_path: Path, how: str
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
            _group_run(how, [a, _boxed("b", events)]),
            model="mockllm/model",
            max_tasks=2,
            log_dir=str(tmp_path),
        )
    assert [log.status for log in logs] == ["success"] * 3
    assert events[:2] == ["init start", "init end"]
    assert sorted(events[2:]) == ["a", "b"]


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
def test_group_sandbox_startup_failure_runs_no_sibling(
    tmp_path: Path, how: str
) -> None:
    events: list[str] = []
    a_ran = anyio.Event()

    async def fail() -> None:
        await _init_waiting_for(a_ran, [])
        raise PrerequisiteError("sandbox prerequisite missing")

    _box_init["task_init"] = fail
    a = Task(
        name="a",
        dataset=[Sample(input="x")],
        solver=[record_and_set(events, "a", a_ran)],
    )
    with pytest.raises(PrerequisiteError, match="sandbox prerequisite missing"):
        eval(
            _group_run(how, [a, _boxed("b", events)]),
            model="mockllm/model",
            max_tasks=3,
            display="none",
            log_dir=str(tmp_path),
        )
    assert events == []


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
        enqueue_task(Task(name="added", dataset=[Sample(input="x")]))

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
            enqueue_task(
                Task(
                    name="b",
                    dataset=[Sample(input="x")],
                    solver=[record_box_limit(seen)],
                    sandbox="task_dispatch_box",
                ),
                start="when_free",
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


@pytest.mark.parametrize("start", ["when_free", "after_batch"])
def test_enqueued_task_with_invalid_config_fails_the_run(
    tmp_path: Path, start: TaskStartPolicy
) -> None:
    # enqueue_task only resolves the task: its configuration (here a reducer
    # needing more epochs than the task has) fails the run when the task
    # starts up, not the caller
    caller_errors: list[str] = []

    @solver
    def add_invalid() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            try:
                enqueue_task(
                    Task(
                        name="invalid",
                        dataset=[Sample(input="x")],
                        epochs=Epochs(2, "pass_at_5"),
                    ),
                    start=start,
                )
            except PrerequisiteError as ex:
                caller_errors.append(str(ex))
            return state

        return solve

    parent = Task(name="parent", dataset=[Sample(input="x")], solver=[add_invalid()])
    with pytest.raises(PrerequisiteError, match="pass_at_5"):
        eval(parent, model="mockllm/model", display="none", log_dir=str(tmp_path))
    assert caller_errors == []


@pytest.mark.parametrize("added", [False, True])
def test_invalid_task_in_group_initialises_no_logger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, added: bool
) -> None:
    # the whole group is configured before any logger is initialised, so an
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

    @solver
    def add_group() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(group, start="when_free")
            return state

        return solve

    tasks = (
        Task(name="seed", dataset=[Sample(input="x")], solver=[add_group()])
        if added
        else group
    )
    with pytest.raises(PrerequisiteError, match="pass_at_3"):
        eval(tasks, model="mockllm/model", display="none", log_dir=str(tmp_path))
    assert inits == (["seed"] if added else [])


def _dup_ids_task() -> Task:
    return Task(name="dup", dataset=[Sample(input="x", id=1), Sample(input="y", id=1)])


@pytest.mark.parametrize(
    "callback,seed_status",
    [("sample_complete", "cancelled"), ("task_complete", "success")],
)
def test_invalid_follow_up_from_task_source_fails_the_run(
    tmp_path: Path, callback: str, seed_status: str
) -> None:
    # a follow-up returned by a TaskSource callback that can't run (duplicate
    # sample ids) fails the run, cancelling the seed if it is still running;
    # the seed is not charged with the error (nor retried for it)
    completes: list[str] = []

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [Task(name="seed", dataset=[Sample(input="x")])]

        async def sample_complete(
            self, sample: EvalSample, task: Task
        ) -> list[Task] | None:
            if callback == "sample_complete" and task.name == "seed":
                return [_dup_ids_task()]
            return None

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            completes.append(f"{log.eval.task}:{log.status}")
            if callback == "task_complete" and log.eval.task == "seed":
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
    assert completes == [f"seed:{seed_status}"]
    assert [
        read_eval_log(str(p), header_only=True).status for p in tmp_path.glob("*.eval")
    ] == [seed_status]


def test_tasks_enqueued_during_next_tasks_follow_its_batch(tmp_path: Path) -> None:
    # when next_tasks() returns a batch, tasks enqueued (when_free) while it
    # ran join the queue after that batch
    started: list[str] = []

    class Source(TaskSource):
        calls = 0

        def initial_tasks(self) -> list[Task]:
            return [_plain("seed", started)]

        async def next_tasks(self) -> list[Task] | None:
            self.calls += 1
            if self.calls == 1:
                enqueue_task(_plain("late", started), start="when_free")
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
