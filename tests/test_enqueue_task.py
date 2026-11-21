"""Tests for adding tasks to a running eval via `enqueue_task`.

`enqueue_task` is the in-process primitive: a task added while the eval runs is
picked up after the current batch completes and run under the same run_id. Here
the trigger is a solver (the simplest in-run caller); the ergonomic trigger
surface — hooks, a callback, etc. — is layered on top and tested separately.
"""

from contextvars import copy_context
from pathlib import Path

import anyio
import pytest

from inspect_ai import Task, TaskSource, eval, eval_set, task
from inspect_ai._eval.eval import _resolve_enqueued_tasks
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import (
    creator_model,
    creator_model_scope,
    enqueue_task,
)
from inspect_ai._eval.task.tasks import Tasks
from inspect_ai._util.background import run_in_background
from inspect_ai._util.content import ContentImage
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, EvalSample, read_eval_log
from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from inspect_ai.model._generate_config import active_generate_config
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
    # enqueue_task() resolves the added task by calling init_active_model(),
    # which sets the active model and the run's generate config. That
    # resolution must not leak into the caller: a solver must still see its
    # own model and generate config after enqueuing. The parent's own
    # generate config makes the leak observable (resolution activates the
    # run's config, which does not have it).
    mismatches: list[tuple[str, str]] = []

    @solver
    def enqueue_and_check():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            before = f"{get_model()} {active_generate_config()}"
            enqueue_task(child())
            after = f"{get_model()} {active_generate_config()}"
            if before != after:
                mismatches.append((before, after))
            return state

        return solve

    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_and_check()],
        name="parent",
        config=GenerateConfig(temperature=0.5),
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")
    assert mismatches == [], f"active model leaked after enqueue_task: {mismatches}"
    assert all(log.status == "success" for log in logs)


def test_enqueue_task_outside_run_raises() -> None:
    with pytest.raises(RuntimeError, match="while an eval is running"):
        enqueue_task(child())


def _child_models(logs: list[EvalLog], name: str = "child") -> list[str]:
    return sorted(log.eval.model for log in logs if log.eval.task == name)


def test_enqueue_task_in_multi_model_eval_adds_one_per_creator() -> None:
    # each creator adds one child, on its own model (not one per run model)
    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child()],
        name="parent",
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")

    assert all(log.status == "success" for log in logs)
    assert _child_models(logs) == ["mockllm/model", "mockllm/model2"]


def test_enqueue_task_keeps_added_task_model() -> None:
    child_with_model = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[generate()],
        name="child",
        model="mockllm/own",
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

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")

    assert all(log.status == "success" for log in logs)
    assert _child_models(logs) == ["mockllm/own", "mockllm/own"]


def test_enqueue_task_under_eval_set_uses_creator_model(tmp_path: Path) -> None:
    # eval_set() runs its tasks in an eval whose model is `none`; an added task
    # that sets no model runs on its creator's model instead of failing
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
        # generate() returned model output (the none model raises instead);
        # mockllm's default output names mockllm/model for every model
        assert (
            child_log.samples[0].output.completion
            == "Default output from mockllm/model"
        )


def test_task_source_additions_resolve_per_run_model() -> None:
    # tasks a TaskSource callback returns, and tasks enqueue_task() adds from
    # inside a callback, resolve once per run model, even though the sample
    # callbacks run inside the creator's attempt
    def added(name: str) -> Task:
        return Task(dataset=[Sample(input="hi", target="ok")], solver=[], name=name)

    class Source(TaskSource):
        def __init__(self) -> None:
            self.pulled = False

        def initial_tasks(self) -> list[Task]:
            return [
                Task(dataset=[Sample(input="hi", target="ok")], solver=[], name="seed")
            ]

        async def sample_complete(
            self, sample: EvalSample, task: Task
        ) -> list[Task] | None:
            if task.name != "seed":
                return None
            enqueue_task(added("enqueued_in_sample_complete"))
            return [added("returned_by_sample_complete")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if log.eval.task != "seed":
                return None
            enqueue_task(added("enqueued_in_task_complete"))
            return [added("returned_by_task_complete")]

        async def next_tasks(self) -> list[Task] | None:
            if self.pulled:
                return None
            self.pulled = True
            enqueue_task(added("enqueued_in_next_tasks"))
            return [added("returned_by_next_tasks")]

    models = ["mockllm/model", "mockllm/model2"]
    logs = eval(Source(), model=models, display="none")

    assert all(log.status == "success" for log in logs)
    # two seed attempts (one per model), each adding once per run model
    per_seed = sorted(models * 2)
    assert _child_models(logs, "enqueued_in_sample_complete") == per_seed
    assert _child_models(logs, "returned_by_sample_complete") == per_seed
    assert _child_models(logs, "enqueued_in_task_complete") == per_seed
    assert _child_models(logs, "returned_by_task_complete") == per_seed
    # next_tasks() is called once
    assert _child_models(logs, "enqueued_in_next_tasks") == models
    assert _child_models(logs, "returned_by_next_tasks") == models


def test_sample_abandoned_additions_resolve_per_run_model() -> None:
    # sample_abandoned runs inside the creator's attempt, like
    # sample_complete; tasks it returns or enqueues still resolve once per run
    # model. Each seed (one per model) cancels its parked sibling sample.
    from inspect_ai._control.cancel import cancel_sample
    from inspect_ai.log._samples import sample_active

    def added(name: str) -> Task:
        return Task(dataset=[Sample(input="hi", target="ok")], solver=[], name=name)

    async def on_abandoned(sample: Sample, epoch: int, task: Task) -> list[Task]:
        enqueue_task(added("enqueued_in_sample_abandoned"))
        return [added("returned_by_sample_abandoned")]

    @solver
    def cancel_parked_sibling() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            active = sample_active()
            assert active is not None
            parked = "b" if state.sample_id == "a" else "a"
            with anyio.fail_after(60):
                while True:
                    probe = await cancel_sample(
                        active.eval_id, parked, 1, action="cancel", dry_run=True
                    )
                    if probe is not None and probe.get("status") == "cancelled":
                        break
                    await anyio.sleep(0.01)
            result = await cancel_sample(active.eval_id, parked, 1, action="cancel")
            assert result is not None
            assert result["ok"] is True and result["changed"] is True
            return state

        return solve

    source = TaskSource.from_tasks(
        [
            Task(
                dataset=[Sample(id="a", input="x"), Sample(id="b", input="x")],
                solver=cancel_parked_sibling(),
                name="seed",
            )
        ],
        sample_abandoned=on_abandoned,
    )
    models = ["mockllm/model", "mockllm/model2"]
    logs = eval(tasks=source, model=models, display="none", max_samples=1)

    assert all(log.status == "success" for log in logs)
    # two seed attempts each abandon one sample, each addition once per run model
    per_seed = sorted(models * 2)
    assert _child_models(logs, "enqueued_in_sample_abandoned") == per_seed
    assert _child_models(logs, "returned_by_sample_abandoned") == per_seed


def test_resolve_enqueued_tasks_outside_attempt_resolves_per_run_model() -> None:
    models = [get_model("mockllm/model"), get_model("mockllm/model2")]
    resolved_child = resolve_tasks(child(), {}, models[0], None, None, None)[0]

    def resolve(tasks: Tasks) -> list[str]:
        resolved = _resolve_enqueued_tasks(
            tasks,
            models=models,
            model_roles=None,
            config=GenerateConfig(),
            sandbox=None,
            sample_shuffle=None,
            checkpoint=None,
            cost_limit=None,
        )
        return [str(r.model) for r in resolved]

    # no attempt running: once per run model, as for a ResolvedTask
    assert resolve(child()) == ["mockllm/model", "mockllm/model2"]
    assert resolve(resolved_child) == ["mockllm/model", "mockllm/model"]

    # inside an attempt: once, under the attempt's model
    with creator_model_scope(models[1]):
        assert resolve(child()) == ["mockllm/model2"]
        assert resolve(resolved_child) == ["mockllm/model"]


def test_enqueue_task_after_creator_attempt_ends_resolves_per_run_model() -> None:
    # a background coroutine started by a creator attempt that adds a task
    # after the attempt has ended is outside any attempt: its task resolves
    # once per run model, not under the ended creator's model
    class Source(TaskSource):
        def __init__(self) -> None:
            self.release: anyio.Event | None = None
            self.all_added: anyio.Event | None = None
            self.ended = 0
            self.added = 0
            self.pulled = False

        def events(self) -> tuple[anyio.Event, anyio.Event]:
            if self.release is None or self.all_added is None:
                self.release, self.all_added = anyio.Event(), anyio.Event()
            return self.release, self.all_added

        def initial_tasks(self) -> list[Task]:
            return [
                Task(
                    dataset=[Sample(input="hi", target="ok")],
                    solver=[defer_enqueue(self)],
                    name="seed",
                )
            ]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if log.eval.task == "seed":
                self.ended += 1
                if self.ended == 2:
                    self.events()[0].set()
            return None

        async def next_tasks(self) -> list[Task] | None:
            # keep the run open until the deferred additions are in, then
            # return one more task so the run drains them
            if self.pulled:
                return None
            self.pulled = True
            with anyio.fail_after(30):
                await self.events()[1].wait()
            return [Task(dataset=[Sample(input="hi")], solver=[], name="last")]

    @solver
    def defer_enqueue(source: Source) -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            release, all_added = source.events()

            async def add_later() -> None:
                with anyio.fail_after(30):
                    await release.wait()
                enqueue_task(child())
                source.added += 1
                if source.added == 2:
                    all_added.set()

            run_in_background(add_later)
            return state

        return solve

    models = ["mockllm/model", "mockllm/model2"]
    logs = eval(Source(), model=models, display="none")

    assert all(log.status == "success" for log in logs)
    # two deferred additions, each once per run model
    assert _child_models(logs) == sorted(models * 2)


async def test_creator_model_expires_when_attempt_ends() -> None:
    model = get_model("mockllm/model")

    # a context copied inside the attempt (as a background task's is) sees the
    # attempt end, whether it returns, raises or is cancelled
    with creator_model_scope(model):
        returned = copy_context()
        assert returned.run(creator_model) is model
    assert returned.run(creator_model) is None

    with pytest.raises(ValueError):
        with creator_model_scope(model):
            raised = copy_context()
            raise ValueError()
    assert raised.run(creator_model) is None

    with anyio.CancelScope() as scope:
        with creator_model_scope(model):
            cancelled = copy_context()
            scope.cancel()
            await anyio.sleep_forever()
    assert cancelled.run(creator_model) is None

    # clearing it for a callback does not end the enclosing attempt
    with creator_model_scope(model):
        with creator_model_scope(None):
            assert creator_model() is None
        assert creator_model() is model
