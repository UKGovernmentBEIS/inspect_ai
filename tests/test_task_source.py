"""Tests for driving a running eval from a `TaskSource` (batch-at-a-time).

The source seeds the run with `initial_tasks()`, observes each batch's results
via `sample_complete` / `task_complete`, and produces the next batch from
`next_tasks()` until it returns `None` — all under one run_id.
"""

from pathlib import Path

import anyio
import pytest

from inspect_ai import Task, TaskSource, eval, eval_async, task_source
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import enqueue_task
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.model import get_model
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver
from inspect_ai.util._display import init_display_type


def _task(name: str) -> Task:
    return Task(
        dataset=[Sample(input="hi", target="ok")], solver=[generate()], name=name
    )


class _Generations(TaskSource):
    """Runs `count` tasks one batch at a time; each produced after the prior."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.tasks_seen: list[str] = []
        self.samples_seen = 0
        self._produced = 1  # gen0 is the initial seed

    def initial_tasks(self) -> list[Task]:
        return [_task("gen0")]

    async def sample_complete(self, sample: EvalSample, task: Task) -> None:
        self.samples_seen += 1

    async def task_complete(self, log: EvalLog) -> None:
        self.tasks_seen.append(log.eval.task)

    async def next_tasks(self) -> list[Task] | None:
        if self._produced < self.count:
            name = f"gen{self._produced}"
            self._produced += 1
            return [_task(name)]
        return None


@task_source(name="decorated_generations")
def decorated_generations(count: int = 2) -> TaskSource:
    """A registered, parameterized source (mirrors an `@task` definition)."""
    return _Generations(count)


def test_task_source_runs_batches_in_one_run() -> None:
    source = _Generations(3)
    logs = eval(tasks=source, model="mockllm/model", display="none")

    # all generations ran, under a single run, in order observed by the source
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1", "gen2"]
    assert len({log.eval.run_id for log in logs}) == 1
    assert source.tasks_seen == ["gen0", "gen1", "gen2"]
    assert source.samples_seen == 3  # one sample per task, observed per batch


def test_task_source_single_batch_when_next_is_none() -> None:
    # next_tasks() returns None immediately -> only the seed runs
    logs = eval(tasks=_Generations(1), model="mockllm/model", display="none")
    assert [log.eval.task for log in logs] == ["gen0"]


def test_sample_complete_fires_per_sample_before_task() -> None:
    # sample_complete fires as each sample finishes (one per sample), all before
    # the task's task_complete — not batched at task end
    class _Observer(TaskSource):
        def __init__(self) -> None:
            self.events: list[str] = []

        def initial_tasks(self) -> list[Task]:
            return [
                Task(
                    dataset=[Sample(input="hi", target="ok") for _ in range(3)],
                    solver=[generate()],
                    name="t",
                )
            ]

        async def sample_complete(self, sample: EvalSample, task: Task) -> None:
            self.events.append("sample")

        async def task_complete(self, log: EvalLog) -> None:
            self.events.append("task")

        async def next_tasks(self) -> list[Task] | None:
            return None

    obs = _Observer()
    eval(tasks=obs, model="mockllm/model", display="none")
    assert obs.events == ["sample", "sample", "sample", "task"]


def test_sample_complete_receives_owning_task() -> None:
    # sample_complete is handed the Task the sample ran under (the sample alone
    # doesn't identify its task), so a source can route follow-ups by task.
    seen: list[tuple[str, str]] = []

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [
                Task(dataset=[Sample(input="x")], solver=[generate()], name="a"),
                Task(dataset=[Sample(input="x")], solver=[generate()], name="b"),
            ]

        async def sample_complete(self, sample: EvalSample, task: Task) -> None:
            seen.append((task.name, str(sample.input)))

        async def next_tasks(self) -> list[Task] | None:
            return None

    eval(tasks=_Src(), model="mockllm/model", display="none")
    assert sorted(name for name, _ in seen) == ["a", "b"]


def test_task_source_factory_seed_and_callbacks() -> None:
    # task_source() builds a TaskSource from a seed + callbacks (no subclass).
    # next_tasks closes over shared state to produce two more generations.
    produced = [1]
    tasks_seen: list[str] = []
    samples_seen = 0

    async def next_tasks() -> list[Task] | None:
        if produced[0] < 3:
            name = f"gen{produced[0]}"
            produced[0] += 1
            return [_task(name)]
        return None

    async def on_sample(sample: EvalSample, task: Task) -> None:
        nonlocal samples_seen
        samples_seen += 1

    async def on_task(log: EvalLog) -> None:
        tasks_seen.append(log.eval.task)

    source = TaskSource.from_tasks(
        [_task("gen0")],
        next_tasks=next_tasks,
        sample_complete=on_sample,
        task_complete=on_task,
    )
    logs = eval(tasks=source, model="mockllm/model", display="none")

    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1", "gen2"]
    assert len({log.eval.run_id for log in logs}) == 1
    assert tasks_seen == ["gen0", "gen1", "gen2"]
    assert samples_seen == 3


def test_task_source_factory_seed_only_runs_once() -> None:
    # omitting next_tasks stops after the seed (equivalent to a plain list)
    logs = eval(
        tasks=TaskSource.from_tasks([_task("only")]),
        model="mockllm/model",
        display="none",
    )
    assert [log.eval.task for log in logs] == ["only"]


def test_task_complete_returning_tasks_chains_generations() -> None:
    # the simplest source: return follow-up tasks straight from task_complete,
    # no next_tasks() and no manual buffer. The run chains until a completion
    # returns nothing, all under one run_id.
    class _Chain(TaskSource):
        def __init__(self, count: int) -> None:
            self.count = count
            self._produced = 1  # gen0 is the seed

        def initial_tasks(self) -> list[Task]:
            return [_task("gen0")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if self._produced < self.count:
                name = f"gen{self._produced}"
                self._produced += 1
                return [_task(name)]
            return None

    logs = eval(tasks=_Chain(3), model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1", "gen2"]
    assert len({log.eval.run_id for log in logs}) == 1


def test_factory_task_complete_returning_tasks() -> None:
    # same pattern via the task_source() factory: task_complete returns followups
    produced = [1]

    async def on_task(log: EvalLog) -> list[Task] | None:
        if produced[0] < 2:
            name = f"gen{produced[0]}"
            produced[0] += 1
            return [_task(name)]
        return None

    logs = eval(
        tasks=TaskSource.from_tasks([_task("gen0")], task_complete=on_task),
        model="mockllm/model",
        display="none",
    )
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1"]


async def _run_live_injection(
    task_retry_attempts: int = 0,
) -> tuple[list[EvalLog], list[str]]:
    # Discriminates live injection from batch-at-a-time: a task injected mid-run
    # must start while another task is still in flight. Here "blocker" parks
    # until "injected" releases it, and "injected" is only enqueued (by
    # "injector") once the run is already underway. Under batch-at-a-time the
    # injected task wouldn't run until the seed batch completed — but the seed
    # can't complete until the injected task releases the blocker, so only live
    # injection lets this finish (the fail_after turns a regression into a fast
    # failure instead of a hang).
    released = anyio.Event()
    order: list[str] = []

    @solver
    def blocker() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            order.append("blocker-start")
            with anyio.fail_after(10):
                await released.wait()
            order.append("blocker-end")
            return state

        return solve

    @solver
    def releaser() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            order.append("injected")
            released.set()
            return state

        return solve

    @solver
    def injector() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                Task(dataset=[Sample(input="x")], solver=[releaser()], name="injected")
            )
            return state

        return solve

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [
                Task(dataset=[Sample(input="x")], solver=[blocker()], name="blocker"),
                Task(dataset=[Sample(input="x")], solver=[injector()], name="injector"),
            ]

        async def next_tasks(self) -> list[Task] | None:
            return None

    init_display_type("none")
    logs = await eval_async(
        tasks=_Src(),
        model="mockllm/model",
        max_tasks=2,
        task_retry_attempts=task_retry_attempts,
    )

    assert sorted(log.eval.task for log in logs) == ["blocker", "injected", "injector"]
    assert len({log.eval.run_id for log in logs}) == 1
    # blocker only reaches its end if the injected task ran while it was blocked
    assert "blocker-end" in order
    assert all(log.status == "success" for log in logs)
    return logs, order


async def test_live_injection_runs_concurrently_with_in_flight_task() -> None:
    await _run_live_injection()


async def test_live_injection_works_with_task_retry_attempts() -> None:
    # task_retry_attempts routes through run_task_retry_attempts (the recommended
    # path). The TaskSource feed must still be honoured there — without it the
    # injected task never runs and the blocker hangs until fail_after fires.
    await _run_live_injection(task_retry_attempts=1)


def test_initial_tasks_runs_in_active_model_context() -> None:
    # initial_tasks() must run inside the initialized model/role context, like a
    # @task factory resolved by eval(). Before the seed was produced there,
    # get_model() with no args raised "No model specified" / saw stale context.
    seen: list[str] = []

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            seen.append(str(get_model()))
            return [_task("seed")]

        async def next_tasks(self) -> list[Task] | None:
            return None

    logs = eval(tasks=_Src(), model="mockllm/model", display="none")
    assert seen == ["mockllm/model"]
    assert [log.eval.task for log in logs] == ["seed"]
    assert all(log.status == "success" for log in logs)


def test_initial_tasks_parallel1_preserves_sequence_grouping() -> None:
    # With parallel == 1 (max_tasks=1) and multiple models, a TaskSource seed of
    # [a, b] must behave like passing [a, b] to eval(): every fan-out of `a`
    # runs before any fan-out of `b` (sequence grouping). The live injection path
    # would instead interleave them (a/m1, b/m1, a/m2, b/m2), so parallel==1
    # falls through to the batch path.
    starts: list[str] = []

    @solver
    def record(label: str) -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            starts.append(label)
            return state

        return solve

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [
                Task(dataset=[Sample(input="x")], solver=[record("a")], name="a"),
                Task(dataset=[Sample(input="x")], solver=[record("b")], name="b"),
            ]

        async def next_tasks(self) -> list[Task] | None:
            return None

    logs = eval(
        tasks=_Src(),
        model=["mockllm/model", "mockllm/model2"],
        max_tasks=1,
        display="none",
    )
    assert len(logs) == 4
    assert all(log.status == "success" for log in logs)
    # all `a` executions precede all `b` executions (no interleaving)
    assert starts == ["a", "a", "b", "b"], starts
    assert len({log.eval.run_id for log in logs}) == 1


def test_task_source_decorator_instance() -> None:
    # calling a @task_source-decorated function yields a tagged TaskSource that
    # eval() drives like any source
    logs = eval(tasks=decorated_generations(2), model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1"]


def test_task_source_decorator_passed_as_function() -> None:
    # passing the decorated function itself (not an instance) resolves + runs it
    logs = eval(tasks=decorated_generations, model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1"]


def test_task_source_load_by_registered_name() -> None:
    # resolve a registered source by name, like inspect eval <name>
    logs = eval(tasks="decorated_generations", model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1"]  # default count=2


def test_task_source_load_by_name_with_args() -> None:
    # task args parameterize the source (mirrors @task / -T args)
    logs = eval(
        tasks="decorated_generations",
        model="mockllm/model",
        display="none",
        task_args={"count": 3},
    )
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1", "gen2"]


def test_task_source_load_from_file(tmp_path: Path) -> None:
    # file.py@name spec resolves a @task_source defined in that file
    src = tmp_path / "rl_source.py"
    src.write_text(
        "from inspect_ai import Task, TaskSource, task_source\n"
        "from inspect_ai.dataset import Sample\n"
        "from inspect_ai.solver import generate\n"
        "\n"
        "@task_source\n"
        "def my_source() -> TaskSource:\n"
        "    return TaskSource.from_tasks(\n"
        "        [Task(dataset=[Sample(input='hi', target='ok')], "
        "solver=[generate()], name='seed')]\n"
        "    )\n"
    )
    logs = eval(
        tasks=f"{src.as_posix()}@my_source", model="mockllm/model", display="none"
    )
    assert [log.eval.task for log in logs] == ["seed"]


def test_task_source_rejected_outside_eval() -> None:
    # a TaskSource isn't a concrete, resumable task list — resolving one (e.g.
    # via eval_set / eval_retry / score) is a clear error that points to eval()
    with pytest.raises(ValueError, match="only supported by `eval"):
        resolve_tasks(_Generations(1), {}, get_model("mockllm/model"), None, None, None)


def test_task_source_name_rejected_outside_eval() -> None:
    # the same clear error fires for a spec/name that *refers* to a source (the
    # CLI path, e.g. `inspect eval-set file.py@source`) — not a confusing
    # "task not found"
    with pytest.raises(ValueError, match="only supported by `eval"):
        resolve_tasks(
            "decorated_generations", {}, get_model("mockllm/model"), None, None, None
        )
