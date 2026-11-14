"""Tests for adding tasks to a running eval via `enqueue_task`.

`enqueue_task` is the in-process primitive: a task added while the eval runs is
picked up after the current batch completes and run under the same run_id. Here
the trigger is a solver (the simplest in-run caller); the ergonomic trigger
surface — hooks, a callback, etc. — is layered on top and tested separately.
"""

from pathlib import Path

import pytest

from inspect_ai import Task, TaskSource, eval, eval_set, task
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import enqueue_task
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


def _child_models(logs: list[EvalLog]) -> list[str]:
    return sorted(log.eval.model for log in logs if log.eval.task == "child")


def test_enqueue_task_under_eval_set_uses_creator_model(tmp_path: Path) -> None:
    # eval_set() attaches its models to each task and runs them in an eval with
    # no model of its own, so a task added without a model runs with the model
    # of the task that added it -- one child per creator, on that creator's model
    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child()],
        name="parent",
    )

    success, logs = eval_set(
        parent,
        model=["mockllm/model", "mockllm/model2"],
        log_dir=str(tmp_path),
        display="none",
    )

    assert _child_models(logs) == ["mockllm/model", "mockllm/model2"]
    assert success
    for log in logs:
        if log.eval.task != "child":
            continue
        child_log = read_eval_log(log.location)
        assert child_log.status == "success"
        assert child_log.samples is not None
        # generate() returned model output (the none model raises instead)
        assert (
            child_log.samples[0].output.completion
            == "Default output from mockllm/model"
        )


def test_enqueue_task_under_eval_set_keeps_added_task_model(tmp_path: Path) -> None:
    child_with_model = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[generate()],
        name="child",
        model="mockllm/model2",
    )

    @solver
    def enqueue_child_with_model() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(child_with_model)
            return state

        return solve

    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child_with_model()],
        name="parent",
    )

    success, logs = eval_set(
        parent, model="mockllm/model", log_dir=str(tmp_path), display="none"
    )

    assert success
    assert _child_models(logs) == ["mockllm/model2"]


def test_enqueue_task_under_eval_uses_run_models() -> None:
    # eval() gives the run its models, so an added task resolves against those
    # (fanning out across them) rather than its creator's own model
    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child(), generate()],
        name="parent",
        model="mockllm/creator",
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")

    assert all(log.status == "success" for log in logs)
    assert _child_models(logs) == [
        "mockllm/model",
        "mockllm/model",
        "mockllm/model2",
        "mockllm/model2",
    ]


def test_added_task_in_run_without_model_uses_creator_model_or_none() -> None:
    # in a run with no model, a task returned from task_complete (which runs in
    # the completing task) uses that task's model, while one returned from
    # next_tasks() (which runs outside any task) has no creator and resolves to
    # no model, like any other task in the run
    def added_task(name: str) -> Task:
        return Task(dataset=[Sample(input="hi", target="ok")], solver=[], name=name)

    class Source(TaskSource):
        def __init__(self) -> None:
            self.next_tasks_called = False

        def initial_tasks(self) -> list[Task]:
            return [
                Task(
                    dataset=[Sample(input="hi", target="ok")],
                    solver=[],
                    name="parent",
                    model="mockllm/model",
                )
            ]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if log.eval.task == "parent":
                return [added_task("from_task_complete")]
            return None

        async def next_tasks(self) -> list[Task] | None:
            if self.next_tasks_called:
                return None
            self.next_tasks_called = True
            return [added_task("from_next_tasks")]

    logs = eval(Source(), model=None, display="none")

    assert {log.eval.task: log.eval.model for log in logs} == {
        "parent": "mockllm/model",
        "from_task_complete": "mockllm/model",
        "from_next_tasks": "none/none",
    }
