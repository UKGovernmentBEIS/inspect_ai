"""Tests for adding tasks to a running eval via `enqueue_task`.

`enqueue_task` is the in-process primitive: a task added while the eval runs
joins the run's dispatcher under the same run_id, and starts either once every
task already in the run has finished (`start="after_batch"`, the default
outside a `TaskSource` run) or as soon as there is free task capacity
(`start="when_free"`). Here the trigger is a solver (the simplest in-run
caller); the ergonomic trigger surface — hooks, a callback, etc. — is layered on
top and tested separately.
"""

import os
import subprocess
import sys
from contextvars import Context, copy_context
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import anyio
import pytest

from inspect_ai import Task, TaskSource, eval, eval_async, eval_set, task
from inspect_ai._control.max_tasks import set_max_tasks_override, task_dispatcher_stats
from inspect_ai._eval.eval_set_manifest import INSPECT_EVAL_SET_CAPTURE, EvalSetCapture
from inspect_ai._eval.eval_set_selection import (
    EVAL_SET_SELECTION_VERSION,
    INSPECT_EVAL_SET_SELECTION,
    EvalSetSelection,
    EvalSetSelectionTask,
)
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import (
    TaskEnqueuer,
    TaskStartPolicy,
    clear_task_enqueuer,
    enqueue_task,
    register_task_enqueuer,
)
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._eval.task.tasks import Tasks
from inspect_ai._util.content import ContentImage
from inspect_ai._util.registry import _registry
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, RunEnd, RunStart, SampleEnd, TaskStart, hooks
from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.model import ChatMessageUser, get_model
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver
from inspect_ai.util._display import init_display_type


@task
def child() -> Task:
    return Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[generate()],
        name="child",
    )


@solver
def enqueue_child():
    """A solver that adds a `child` task to the running eval, once."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        enqueue_task(child())
        return state

    return solve


def test_enqueue_task_runs_added_task_in_same_run() -> None:
    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child()],
        name="parent",
    )

    logs = eval(parent, model="mockllm/model", display="none")

    # the enqueued child ran alongside the parent, in the same run
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert len({log.eval.run_id for log in logs}) == 1


def test_enqueue_task_chains_across_batches() -> None:
    # each task enqueues the next up to a depth, exercising repeated draining:
    # parent -> gen1 -> gen2, all under one run
    seen: list[str] = []

    @solver
    def spawn_next(depth: int):
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(state.metadata.get("name", "?"))
            if depth > 0:
                enqueue_task(
                    Task(
                        dataset=[Sample(input="hi", target="ok")],
                        solver=[spawn_next(depth - 1)],
                        name=f"gen{depth - 1}",
                        metadata={"name": f"gen{depth - 1}"},
                    )
                )
            return state

        return solve

    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[spawn_next(2)],
        name="parent",
        metadata={"name": "parent"},
    )

    logs = eval(parent, model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1", "parent"]
    assert len({log.eval.run_id for log in logs}) == 1


def test_enqueued_task_media_is_inline_only(tmp_path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"runtime-selected")
    seen: list[str] = []

    @solver
    def child_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            assert not isinstance(state.input, str)
            content = state.input[0].content
            assert isinstance(content, list)
            image = content[0]
            assert isinstance(image, ContentImage)
            seen.append(image.image)
            return state

        return solve

    @solver
    def enqueue_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                Task(
                    dataset=[
                        Sample(
                            id="child",
                            input=[
                                ChatMessageUser(
                                    content=[ContentImage(image=str(secret))]
                                )
                            ],
                        )
                    ],
                    solver=child_solver(),
                    name="child-media",
                )
            )
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="parent", input="parent")],
            solver=enqueue_child(),
            name="parent-media",
        ),
        model="mockllm/model",
        display="none",
    )

    assert seen == [str(secret)]
    child_sample = next(
        sample for log in logs for sample in (log.samples or []) if sample.id == "child"
    )
    content = child_sample.messages[-1].content
    assert isinstance(content, list)
    image = content[0]
    assert isinstance(image, ContentImage)
    assert image.image == str(secret)


def test_enqueued_resolved_task_media_is_inline_only(tmp_path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"runtime-selected")
    seen: list[str] = []

    @solver
    def child_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            assert not isinstance(state.input, str)
            content = state.input[0].content
            assert isinstance(content, list)
            image = content[0]
            assert isinstance(image, ContentImage)
            seen.append(image.image)
            return state

        return solve

    child = Task(
        dataset=[
            Sample(
                id="child",
                input=[ChatMessageUser(content=[ContentImage(image=str(secret))])],
            )
        ],
        solver=child_solver(),
        name="child-resolved-media",
    )
    resolved_child = resolve_tasks(
        child,
        {},
        get_model("mockllm/model"),
        None,
        None,
        None,
    )[0]
    assert resolved_child.input_media_policy == "inline_only"

    @solver
    def enqueue_resolved_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(resolved_child)
            return state

        return solve

    eval(
        Task(
            dataset=[Sample(id="parent", input="parent")],
            solver=enqueue_resolved_child(),
            name="parent-resolved-media",
        ),
        model="mockllm/model",
        display="none",
    )

    assert seen == [str(secret)]
    assert resolved_child.input_media_policy == "inline_only"


def test_enqueue_task_does_not_leak_active_model() -> None:
    # enqueue_task() resolves the added task against every model in the run,
    # calling init_active_model() per model. That resolution must not leak into
    # the caller: a solver running under one model must still see that model via
    # get_model() after enqueuing. Two models make the leak observable — the
    # resolution loop would otherwise leave the *last* model active.
    mismatches: list[tuple[str, str]] = []

    @solver
    def enqueue_and_check():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            before = str(get_model())
            enqueue_task(child())
            after = str(get_model())
            if before != after:
                mismatches.append((before, after))
            return state

        return solve

    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_and_check()],
        name="parent",
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")
    assert mismatches == [], f"active model leaked after enqueue_task: {mismatches}"
    assert all(log.status == "success" for log in logs)


def test_enqueue_task_outside_run_raises() -> None:
    with pytest.raises(RuntimeError, match="while an eval is running"):
        enqueue_task(child())


def test_enqueue_task_from_hooks(tmp_path: Path) -> None:
    # hooks Inspect calls during a task can add tasks. Run-level hooks cannot:
    # on_run_start runs before the run accepts additions and on_run_end after
    # it has finished dispatching, so enqueue_task raises there
    errors: dict[str, str] = {}

    def try_enqueue(hook: str, name: str) -> None:
        try:
            enqueue_task(Task(dataset=[Sample(input="x")], name=name))
        except RuntimeError as ex:
            errors[hook] = str(ex)

    @hooks(name="enqueue_from_hooks", description="Adds tasks from hooks.")
    class EnqueueFromHooks(Hooks):
        async def on_run_start(self, data: RunStart) -> None:
            try_enqueue("on_run_start", "from_run_start")

        async def on_task_start(self, data: TaskStart) -> None:
            if data.spec.task == "parent":
                try_enqueue("on_task_start", "from_task_start")

        async def on_sample_end(self, data: SampleEnd) -> None:
            if data.sample.metadata.get("parent"):
                try_enqueue("on_sample_end", "from_sample_end")

        async def on_run_end(self, data: RunEnd) -> None:
            try_enqueue("on_run_end", "from_run_end")

    try:
        logs = eval(
            Task(dataset=[Sample(input="x", metadata={"parent": True})], name="parent"),
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
        )
    finally:
        del _registry["hooks:enqueue_from_hooks"]

    assert sorted(log.eval.task for log in logs) == [
        "from_sample_end",
        "from_task_start",
        "parent",
    ]
    assert sorted(errors) == ["on_run_end", "on_run_start"]
    assert "can only be called while an eval is running" in errors["on_run_start"]
    assert "finished dispatching" in errors["on_run_end"]


@pytest.mark.parametrize("ending", ["cancelled", "failed_before_dispatch"])
async def test_enqueue_task_from_run_end_hook_of_ended_run_raises(
    monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    # a run cancelled while a task runs (the cancellation is absorbed, so the
    # run returns its logs), or one that fails after registering its enqueuer
    # but before dispatching, has stopped starting tasks: on_run_end cannot
    # add one
    errors: list[str] = []

    @hooks(name="enqueue_from_run_end", description="Adds a task at run end.")
    class EnqueueFromRunEnd(Hooks):
        async def on_run_end(self, data: RunEnd) -> None:
            try:
                enqueue_task(Task(dataset=[Sample(input="x")], name="late"))
            except RuntimeError as ex:
                errors.append(str(ex))

    @solver
    def cancel_run() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            scope.cancel()
            await anyio.sleep_forever()
            return state

        return solve

    def fail_launch_handoff(*args: object, **kwargs: object) -> None:
        raise RuntimeError("launch handoff failed")

    if ending == "failed_before_dispatch":
        monkeypatch.setattr(
            "inspect_ai._eval.eval.emit_launch_handoff", fail_launch_handoff
        )

    init_display_type("none")
    try:
        with anyio.fail_after(60):
            with anyio.CancelScope() as scope:
                if ending == "cancelled":
                    await eval_async(_parent(cancel_run()), model="mockllm/model")
                else:
                    with pytest.raises(RuntimeError, match="launch handoff failed"):
                        await eval_async(_parent(generate()), model="mockllm/model")
    finally:
        del _registry["hooks:enqueue_from_run_end"]

    assert len(errors) == 1
    assert "finished dispatching" in errors[0]


def test_enqueue_task_invalid_start_raises_before_resolving() -> None:
    resolved: list[Tasks] = []

    def resolve(tasks: Tasks) -> list[ResolvedTask]:
        resolved.append(tasks)
        return []

    enqueuer = TaskEnqueuer(run_id="run", _resolve=resolve, _source=None)
    token = register_task_enqueuer(enqueuer)
    try:
        with pytest.raises(ValueError, match="start must be .* not 'now'"):
            enqueue_task(child(), start=cast(TaskStartPolicy, "now"))
    finally:
        clear_task_enqueuer(token)
    assert resolved == []
    assert enqueuer.ready() == []


def _child_signalling(started: anyio.Event) -> Task:
    """A one-sample task whose solver sets `started` when it runs."""

    @solver
    def signal_started() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            started.set()
            return state

        return solve

    return Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=signal_started(),
        name="child",
    )


async def _wait_until_child_held() -> None:
    """Wait until the dispatcher holds one queued task behind one running task."""
    with anyio.fail_after(30):
        while True:
            stats = task_dispatcher_stats()
            if stats is not None and stats.pending == 1 and stats.in_flight == 1:
                return
            await anyio.sleep(0.01)


@solver
def enqueue_child_and_wait(
    start: TaskStartPolicy | None = "when_free", raise_max_tasks: int | None = None
) -> Solver:
    """Enqueue a child and record, in sample metadata, when it started.

    `started_while_parent_ran` is whether the child started (within 30 s)
    before this task finished. With `raise_max_tasks`, `held_at_launch_limit`
    records that the dispatcher held the child queued behind this task, not
    started, before the live limit was raised.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        started = anyio.Event()
        enqueue_task(_child_signalling(started), start=start)
        if raise_max_tasks is not None:
            await _wait_until_child_held()
            state.metadata["held_at_launch_limit"] = not started.is_set()
            set_max_tasks_override(raise_max_tasks)
        with anyio.move_on_after(30):
            await started.wait()
        state.metadata["started_while_parent_ran"] = started.is_set()
        return state

    return solve


def _parent_metadata(logs: list[EvalLog]) -> dict[str, object]:
    parent = next(log for log in logs if log.eval.task == "parent")
    samples = read_eval_log(parent.location).samples
    assert samples is not None
    return samples[0].metadata


def _parent(solver: Solver) -> Task:
    return Task(dataset=[Sample(input="hi", target="ok")], solver=solver, name="parent")


def test_enqueue_task_when_free_starts_during_batch() -> None:
    logs = eval(
        _parent(enqueue_child_and_wait()),
        model="mockllm/model",
        max_tasks=2,
        display="none",
    )
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert len({log.eval.run_id for log in logs}) == 1
    assert _parent_metadata(logs)["started_while_parent_ran"] is True


def test_enqueue_task_when_free_starts_during_eval_set_batch(tmp_path: Path) -> None:
    success, logs = eval_set(
        _parent(enqueue_child_and_wait()),
        log_dir=str(tmp_path),
        model="mockllm/model",
        max_tasks=2,
        retry_attempts=0,
        display="none",
    )
    assert success
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert _parent_metadata(logs)["started_while_parent_ran"] is True


def test_enqueue_task_when_free_starts_during_eval_set_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # a runner enumerates the eval set (capture mode), then a worker runs one
    # selected task; the child that task adds starts alongside it
    manifest = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest))
    with pytest.raises(SystemExit):
        eval_set(
            _parent(enqueue_child_and_wait()),
            log_dir=str(tmp_path / "capture-logs"),
            model="mockllm/model",
            max_tasks=2,
            display="none",
        )
    monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    capture = EvalSetCapture.model_validate_json(manifest.read_bytes())
    selection = EvalSetSelection(
        version=EVAL_SET_SELECTION_VERSION,
        eval_set_id="enqueue-selection",
        tasks=[EvalSetSelectionTask(identifier=capture.tasks[0].identifier)],
    )
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(selection.model_dump_json())
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))

    success, logs = eval_set(
        _parent(enqueue_child_and_wait()),
        log_dir=str(tmp_path / "logs"),
        model="mockllm/model",
        max_tasks=2,
        display="none",
    )

    assert success
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert _parent_metadata(logs)["started_while_parent_ran"] is True


def test_enqueue_task_when_free_waits_for_capacity_until_limit_raised() -> None:
    # at max_tasks=1 the parent holds the only slot; raising the live limit
    # (what `inspect ctl config --max-tasks` does) lets the child start
    try:
        logs = eval(
            _parent(enqueue_child_and_wait(raise_max_tasks=2)),
            model="mockllm/model",
            max_tasks=1,
            display="none",
        )
    finally:
        set_max_tasks_override(None)
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    metadata = _parent_metadata(logs)
    assert metadata["held_at_launch_limit"] is True
    assert metadata["started_while_parent_ran"] is True


@pytest.mark.parametrize("start", ["when_free", None])
def test_enqueue_task_when_free_in_task_source_run(
    start: TaskStartPolicy | None,
) -> None:
    # in a TaskSource run, no `start` means when_free
    logs = eval(
        TaskSource.from_tasks([_parent(enqueue_child_and_wait(start=start))]),
        model="mockllm/model",
        max_tasks=2,
        display="none",
    )
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert _parent_metadata(logs)["started_while_parent_ran"] is True


@pytest.mark.parametrize("start", ["when_free", None])
def test_enqueue_task_when_free_in_task_source_run_at_max_tasks_one(
    start: TaskStartPolicy | None,
) -> None:
    # a TaskSource run at max_tasks=1 also feeds the running dispatcher: the
    # child is queued behind the parent until the limit is raised
    try:
        logs = eval(
            TaskSource.from_tasks(
                [_parent(enqueue_child_and_wait(start=start, raise_max_tasks=2))]
            ),
            model="mockllm/model",
            max_tasks=1,
            display="none",
        )
    finally:
        set_max_tasks_override(None)
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    metadata = _parent_metadata(logs)
    assert metadata["held_at_launch_limit"] is True
    assert metadata["started_while_parent_ran"] is True


@pytest.mark.parametrize(
    "driver,start",
    [("eval", None), ("eval", "after_batch"), ("task_source", "after_batch")],
)
def test_enqueue_task_after_batch_waits_for_every_running_task(
    driver: str, start: TaskStartPolicy | None
) -> None:
    # with free capacity (max_tasks=3), an after_batch child still starts only
    # once the parent and its longer-running sibling have both finished, and
    # before a TaskSource's next_tasks() is consulted
    order: list[str] = []
    parent_done = anyio.Event()

    @solver
    def record(label: str) -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            order.append(label)
            return state

        return solve

    @solver
    def enqueue_child_then_finish() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                Task(
                    dataset=[Sample(input="hi")],
                    solver=record("child-start"),
                    name="child",
                ),
                start=start,
            )
            order.append("parent-end")
            parent_done.set()
            return state

        return solve

    @solver
    def outlast_parent() -> Solver:
        # ends only once the parent's task has finished and this is the one
        # task running, so a child that started when free would start first
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with anyio.fail_after(30):
                await parent_done.wait()
                while (
                    stats := task_dispatcher_stats()
                ) is None or stats.in_flight != 1:
                    await anyio.sleep(0.01)
            order.append("sibling-end")
            return state

        return solve

    seed = [
        _parent(enqueue_child_then_finish()),
        Task(dataset=[Sample(input="hi")], solver=outlast_parent(), name="sibling"),
    ]

    async def next_tasks() -> list[Task] | None:
        order.append("next_tasks")
        return None

    logs = eval(
        TaskSource.from_tasks(seed, next_tasks=next_tasks)
        if driver == "task_source"
        else seed,
        model="mockllm/model",
        max_tasks=3,
        display="none",
    )

    assert sorted(log.eval.task for log in logs) == ["child", "parent", "sibling"]
    assert all(log.status == "success" for log in logs)
    expected = ["parent-end", "sibling-end", "child-start"]
    assert order == expected + (["next_tasks"] if driver == "task_source" else [])


def test_enqueue_task_when_free_group_keeps_sequence_grouping_at_max_tasks_one() -> (
    None
):
    # at max_tasks=1 an added multi-model group runs each task's model fan-outs
    # together, as passing the tasks to eval() would
    starts: list[str] = []
    enqueued: list[bool] = []

    @solver
    def record(label: str) -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            starts.append(label)
            return state

        return solve

    @solver
    def enqueue_group_once() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            starts.append("p")
            if not enqueued:
                enqueued.append(True)
                enqueue_task(
                    [
                        Task(dataset=[Sample(input="x")], solver=record("c"), name="c"),
                        Task(dataset=[Sample(input="x")], solver=record("d"), name="d"),
                    ],
                    start="when_free",
                )
            return state

        return solve

    logs = eval(
        Task(dataset=[Sample(input="x")], solver=enqueue_group_once(), name="p"),
        model=["mockllm/model", "mockllm/model2"],
        max_tasks=1,
        display="none",
    )
    assert len(logs) == 6
    assert all(log.status == "success" for log in logs)
    assert starts == ["p", "p", "c", "c", "d", "d"]


def test_enqueue_task_when_free_child_runs_when_parent_fails() -> None:
    # a when_free child is an independent task: the parent erroring after
    # enqueuing it does not cancel it (this checks independence from the
    # parent, not mid-batch start, which the tests above cover)
    child_ran: list[bool] = []

    @solver
    def record_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            child_ran.append(True)
            return state

        return solve

    @solver
    def enqueue_then_fail() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                Task(dataset=[Sample(input="hi")], solver=record_child(), name="child"),
                start="when_free",
            )
            raise RuntimeError("parent failed")

        return solve

    logs = eval(
        _parent(enqueue_then_fail()), model="mockllm/model", max_tasks=2, display="none"
    )
    by_task = {log.eval.task: log for log in logs}
    assert by_task["parent"].status == "error"
    assert by_task["child"].status == "success"
    assert child_ran == [True]


def test_enqueue_task_when_free_child_is_retried() -> None:
    attempts: list[int] = []

    @solver
    def fail_first_attempt() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise RuntimeError("first attempt fails")
            return state

        return solve

    @solver
    def enqueue_flaky_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                Task(
                    dataset=[Sample(input="hi")],
                    solver=fail_first_attempt(),
                    name="child",
                ),
                start="when_free",
            )
            return state

        return solve

    logs = eval(
        _parent(enqueue_flaky_child()),
        model="mockllm/model",
        max_tasks=2,
        task_retry_attempts=1,
        display="none",
    )
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert attempts == [1, 2]


def test_enqueue_task_after_run_finished_dispatching_raises() -> None:
    # a context copied during the run keeps the run's enqueuer; once the run
    # has finished dispatching, enqueuing through it raises instead of
    # buffering a task that would never run
    contexts: list[Context] = []

    @solver
    def keep_context() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            contexts.append(copy_context())
            return state

        return solve

    logs = eval(_parent(keep_context()), model="mockllm/model", display="none")
    assert [log.status for log in logs] == ["success"]
    with pytest.raises(RuntimeError, match="finished dispatching"):
        contexts[0].run(enqueue_task, child())


async def test_task_enqueuer_close_refuses_enqueue() -> None:
    resolved: list[Tasks] = []

    def resolve(tasks: Tasks) -> list[ResolvedTask]:
        resolved.append(tasks)
        return []

    enqueuer = TaskEnqueuer(run_id="run", _resolve=resolve, _source=None)
    enqueuer.close()
    with pytest.raises(RuntimeError, match="run 'run' has finished dispatching"):
        enqueuer.enqueue(child())
    # refused before resolution, and nothing is buffered
    assert resolved == []
    assert enqueuer.ready() == []
    assert await enqueuer.when_idle() is None


def _resolve_named(tasks: Tasks) -> list[ResolvedTask]:
    return resolve_tasks(tasks, {}, get_model("mockllm/model"), None, None, None)


def _named(names: list[str]) -> list[Task]:
    return [Task(dataset=[Sample(input="hi")], name=name) for name in names]


def _task_names(tasks: list[ResolvedTask] | None) -> list[str] | None:
    return None if tasks is None else [t.task.name for t in tasks]


class _ScriptedSource(TaskSource):
    """``next_tasks()`` returns the scripted batches in order; one call too many raises."""

    def __init__(self, batches: list[list[str] | None]) -> None:
        self.batches = list(batches)

    async def next_tasks(self) -> list[Task] | None:
        batch = self.batches.pop(0)
        return None if batch is None else _named(batch)


@dataclass
class _IdleCase:
    id: str
    source: list[list[str] | None] | None
    """The ``next_tasks()`` script, or ``None`` for a run without a ``TaskSource``."""
    enqueued: list[tuple[str, TaskStartPolicy | None]]
    """Tasks enqueued (with their ``start``) before the dispatcher asks for any."""
    ready: list[str]
    """What ``ready()`` returns after the enqueues."""
    when_idle: list[list[str] | None]
    """What successive ``when_idle()`` calls return; the last is ``None``."""


@pytest.mark.parametrize(
    "case",
    [
        _IdleCase(
            id="after_batch_before_source",
            source=[["s1"], None],
            enqueued=[("a", "after_batch"), ("w", "when_free")],
            ready=["w"],
            when_idle=[["a"], ["s1"], None],
        ),
        _IdleCase(
            id="source_batches_until_none",
            source=[["s1", "s2"], ["s3"], None],
            enqueued=[],
            ready=[],
            when_idle=[["s1", "s2"], ["s3"], None],
        ),
        _IdleCase(
            id="source_empty_list_ends",
            source=[[]],
            enqueued=[],
            ready=[],
            when_idle=[None],
        ),
        _IdleCase(
            id="default_start_with_source_is_when_free",
            source=[None],
            enqueued=[("w", None)],
            ready=["w"],
            when_idle=[None],
        ),
        _IdleCase(
            id="default_start_without_source_is_after_batch",
            source=None,
            enqueued=[("a", None), ("w", "when_free")],
            ready=["w"],
            when_idle=[["a"], None],
        ),
        _IdleCase(
            id="no_source_nothing_added",
            source=None,
            enqueued=[],
            ready=[],
            when_idle=[None],
        ),
    ],
    ids=lambda case: case.id,
)
async def test_task_enqueuer_idle_rule(case: _IdleCase) -> None:
    # the dispatcher's side of the enqueuer, without running an eval: ready()
    # on every cycle, when_idle() once idle, until it returns None
    source = None if case.source is None else _ScriptedSource(case.source)
    enqueuer = TaskEnqueuer(run_id="run", _resolve=_resolve_named, _source=source)
    wakes = 0

    def wake() -> None:
        nonlocal wakes
        wakes += 1

    enqueuer.set_wake(wake)
    for name, start in case.enqueued:
        enqueuer.enqueue(_named([name]), start=start)
    assert wakes == len(case.enqueued)

    assert _task_names(enqueuer.ready()) == case.ready
    assert enqueuer.ready() == []
    assert [_task_names(await enqueuer.when_idle()) for _ in case.when_idle] == (
        case.when_idle
    )
    # every scripted batch was asked for, and none beyond (a further call raises)
    assert source is None or source.batches == []
    # the run is complete: a late enqueue is refused
    with pytest.raises(RuntimeError, match="finished dispatching"):
        enqueuer.enqueue(_named(["late"]))


async def test_task_enqueuer_runs_tasks_enqueued_during_next_tasks() -> None:
    # next_tasks() blocks; tasks enqueued meanwhile are returned after it
    # returns None, and the ended source is never asked again
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
    enqueuer = TaskEnqueuer(run_id="run", _resolve=_resolve_named, _source=source)
    first: list[list[str] | None] = []

    async def idle() -> None:
        first.append(_task_names(await enqueuer.when_idle()))

    async with anyio.create_task_group() as tg:
        tg.start_soon(idle)
        await entered.wait()
        enqueuer.enqueue(_named(["w"]), start="when_free")
        enqueuer.enqueue(_named(["a"]), start="after_batch")
        release.set()

    # each keeps its start policy: the after_batch task waits for the next idle
    # point, once the when_free task has finished
    assert first == [["w"]]
    assert _task_names(await enqueuer.when_idle()) == ["a"]
    assert await enqueuer.when_idle() is None
    assert source.calls == 1
    with pytest.raises(RuntimeError, match="finished dispatching"):
        enqueuer.enqueue(_named(["late"]))


async def test_task_enqueuer_when_idle_returns_when_free_tasks_first() -> None:
    # when_free tasks enqueued after the dispatcher's last ready() (during an
    # await later in its cycle) are returned before after_batch tasks and
    # before next_tasks() is asked, which is called only when nothing is queued
    source = _ScriptedSource([["s1"], None])
    enqueuer = TaskEnqueuer(run_id="run", _resolve=_resolve_named, _source=source)
    enqueuer.enqueue(_named(["a"]), start="after_batch")
    enqueuer.enqueue(_named(["w"]), start="when_free")
    assert [_task_names(await enqueuer.when_idle()) for _ in range(4)] == [
        ["w"],
        ["a"],
        ["s1"],
        None,
    ]
    assert source.batches == []


@pytest.mark.parametrize("start", ["after_batch", "when_free"])
async def test_enqueue_task_cancel_while_preparing_added_group(
    monkeypatch: pytest.MonkeyPatch, start: TaskStartPolicy
) -> None:
    # the run is cancelled (as by Ctrl-C) while the dispatcher prepares an
    # added group of two tasks, right after the second one's log init: the
    # cancellation propagates out of eval_async (the added tasks have no log,
    # so returning normally would report a complete run), and the loggers of
    # both are discarded, releasing their realtime buffers
    loggers: dict[str, TaskLogger] = {}
    discarded: list[str] = []
    init = TaskLogger.init
    discard = TaskLogger.discard

    async def cancelling_init(logger: TaskLogger) -> None:
        loggers[logger.eval.task] = logger
        await init(logger)
        if logger.eval.task == "d":
            scope.cancel()
            await anyio.lowlevel.checkpoint()

    async def track_discard(
        logger: TaskLogger, *, keep_destination: bool = False, keep_buffer: bool = False
    ) -> None:
        discarded.append(logger.eval.task)
        await discard(
            logger, keep_destination=keep_destination, keep_buffer=keep_buffer
        )

    monkeypatch.setattr(TaskLogger, "init", cancelling_init)
    monkeypatch.setattr(TaskLogger, "discard", track_discard)

    @solver
    def enqueue_group() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                [
                    Task(dataset=[Sample(input="x")], name="c"),
                    Task(dataset=[Sample(input="x")], name="d"),
                ],
                start=start,
            )
            return state

        return solve

    init_display_type("none")
    with anyio.fail_after(60):
        with anyio.CancelScope() as scope:
            await eval_async(_parent(enqueue_group()), model="mockllm/model")
            pytest.fail("eval_async returned from a cancelled run")

    assert scope.cancelled_caught
    assert loggers["c"].buffer_db is None
    assert loggers["d"].buffer_db is None
    assert sorted(name for name in discarded if name in ("c", "d")) == ["c", "d"]


async def test_enqueue_task_cancel_while_when_free_child_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the run is cancelled (as by Ctrl-C) while a when_free child is queued
    # behind the parent at max_tasks=1: the run ends without starting the
    # child, the child's logger is cleaned up, and the enqueuer is closed
    cleaned: list[str] = []
    cleanup = TaskLogger.cleanup

    async def track_cleanup(logger: TaskLogger, *, keep_buffer: bool = False) -> None:
        cleaned.append(logger.eval.task)
        await cleanup(logger, keep_buffer=keep_buffer)

    monkeypatch.setattr(TaskLogger, "cleanup", track_cleanup)
    child_started = anyio.Event()
    contexts: list[Context] = []

    @solver
    def enqueue_then_cancel_run() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(_child_signalling(child_started), start="when_free")
            await _wait_until_child_held()
            contexts.append(copy_context())
            scope.cancel()
            await anyio.sleep_forever()
            return state

        return solve

    init_display_type("none")
    with anyio.fail_after(60):
        with anyio.CancelScope() as scope:
            await eval_async(
                _parent(enqueue_then_cancel_run()),
                model="mockllm/model",
                max_tasks=1,
            )

    assert scope.cancel_called
    assert not child_started.is_set()
    assert "child" in cleaned
    assert task_dispatcher_stats() is None
    with pytest.raises(RuntimeError, match="finished dispatching"):
        contexts[0].run(enqueue_task, child())


async def test_enqueue_task_when_free_file_task_log_init_keeps_running_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a task loaded from a file is configured in its file's directory; its
    # log init (which awaits) must run outside that chdir, since chdir is
    # process-wide and a sample of a task already running would see it
    task_dir = tmp_path / "filetask"
    task_dir.mkdir()
    (task_dir / "filetask.py").write_text(
        "from inspect_ai import Task, task\n"
        "from inspect_ai.dataset import Sample\n\n\n"
        "@task\n"
        "def filetask():\n"
        '    return Task(dataset=[Sample(input="x")])\n'
    )
    init_started = anyio.Event()
    init_release = anyio.Event()
    init = TaskLogger.init

    async def held_init(logger: TaskLogger) -> None:
        if logger.eval.task == "filetask":
            init_started.set()
            await init_release.wait()
        await init(logger)

    monkeypatch.setattr(TaskLogger, "init", held_init)
    cwds: list[str] = []

    @solver
    def enqueue_file_task_and_watch_cwd() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            cwds.append(os.getcwd())
            enqueue_task(f"{task_dir / 'filetask.py'}@filetask", start="when_free")
            await init_started.wait()
            cwds.append(os.getcwd())
            init_release.set()
            return state

        return solve

    init_display_type("none")
    with anyio.fail_after(60):
        logs = await eval_async(
            _parent(enqueue_file_task_and_watch_cwd()),
            model="mockllm/model",
            max_tasks=2,
            log_dir=str(tmp_path / "logs"),
        )

    assert sorted(log.eval.task for log in logs) == ["filetask", "parent"]
    assert all(log.status == "success" for log in logs)
    assert cwds[1] == cwds[0]


# Run in a subprocess so the SIGINT cannot reach the test process.
_CTRL_C_WHILE_ADDING_SCRIPT = """
import signal
import tempfile

import anyio

import inspect_ai._display.core.active as active_display
import inspect_ai._eval.run as eval_run_module
import inspect_ai.util._display as display_state
from inspect_ai import Task, TaskSource, enqueue_task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.solver import solver

start_sandboxes = eval_run_module.SandboxManager.start


async def interrupted_start(self, tasks, task_names):
    if any(t.task.name == "added" for t in tasks):
        signal.raise_signal(signal.SIGINT)
        await anyio.sleep(60)
    await start_sandboxes(self, tasks, task_names)


eval_run_module.SandboxManager.start = interrupted_start


@solver
def add_task(start, hold):
    async def solve(state, generate):
        enqueue_task(
            Task(dataset=[Sample(input="x")], name="added", sandbox="local"),
            start=start,
        )
        if hold:
            await anyio.sleep(60)
        return state

    return solve


class InterruptedSource(TaskSource):
    def initial_tasks(self):
        return [Task(dataset=[Sample(input="x")], name="seed")]

    async def next_tasks(self):
        signal.raise_signal(signal.SIGINT)
        await anyio.sleep(60)
        return None


def run(case, display, log_dir):
    active_display._active_display = None
    display_state._display_type = None
    if case == "source":
        tasks = InterruptedSource()
    else:
        tasks = Task(
            dataset=[Sample(input="x")],
            solver=add_task(None if case == "default" else case, case == "when_free"),
            name="parent",
        )
    eval(
        tasks,
        model="mockllm/model",
        max_tasks=1,
        log_dir=log_dir,
        display=display,
        ctl_server=False,
    )


# the Ctrl-C lands while the dispatcher prepares the added task (its sandbox
# startup) or while next_tasks() waits; the interrupted task has no log
expected = {
    "default": [("parent", "success")],
    "after_batch": [("parent", "success")],
    "when_free": [("parent", "cancelled")],
    "source": [("seed", "success")],
}
for case, logs in expected.items():
    for display in ["rich", "plain", "log"]:
        log_dir = tempfile.mkdtemp()
        try:
            run(case, display, log_dir)
        except KeyboardInterrupt as ex:
            assert type(ex) is KeyboardInterrupt, repr(ex)
        else:
            raise AssertionError(f"{case}, {display}: no KeyboardInterrupt")
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
        on_disk = [
            (log.eval.task, log.status)
            for log in (read_eval_log(info.name) for info in list_eval_logs(log_dir))
        ]
        assert on_disk == logs, (case, display, on_disk)

# a later eval() in the same process still runs
active_display._active_display = None
display_state._display_type = None
(log,) = eval(
    Task(dataset=[Sample(input="x")]),
    model="mockllm/model",
    log_dir=tempfile.mkdtemp(),
    display="plain",
)
assert log.status == "success", log.status
"""


@pytest.mark.parametrize("backend", ["asyncio", "trio"], ids=["on_asyncio", "on_trio"])
def test_ctrl_c_while_adding_tasks_raises_keyboard_interrupt(backend: str) -> None:
    """A Ctrl-C while added tasks are prepared or next_tasks() waits ends eval().

    eval() raises KeyboardInterrupt (the CLI exits 1), with the rich, plain
    and log displays, for an added task under each start policy and for a
    TaskSource's next_tasks(). Tasks that already finished keep their logs, a
    task running beside the interrupted preparation is cancelled, and a later
    eval() still runs.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-c", _CTRL_C_WHILE_ADDING_SCRIPT],
        env={**os.environ, "INSPECT_ASYNC_BACKEND": backend},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
