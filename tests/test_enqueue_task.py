"""Tests for adding tasks to a running eval via `enqueue_task`.

`enqueue_task` is the in-process primitive: a task added while the eval runs is
picked up after the current batch completes and run under the same run_id. Here
the trigger is a solver (the simplest in-run caller); the ergonomic trigger
surface — hooks, a callback, etc. — is layered on top and tested separately.
"""

import os
from pathlib import Path

import pytest

from inspect_ai import SampleSource, Task, eval, eval_async, eval_retry, task
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import enqueue_task
from inspect_ai._util.content import ContentImage
from inspect_ai._util.registry import _registry
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, SampleEnd, TaskEnd, TaskStart, hooks
from inspect_ai.log import (
    EnqueueTaskOrigin,
    EvalLog,
    EvalSample,
    list_eval_logs,
    read_eval_log,
)
from inspect_ai.model import ChatMessageUser, get_model
from inspect_ai.scorer import Score, Target, scorer
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


def _logs_by_task(logs: list[EvalLog]) -> dict[str, EvalLog]:
    by_task = {log.eval.task: log for log in logs}
    assert len(by_task) == len(logs), "task names must be unique"
    return by_task


async def test_enqueued_task_records_creating_task() -> None:
    @solver
    def enqueue_named_child():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                Task(
                    dataset=[Sample(input="hi")],
                    name=f"child-{state.sample_id}-{state.epoch}",
                )
            )
            return state

        return solve

    parent = Task(
        dataset=[Sample(id=1, input="hi"), Sample(id="b", input="hi")],
        solver=[enqueue_named_child()],
        epochs=2,
        name="parent",
    )

    init_display_type("none")
    logs = _logs_by_task(await eval_async(parent, model="mockllm/model"))

    parent_spec = logs.pop("parent").eval
    assert parent_spec.origin is None
    assert {name: log.eval.origin for name, log in logs.items()} == {
        f"child-{sample_id}-{epoch}": EnqueueTaskOrigin(
            eval_id=parent_spec.eval_id,
            task_id=parent_spec.task_id,
        )
        for sample_id in (1, "b")
        for epoch in (1, 2)
    }
    assert {
        log.eval.origin.type for log in logs.values() if log.eval.origin is not None
    } == {"enqueue_task"}


def test_enqueue_task_from_scorer_records_task() -> None:
    @scorer(metrics=[])
    def enqueue_from_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            enqueue_task(child())
            return Score(value=1)

        return score

    parent = Task(
        dataset=[Sample(id="s", input="hi")],
        scorer=enqueue_from_scorer(),
        name="parent",
    )

    logs = _logs_by_task(eval(parent, model="mockllm/model", display="none"))
    assert logs["child"].eval.origin == EnqueueTaskOrigin(
        eval_id=logs["parent"].eval.eval_id,
        task_id=logs["parent"].eval.task_id,
    )


def test_nested_enqueued_tasks_record_their_own_creator() -> None:
    @solver
    def spawn_next(depth: int):
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if depth > 0:
                enqueue_task(
                    Task(
                        dataset=[Sample(id="x", input="hi")],
                        solver=[spawn_next(depth - 1)],
                        name=f"gen{depth - 1}",
                    )
                )
            return state

        return solve

    parent = Task(
        dataset=[Sample(id="x", input="hi")],
        solver=[spawn_next(2)],
        name="parent",
    )

    logs = _logs_by_task(eval(parent, model="mockllm/model", display="none"))
    assert logs["parent"].eval.origin is None
    for name, creator in (("gen1", "parent"), ("gen0", "gen1")):
        origin = logs[name].eval.origin
        assert origin is not None
        assert origin.eval_id == logs[creator].eval.eval_id
        assert origin.task_id == logs[creator].eval.task_id


def test_enqueue_task_from_sample_source_records_task() -> None:
    # next_samples() runs in the task outside any sample, sample_complete() in
    # the completed sample's context; both are the task's own code
    enqueued = False

    async def next_samples() -> list[Sample] | None:
        nonlocal enqueued
        if not enqueued:
            enqueued = True
            enqueue_task(Task(dataset=[Sample(input="hi")], name="from-next-samples"))
        return None

    async def sample_complete(sample: EvalSample) -> list[Sample] | None:
        enqueue_task(Task(dataset=[Sample(input="hi")], name="from-sample-complete"))
        return None

    parent = Task(
        dataset=SampleSource.from_samples(
            [Sample(id="seed", input="hi")],
            next_samples=next_samples,
            sample_complete=sample_complete,
        ),
        name="parent",
    )

    logs = _logs_by_task(eval(parent, model="mockllm/model", display="none"))
    parent_spec = logs["parent"].eval
    assert logs["from-next-samples"].eval.origin == EnqueueTaskOrigin(
        eval_id=parent_spec.eval_id, task_id=parent_spec.task_id
    )
    assert logs["from-sample-complete"].eval.origin == EnqueueTaskOrigin(
        eval_id=parent_spec.eval_id, task_id=parent_spec.task_id
    )


def test_enqueued_task_records_creator_per_model() -> None:
    parent = Task(
        dataset=[Sample(id="p", input="hi")],
        solver=[enqueue_child()],
        name="parent",
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")

    parents = {log.eval.model: log.eval for log in logs if log.eval.task == "parent"}
    children = [log.eval for log in logs if log.eval.task == "child"]
    assert len(parents) == 2
    # the creating sample adds the child for every model in the run; each
    # child records the parent eval that added it
    creators = sorted(
        (spec.model, spec.origin.eval_id)
        for spec in children
        if spec.origin is not None
    )
    assert len(creators) == len(children) == 4
    assert {eval_id for _, eval_id in creators} == {
        spec.eval_id for spec in parents.values()
    }


class _EnqueueFromHooks(Hooks):
    """Adds a task from sample and task hooks (of the `parent` task)."""

    async def on_task_start(self, data: TaskStart) -> None:
        if data.spec.task == "parent":
            enqueue_task(Task(dataset=[Sample(input="hi")], name="from-on-task-start"))

    async def on_sample_end(self, data: SampleEnd) -> None:
        if data.sample.id == "parent-sample":
            enqueue_task(Task(dataset=[Sample(input="hi")], name="from-on-sample-end"))

    async def on_task_end(self, data: TaskEnd) -> None:
        if data.log.eval.task == "parent":
            enqueue_task(Task(dataset=[Sample(input="hi")], name="from-on-task-end"))


async def test_enqueue_task_from_hooks_records_task() -> None:
    @hooks("enqueue_from_hooks", description="enqueue_task() from hooks")
    def enqueue_from_hooks() -> type[_EnqueueFromHooks]:
        return _EnqueueFromHooks

    parent = Task(
        dataset=[Sample(id="parent-sample", input="hi")],
        solver=[enqueue_child()],
        name="parent",
    )
    init_display_type("none")
    try:
        logs = _logs_by_task(await eval_async(parent, model="mockllm/model"))
    finally:
        del _registry["hooks:enqueue_from_hooks"]

    # hooks Inspect calls within the parent's context record it, as its own
    # solver does
    parent_origin = EnqueueTaskOrigin(
        eval_id=logs["parent"].eval.eval_id, task_id=logs["parent"].eval.task_id
    )
    assert logs["from-on-task-start"].eval.origin == parent_origin
    assert logs["from-on-sample-end"].eval.origin == parent_origin
    assert logs["from-on-task-end"].eval.origin == parent_origin
    assert logs["child"].eval.origin == parent_origin


@solver
def fail_first_run() -> Solver:
    """Fails until the file named by ``FLAKY_CHILD_MARKER`` exists, creating it.

    A file rather than module state, since a retry loads the task's file anew.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        marker = Path(os.environ["FLAKY_CHILD_MARKER"])
        if not marker.exists():
            marker.touch()
            raise RuntimeError("first run fails")
        return state

    return solve


@task
def flaky_child() -> Task:
    return Task(dataset=[Sample(id="c", input="hi")], solver=[fail_first_run()])


def test_retried_creating_task_records_each_attempt(tmp_path: Path) -> None:
    # each attempt of a task retried within the run is its own eval; a task an
    # attempt adds records that attempt's eval_id and the shared task_id
    marker = tmp_path / "failed-once"

    @solver
    def enqueue_then_fail_first_run() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            attempt = 2 if marker.exists() else 1
            enqueue_task(
                Task(dataset=[Sample(input="hi")], name=f"child-of-attempt-{attempt}")
            )
            if attempt == 1:
                marker.touch()
                raise RuntimeError("first run fails")
            return state

        return solve

    parent = Task(
        dataset=[Sample(id="p", input="hi")],
        solver=[enqueue_then_fail_first_run()],
        name="parent",
    )
    log_dir = tmp_path / "logs"
    eval(
        parent,
        model="mockllm/model",
        display="none",
        log_dir=str(log_dir),
        task_retry_attempts=1,
    )

    headers = [
        read_eval_log(info, header_only=True) for info in list_eval_logs(str(log_dir))
    ]
    parents = {log.status: log.eval for log in headers if log.eval.task == "parent"}
    children = {log.eval.task: log.eval for log in headers if log.eval.task != "parent"}
    assert sorted(parents) == ["error", "success"]
    assert parents["error"].task_id == parents["success"].task_id
    assert children["child-of-attempt-1"].origin == EnqueueTaskOrigin(
        eval_id=parents["error"].eval_id, task_id=parents["error"].task_id
    )
    assert children["child-of-attempt-2"].origin == EnqueueTaskOrigin(
        eval_id=parents["success"].eval_id, task_id=parents["success"].task_id
    )


def test_task_retry_in_run_keeps_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLAKY_CHILD_MARKER", str(tmp_path / "failed-once"))

    @solver
    def enqueue_flaky_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(flaky_child())
            return state

        return solve

    parent = Task(
        dataset=[Sample(id="p", input="hi")],
        solver=[enqueue_flaky_child()],
        name="parent",
    )
    log_dir = tmp_path / "logs"
    logs = _logs_by_task(
        eval(
            parent,
            model="mockllm/model",
            display="none",
            log_dir=str(log_dir),
            task_retry_attempts=1,
        )
    )

    expected = EnqueueTaskOrigin(
        eval_id=logs["parent"].eval.eval_id,
        task_id=logs["parent"].eval.task_id,
    )
    assert logs["flaky_child"].status == "success"
    assert logs["flaky_child"].eval.origin == expected
    # the failed attempt's log records the same creator
    attempts = [
        read_eval_log(info, header_only=True) for info in list_eval_logs(str(log_dir))
    ]
    child_attempts = [log for log in attempts if log.eval.task == "flaky_child"]
    assert sorted(log.status for log in child_attempts) == ["error", "success"]
    assert all(log.eval.origin == expected for log in child_attempts)


def test_eval_retry_keeps_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLAKY_CHILD_MARKER", str(tmp_path / "failed-once"))

    @solver
    def enqueue_flaky_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(flaky_child())
            return state

        return solve

    parent = Task(
        dataset=[Sample(id="p", input="hi")],
        solver=[enqueue_flaky_child()],
        name="parent",
    )
    logs = _logs_by_task(
        eval(
            parent,
            model="mockllm/model",
            display="none",
            log_dir=str(tmp_path / "logs"),
        )
    )
    failed = logs["flaky_child"]
    assert failed.status == "error"
    assert failed.eval.origin == EnqueueTaskOrigin(
        eval_id=logs["parent"].eval.eval_id,
        task_id=logs["parent"].eval.task_id,
    )

    retried = eval_retry(failed, display="none", log_dir=str(tmp_path / "logs"))[0]
    assert retried.status == "success", retried.error
    assert retried.eval.run_id != failed.eval.run_id
    assert retried.eval.origin == failed.eval.origin
