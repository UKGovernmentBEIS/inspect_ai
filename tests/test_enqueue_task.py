"""Tests for adding tasks to a running eval via `enqueue_task`.

`enqueue_task` is the in-process primitive: a task added while the eval runs is
picked up after the current batch completes (or, with `start="when_free"`, as
soon as there is free task capacity) and run under the same run_id. Here the
trigger is a solver (the simplest in-run caller); the ergonomic trigger surface
— hooks, a callback, etc. — is layered on top and tested separately.
"""

from pathlib import Path

import anyio
import pytest

from inspect_ai import Task, TaskSource, eval, eval_set, task
from inspect_ai._control.max_tasks import set_max_tasks_override
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import TaskStartPolicy, enqueue_task
from inspect_ai._util.content import ContentImage
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.model import ChatMessageUser, get_model
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


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


@solver
def enqueue_child_and_wait(
    start: TaskStartPolicy = "when_free", raise_max_tasks: int | None = None
) -> Solver:
    """Enqueue a child and record, in sample metadata, when it started.

    `started_while_parent_ran` is whether the child started before this task
    finished (waiting up to 30 s for `when_free`, 1 s for `after_batch`). With
    `raise_max_tasks`, `held_at_launch_limit` records that the child had not
    started within 1 s at the launch limit, before the live limit was raised.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        started = anyio.Event()
        enqueue_task(_child_signalling(started), start=start)
        if raise_max_tasks is not None:
            with anyio.move_on_after(1):
                await started.wait()
            state.metadata["held_at_launch_limit"] = not started.is_set()
            set_max_tasks_override(raise_max_tasks)
        with anyio.move_on_after(30 if start == "when_free" else 1):
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


def test_enqueue_task_when_free_in_task_source_run() -> None:
    logs = eval(
        TaskSource.from_tasks([_parent(enqueue_child_and_wait())]),
        model="mockllm/model",
        max_tasks=2,
        display="none",
    )
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert _parent_metadata(logs)["started_while_parent_ran"] is True


def test_enqueue_task_after_batch_waits_for_batch() -> None:
    # the default is unchanged: the child does not start while the parent runs,
    # even with free capacity, and runs once the parent's batch has finished
    logs = eval(
        _parent(enqueue_child_and_wait(start="after_batch")),
        model="mockllm/model",
        max_tasks=2,
        display="none",
    )
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert _parent_metadata(logs)["started_while_parent_ran"] is False


def test_enqueue_task_when_free_in_task_source_run_at_max_tasks_one() -> None:
    # a TaskSource run at max_tasks=1 goes through the batch path, not the
    # live one; a when_free child is still held until the limit is raised
    try:
        logs = eval(
            TaskSource.from_tasks([_parent(enqueue_child_and_wait(raise_max_tasks=2))]),
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
