"""Tests for driving a running eval from a `TaskSource`.

The source seeds the run with `initial_tasks()`, observes results via
`sample_complete` / `task_complete`, and produces the next batch from
`next_tasks()` (called when no task is queued or running) until it returns
`None` — all under one run_id.
"""

import gc
import os
import subprocess
import sys
import weakref
from pathlib import Path
from typing import Any, Awaitable, Callable

import anyio
import pytest
from test_helpers.ctl import ctl_request, ctl_task_directive, ctl_tasks
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, TaskSource, eval, eval_async, task_source
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import TaskRecord, enqueue_task, get_run_queue
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, EvalSample, list_eval_logs, read_eval_log_async
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


def test_sample_complete_fires_for_per_sample_cancel() -> None:
    """A per-sample `cancel` interrupt still notifies the TaskSource.

    The task keeps running after an operator cancels one sample, so the
    source hears about it (as cancelled) like any other completing sample.
    """
    from inspect_ai.log._samples import sample_active

    completed: list[str] = []

    @solver(name="task_source_self_cancel_solver")
    def self_cancel_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == "a":
                active = sample_active()
                assert active is not None
                active.interrupt("cancel")
                await anyio.sleep(10)
            return state

        return solve

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [
                Task(
                    dataset=[Sample(id="a", input="x"), Sample(id="b", input="x")],
                    solver=self_cancel_solver(),
                    name="per_sample_cancel",
                )
            ]

        async def sample_complete(self, sample: EvalSample, task: Task) -> None:
            completed.append(str(sample.id))

        async def next_tasks(self) -> list[Task] | None:
            return None

    logs = eval(tasks=_Src(), model="mockllm/model", display="none")
    assert logs[0].status == "success"
    assert sorted(completed) == ["a", "b"]


def test_sample_complete_skipped_for_task_cancel() -> None:
    """A task-level cancel does not notify the TaskSource for the unwound sample.

    The sample completion block is shielded while a cancellation is being
    resolved, so delivering the sample there would run user callback code
    uncancellable (a callback that blocks would hang ^C). The task's unwind
    also means any follow-up tasks could never run under it; the source still
    sees the sample in the log handed to `task_complete`.
    """
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states

    completed: list[str] = []
    tasks_completed: list[str] = []

    @solver(name="task_source_task_cancel_solver")
    def task_cancel_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            result = ctl_cancel_task(get_eval_states()[0].task_id, action="cancel")
            assert result is not None and result["ok"] is True
            await anyio.sleep(10)
            return state

        return solve

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [
                Task(
                    dataset=[Sample(id="a", input="x")],
                    solver=task_cancel_solver(),
                    name="task_cancel",
                )
            ]

        async def sample_complete(self, sample: EvalSample, task: Task) -> None:
            completed.append(str(sample.id))

        async def task_complete(self, log: EvalLog) -> None:
            tasks_completed.append(log.eval.task)

        async def next_tasks(self) -> list[Task] | None:
            return None

    logs = eval(tasks=_Src(), model="mockllm/model", display="none")
    log = logs[0]
    assert log.status == "error"
    assert log.error is not None and "cancelled by user" in log.error.message
    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].error is not None
    assert completed == []
    assert tasks_completed == ["task_cancel"]


def test_sample_abandoned_fires_for_queued_sample_cancel() -> None:
    """Cancelling a sample still parked in the queue notifies the TaskSource.

    With one slot, whichever seed wins it cancels the parked sibling before it
    starts. Nothing is ever logged for the sibling, so the source hears about
    it via `sample_abandoned` (with the sample, epoch and task) rather than
    `sample_complete`, which fires only for the sample that ran.
    """
    from inspect_ai._control.cancel import cancel_sample
    from inspect_ai._control.eval_state import get_eval_states

    completed: list[str] = []
    abandoned: list[tuple[str, int, str]] = []
    ran: list[str] = []

    async def on_complete(sample: EvalSample, task: Task) -> list[Task] | None:
        completed.append(str(sample.id))
        return None

    async def on_abandoned(sample: Sample, epoch: int, task: Task) -> None:
        abandoned.append((str(sample.id), epoch, task.name))

    @solver(name="task_source_queued_cancel_solver")
    def cancel_parked_sibling() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            ran.append(str(state.sample_id))
            parked = "b" if state.sample_id == "a" else "a"
            eval_id = get_eval_states()[0].eval_id
            with anyio.fail_after(60):
                while True:
                    probe = await cancel_sample(
                        eval_id, parked, 1, action="cancel", dry_run=True
                    )
                    if probe is not None and probe.get("status") == "cancelled":
                        break
                    await anyio.sleep(0.01)
            result = await cancel_sample(eval_id, parked, 1, action="cancel")
            assert result is not None
            assert result["ok"] is True and result["changed"] is True
            return state

        return solve

    source = TaskSource.from_tasks(
        [
            Task(
                dataset=[Sample(id="a", input="x"), Sample(id="b", input="x")],
                solver=cancel_parked_sibling(),
                name="queued_cancel",
            )
        ],
        sample_complete=on_complete,
        sample_abandoned=on_abandoned,
    )
    logs = eval(tasks=source, model="mockllm/model", display="none", max_samples=1)
    assert logs[0].status == "success"
    (running,) = ran
    parked = "b" if running == "a" else "a"
    assert completed == [running]
    assert abandoned == [(parked, 1, "queued_cancel")]
    assert [str(s.id) for s in (logs[0].samples or [])] == [running]


def test_task_cancel_reaches_suspended_sample_abandoned() -> None:
    """A task stays cancellable while its `sample_abandoned` callback blocks.

    The hook fires after the run's terminal count, so for the task's last
    sample the counters already read complete when the callback runs. A
    TaskSource-driven eval must therefore not stamp itself finished on the
    counters alone (it registers as dynamic, like a SampleSource task):
    otherwise `ctl task cancel` would no-op as "task already finished" while
    the callback held the fanout open. The cancel is issued from inside the
    suspended callback; it must be accepted, unwind the callback (its cleanup
    runs) and end the eval.
    """
    from inspect_ai._control.cancel import CancelTaskResult, cancel_sample
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states

    attempts = 0
    cancel_results: list[CancelTaskResult | None] = []
    callback_cleanup: list[str] = []

    @solver(name="task_source_drain_window_error_solver")
    def erroring_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("boom")

        return solve

    async def cleanup(state: TaskState) -> None:
        # per-sample cancel in the errored attempt's drain window: the retry
        # is suppressed and the run abandoned without a log record
        if attempts == 1:
            eval_id = get_eval_states()[0].eval_id
            result = await cancel_sample(eval_id, "a", 1, action="cancel")
            assert result is not None and result["ok"] is True

    async def on_abandoned(sample: Sample, epoch: int, task: Task) -> None:
        # the task's only sample is counted terminal by now; the task-level
        # cancel must still be accepted and reach this suspended callback
        cancel_results.append(
            ctl_cancel_task(get_eval_states()[0].task_id, action="cancel")
        )
        try:
            await anyio.sleep(10)
        finally:
            callback_cleanup.append(str(sample.id))

    source = TaskSource.from_tasks(
        [
            Task(
                dataset=[Sample(id="a", input="x")],
                solver=erroring_solver(),
                cleanup=cleanup,
                name="cancel_during_abandoned",
            )
        ],
        sample_abandoned=on_abandoned,
    )
    logs = eval(tasks=source, model="mockllm/model", display="none", retry_on_error=2)
    assert attempts == 1
    (cancel,) = cancel_results
    assert cancel is not None and cancel["ok"] is True
    assert cancel["changed"] is True, cancel
    assert callback_cleanup == ["a"]
    log = logs[0]
    assert log.status == "error"
    assert log.error is not None and "cancelled by user" in log.error.message


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


async def test_task_complete_returned_task_error_propagates(tmp_path: Path) -> None:
    # an error adding a follow-up task that task_complete returned (here a
    # sandbox type that is not registered) ends the run, as it does for
    # enqueue_task; only an exception from the callback itself is logged
    class _BadChild(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_task("gen0")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if log.eval.task == "gen0":
                return [
                    Task(
                        dataset=[Sample(input="hi", target="ok")],
                        solver=[generate()],
                        name="gen1",
                        sandbox="not-a-registered-sandbox",
                    )
                ]
            return None

    with pytest.raises(ValueError, match="not-a-registered-sandbox"):
        await eval_async(
            tasks=_BadChild(),
            model="mockllm/model",
            log_dir=str(tmp_path),
        )


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
    # The TaskSource feed must be honoured when retries are enabled — without it
    # the injected task never runs and the blocker hangs until fail_after fires.
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


# -- one queue, one dispatcher (design/task-dispatch.md) -----------------------


def _hook_task(name: str, hook: Callable[[], Awaitable[None]]) -> Task:
    @solver
    def run_hook() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await hook()
            return state

        return solve

    return Task(dataset=[Sample(input="x")], solver=[run_hook()], name=name)


async def _noop() -> None:
    pass


def _record(name: str) -> TaskRecord:
    queue = get_run_queue()
    assert queue is not None
    return next(r for r in queue.records if r.task == name)


async def test_task_added_while_next_tasks_blocks_starts_first(tmp_path: Path) -> None:
    started: list[str] = []

    def recording(name: str) -> Task:
        async def record() -> None:
            started.append(name)

        return _hook_task(name, record)

    class _Src(TaskSource):
        calls = 0

        def initial_tasks(self) -> list[Task]:
            return [recording("seed")]

        async def next_tasks(self) -> list[Task] | None:
            self.calls += 1
            if self.calls > 1:
                return None
            # a task added while the call blocks waits for it to return
            enqueue_task(recording("added"))
            await anyio.sleep(0)
            assert _record("added").phase == "queued"
            return [recording("returned")]

    init_display_type("none")
    logs = await eval_async(
        _Src(), model="mockllm/model", max_tasks=1, log_dir=str(tmp_path)
    )
    assert started == ["seed", "added", "returned"]
    assert [log.eval.task for log in logs] == ["seed", "added", "returned"]


async def test_next_tasks_empty_list_ends_the_source(tmp_path: Path) -> None:
    class _Src(TaskSource):
        calls = 0

        def initial_tasks(self) -> list[Task]:
            return [_task("seed")]

        async def next_tasks(self) -> list[Task] | None:
            self.calls += 1
            return []

    source = _Src()
    init_display_type("none")
    logs = await eval_async(source, model="mockllm/model", log_dir=str(tmp_path))
    assert [log.eval.task for log in logs] == ["seed"]
    assert source.calls == 1


class _WaitForReports(TaskSource):
    """Seeds tasks and returns from next_tasks() only once each has been reported."""

    def __init__(self, seed: list[Task], reports_needed: int) -> None:
        self.seed = seed
        self.reports: list[EvalLog] = []
        self.reports_needed = reports_needed
        self._done: anyio.Event | None = None

    def initial_tasks(self) -> list[Task]:
        return self.seed

    def done(self) -> anyio.Event:
        if self._done is None:
            self._done = anyio.Event()
        return self._done

    async def task_complete(self, log: EvalLog) -> list[Task] | None:
        self.reports.append(log)
        if len(self.reports) >= self.reports_needed:
            self.done().set()
        return None

    async def next_tasks(self) -> list[Task] | None:
        with anyio.fail_after(20):
            await self.done().wait()
        return None


@pytest.mark.parametrize("retries", [0, 2])
async def test_every_attempt_is_reported_including_failed_log_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retries: int
) -> None:
    init = TaskLogger.init

    async def failing_init(self: TaskLogger) -> None:
        if self.eval.task == "B":
            raise OSError("cannot start log")
        await init(self)

    monkeypatch.setattr(TaskLogger, "init", failing_init)
    source = _WaitForReports([_task("A"), _task("B")], reports_needed=retries + 2)
    init_display_type("none")
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=retries,
    )
    b_reports = [log for log in source.reports if log.eval.task == "B"]
    assert len(b_reports) == retries + 1
    assert all(
        log.status == "error"
        and log.error is not None
        and "cannot start log" in log.error.message
        for log in b_reports
    )
    by_task = {log.eval.task: log for log in logs}
    assert by_task["A"].status == "success"
    assert by_task["B"].status == "error"


@pytest.mark.parametrize("failure", ["header", "final"])
async def test_attempt_whose_log_storage_failed_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    method = "log_start" if failure == "header" else "log_finish"
    original = getattr(TaskLogger, method)

    async def failing(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        if self.eval.task == "B":
            raise OSError(f"{method} failed")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, method, failing)
    source = _WaitForReports([_task("A"), _task("B")], reports_needed=2)
    init_display_type("none")
    logs = await eval_async(source, model="mockllm/model", log_dir=str(tmp_path))
    [b_report] = [log for log in source.reports if log.eval.task == "B"]
    [b_log] = [log for log in logs if log.eval.task == "B"]
    assert b_report.status == "error"
    assert b_report.error is not None
    assert f"{method} failed" in b_report.error.message
    assert b_report.error.message == (b_log.error.message if b_log.error else None)


async def test_cancel_of_queued_task_aborts_it_before_it_starts(
    tmp_path: Path,
) -> None:
    async def cancel_b() -> None:
        queue = get_run_queue()
        assert queue is not None
        b = _record("B")
        assert b.phase == "queued"
        queue.cancel(b)
        assert b.abort_requested

    source = _WaitForReports(
        [_hook_task("A", cancel_b), _hook_task("B", _noop)], reports_needed=2
    )
    init_display_type("none")
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )
    by_task = {log.eval.task: log for log in logs}
    assert by_task["A"].status == "success"
    b = by_task["B"]
    assert b.status == "error"
    assert b.error is not None
    assert "Task cancelled by user (abort)" in b.error.message
    assert b.location == ""
    # reported once, never retried, and no log file was created for it
    assert [log.eval.task for log in source.reports].count("B") == 1
    assert len(list(tmp_path.glob("*_B_*"))) == 0


async def test_cancel_of_attempt_before_it_registers_aborts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init = TaskLogger.init
    init_entered = anyio.Event()

    async def held_init(self: TaskLogger) -> None:
        if self.eval.task == "B":
            init_entered.set()
            await anyio.sleep_forever()
        await init(self)

    async def cancel_b() -> None:
        with anyio.fail_after(10):
            await init_entered.wait()
        b = _record("B")
        assert b.phase == "attempt"
        assert b.reached == "added"
        queue = get_run_queue()
        assert queue is not None
        queue.cancel(b)

    monkeypatch.setattr(TaskLogger, "init", held_init)
    source = _WaitForReports([_hook_task("A", cancel_b), _hook_task("B", _noop)], 2)
    init_display_type("none")
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=2,
        task_retry_attempts=1,
    )
    [b] = [log for log in logs if log.eval.task == "B"]
    assert b.status == "error"
    assert b.error is not None
    assert "Task cancelled by user (abort)" in b.error.message
    assert [log.eval.task for log in source.reports].count("B") == 1


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("verb", ["cancel", "drain"])
async def test_ctl_cancel_of_starting_attempt_aborts_it_when_it_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str, empty: bool
) -> None:
    # B's attempt is starting (logger.init() held): a cancel or drain through
    # the control channel is deferred, B's startup runs undisturbed, and B is
    # aborted when it registers, before any sample, keeping its error log.
    # With `empty`, B's sample selection is empty, so it registers as already
    # finished; the abort accepted before that still applies
    init = TaskLogger.init
    init_entered = anyio.Event()
    release = anyio.Event()
    seen: dict[str, Any] = {}
    b_ran: list[bool] = []

    async def held_init(self: TaskLogger) -> None:
        if self.eval.task == "B":
            init_entered.set()
            with anyio.CancelScope(shield=True):
                await release.wait()
        await init(self)

    async def run_b() -> None:
        b_ran.append(True)

    async def cancel_b() -> None:
        with anyio.fail_after(10):
            await init_entered.wait()
        try:
            task_id = (await ctl_tasks())["B"]["task_id"]
            seen["status"] = (await ctl_tasks())["B"]["status"]
            seen["first"] = await ctl_task_directive(task_id, verb)
            seen["repeats"] = [
                (await ctl_task_directive(task_id, repeat, **params))[1].get("reason")
                for repeat in ("cancel", "drain")
                for params in ({}, {"dry_run": True})
            ]
        finally:
            release.set()
        with anyio.fail_after(10):
            await _record("B").ended.wait()
        seen["finished_status"] = (await ctl_tasks())["B"]["status"]

    monkeypatch.setattr(TaskLogger, "init", held_init)
    a = _hook_task("A", cancel_b)
    if empty:
        # A keeps one sample in the selection, B (one sample) none
        a = Task(
            dataset=[Sample(input=str(i)) for i in range(3)], solver=a.solver, name="A"
        )
    init_display_type("none")
    logs = await eval_async(
        [a, _hook_task("B", run_b)],
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=2,
        task_retry_attempts=1,
        limit=(2, 3) if empty else None,
    )
    assert seen["status"] == "queued"
    status, body = seen["first"]
    assert status == 200
    assert body["changed"] is True and body["abort_deferred"] is True
    assert "task_queued" not in body
    assert seen["repeats"] == ["cancel already requested (abort)"] * 4
    assert seen["finished_status"] == "completed"
    assert b_ran == []
    [b] = [log for log in logs if log.eval.task == "B"]
    assert b.status == "error"
    assert b.error is not None
    assert "Task cancelled by user (abort)" in b.error.message
    # the ordinary cancelled-task log, kept
    assert b.location and Path(b.location).exists()
    assert (await read_eval_log_async(b.location)).status == "error"


@pytest.mark.parametrize("verb", ["cancel", "drain"])
async def test_deferred_abort_of_resumed_task_reads_its_cancelled_sample_as_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str
) -> None:
    # B resumes a log holding a sample cancelled by its sibling's failure,
    # with a retry left (so it registers with will_retry). The deferred abort
    # suppresses the retry, so that inherited sample reads `cancelled`, not
    # `pending`, in the sample listing and the sample detail
    from inspect_ai._eval.task.resolved import ResolvedTask
    from inspect_ai._eval.task.task import PreviousTask

    started = anyio.Event()

    @solver
    def failing_sibling() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == 1:
                started.set()
                await anyio.sleep_forever()
            await started.wait()
            raise RuntimeError("second sample failed")

        return solve

    b_task = Task(
        name="B",
        dataset=[Sample(input="x"), Sample(input="y")],
        solver=failing_sibling(),
    )
    init_display_type("none")
    [prior] = await eval_async(
        b_task, model="mockllm/model", log_dir=str(tmp_path / "prior"), max_samples=2
    )
    prior = await read_eval_log_async(prior.location)
    assert prior.samples is not None
    [cancelled] = [
        s for s in prior.samples if s.error and "cancel" in s.error.message.lower()
    ]

    init = TaskLogger.init
    init_entered = anyio.Event()
    release = anyio.Event()
    seen: dict[str, Any] = {}

    async def held_init(self: TaskLogger) -> None:
        if self.eval.task == "B":
            init_entered.set()
            with anyio.CancelScope(shield=True):
                await release.wait()
        await init(self)

    async def cancel_b() -> None:
        with anyio.fail_after(10):
            await init_entered.wait()
        try:
            task_id = (await ctl_tasks())["B"]["task_id"]
            seen["first"] = await ctl_task_directive(task_id, verb)
        finally:
            release.set()
        with anyio.fail_after(10):
            await _record("B").ended.wait()
        eval_id = (await ctl_tasks())["B"]["eval_id"]
        listing = await ctl_request("GET", f"/evals/{eval_id}/samples")
        seen["listing"] = {
            str(row["sample_id"]): row["status"] for row in listing.json()["samples"]
        }
        detail = await ctl_request(
            "GET",
            f"/evals/{eval_id}/sample",
            {"sample_id": str(cancelled.id), "epoch": cancelled.epoch},
        )
        seen["detail"] = detail.json()["status"]

    monkeypatch.setattr(TaskLogger, "init", held_init)
    previous = PreviousTask(
        id=prior.eval.task_id,
        task=b_task,
        task_args={},
        model=None,
        model_roles=None,
        sandbox=None,
        log=prior,
        log_info=None,
    )
    a = resolve_tasks(
        _hook_task("A", cancel_b), {}, get_model("mockllm/model"), None, None, None
    )
    with anyio.fail_after(30):
        tasks: list[PreviousTask | ResolvedTask] = [*a, previous]
        await eval_async(
            tasks,
            model="mockllm/model",
            log_dir=str(tmp_path / "resume"),
            max_tasks=2,
            task_retry_attempts=1,
        )
    status, body = seen["first"]
    assert status == 200 and body["abort_deferred"] is True
    assert seen["listing"][str(cancelled.id)] == "cancelled"
    assert "pending" not in seen["listing"].values()
    assert seen["detail"] == "cancelled"


@pytest.mark.parametrize("verb", ["cancel", "drain"])
async def test_ctl_cancel_of_starting_preview_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str
) -> None:
    # previews (run_samples=False) never register: P1's starting attempt
    # (logger.init() held) answers a no-op and keeps its `started` log, while
    # P2, waiting for the one slot, is cancelled at once with no log
    init = TaskLogger.init
    init_entered = anyio.Event()
    release = anyio.Event()
    seen: dict[str, Any] = {}

    async def held_init(self: TaskLogger) -> None:
        if self.eval.task == "P1":
            init_entered.set()
            with anyio.CancelScope(shield=True):
                await release.wait()
        await init(self)

    async def cancel_previews() -> None:
        with anyio.fail_after(10):
            await init_entered.wait()
        try:
            rows = await ctl_tasks()
            seen["starting"] = await ctl_task_directive(rows["P1"]["task_id"], verb)
            seen["waiting"] = await ctl_task_directive(rows["P2"]["task_id"], verb)
        finally:
            release.set()

    monkeypatch.setattr(TaskLogger, "init", held_init)
    init_display_type("none")
    async with anyio.create_task_group() as tg:
        tg.start_soon(cancel_previews)
        logs = await eval_async(
            [_hook_task("P1", _noop), _hook_task("P2", _noop)],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=1,
            run_samples=False,
        )
    status, body = seen["starting"]
    assert status == 200
    assert body["changed"] is False
    assert "preview" in body["reason"]
    assert "abort_deferred" not in body
    status, body = seen["waiting"]
    assert status == 200
    assert body["changed"] is True and body["task_queued"] is True
    by_task = {log.eval.task: log for log in logs}
    assert by_task["P1"].status == "started"
    assert Path(by_task["P1"].location).exists()
    assert by_task["P2"].status == "error"
    assert by_task["P2"].location == ""


@pytest.mark.parametrize("failures", [2, 3])
async def test_attempts_count_startup_failures_before_registering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int
) -> None:
    # B's log init fails `failures` times with two retries allowed: B either
    # registers on its third attempt or ends unregistered after its third
    # failure, and its row counts all three attempts either way
    init = TaskLogger.init
    inits = 0
    seen: dict[str, Any] = {}

    async def failing_init(self: TaskLogger) -> None:
        nonlocal inits
        if self.eval.task == "B":
            inits += 1
            if inits <= failures:
                raise OSError("cannot start log")
        await init(self)

    async def b_running() -> None:
        seen["running"] = (await ctl_tasks())["B"]["attempts"]

    async def b_finished() -> None:
        with anyio.fail_after(10):
            await _record("B").ended.wait()
        seen["finished"] = (await ctl_tasks())["B"]["attempts"]

    monkeypatch.setattr(TaskLogger, "init", failing_init)
    source = _WaitForReports(
        [_hook_task("A", b_finished), _hook_task("B", b_running)], 2
    )
    init_display_type("none")
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=2,
        task_retry_attempts=2,
    )
    assert inits == 3
    [b] = [log for log in logs if log.eval.task == "B"]
    if failures == 2:
        assert b.status == "success"
        assert seen["running"] == 3
    else:
        assert b.status == "error"
        assert "running" not in seen
    assert seen["finished"] == 3


async def test_ctl_cancel_while_unregistered_attempt_prepares_retry_ends_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B's log init fails and its retry is being prepared (reinit() held): a
    # cancel through the control channel is deferred, and the retry it
    # queues aborts before it starts, not as a pending retry abandoned
    init = TaskLogger.init
    reinit = TaskLogger.reinit
    reinit_entered = anyio.Event()
    release = anyio.Event()
    seen: dict[str, Any] = {}

    async def failing_init(self: TaskLogger) -> None:
        if self.eval.task == "B":
            raise OSError("cannot start log")
        await init(self)

    async def held_reinit(self: TaskLogger) -> None:
        if self.eval.task == "B":
            reinit_entered.set()
            await release.wait()
        await reinit(self)

    async def cancel_b() -> None:
        with anyio.fail_after(10):
            await reinit_entered.wait()
        try:
            task_id = (await ctl_tasks())["B"]["task_id"]
            seen["cancel"] = await ctl_task_directive(task_id, "cancel")
        finally:
            release.set()

    monkeypatch.setattr(TaskLogger, "init", failing_init)
    monkeypatch.setattr(TaskLogger, "reinit", held_reinit)
    source = _WaitForReports([_hook_task("A", cancel_b), _hook_task("B", _noop)], 2)
    init_display_type("none")
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=2,
        task_retry_attempts=2,
    )
    status, body = seen["cancel"]
    assert status == 200
    assert body["changed"] is True and body["abort_deferred"] is True
    assert "retry_abandoned" not in body
    [b] = [log for log in logs if log.eval.task == "B"]
    assert b.status == "error"
    assert b.error is not None
    assert "Task cancelled by user (abort)" in b.error.message
    # the failed attempt and the aborted retry
    assert [log.eval.task for log in source.reports].count("B") == 2


async def test_task_failing_before_it_registers_stays_listed_as_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init = TaskLogger.init
    seen: dict[str, Any] = {}

    async def failing_init(self: TaskLogger) -> None:
        if self.eval.task == "B":
            raise OSError("cannot start log")
        await init(self)

    async def check_b() -> None:
        with anyio.fail_after(10):
            await _record("B").ended.wait()
        row = (await ctl_tasks())["B"]
        seen["row"] = row
        seen["cancel"] = (await ctl_task_directive(row["task_id"], "cancel"))[1]

    monkeypatch.setattr(TaskLogger, "init", failing_init)
    source = _WaitForReports([_hook_task("A", check_b), _hook_task("B", _noop)], 2)
    init_display_type("none")
    await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=2,
        task_retry_attempts=0,
    )
    row = seen["row"]
    assert row["status"] == "completed"
    assert row["samples"]["total"] == 0
    assert row["attempts"] == 1
    assert seen["cancel"]["changed"] is False
    assert seen["cancel"]["reason"] == "task already finished"


async def test_next_tasks_error_ends_the_run(tmp_path: Path) -> None:
    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_task("seed")]

        async def next_tasks(self) -> list[Task] | None:
            raise ValueError("source failed")

    init_display_type("none")
    with pytest.raises(ValueError, match="source failed"):
        await eval_async(_Src(), model="mockllm/model", log_dir=str(tmp_path))


async def test_source_returns_after_the_run_stopped_are_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    started = anyio.Event()

    async def block() -> None:
        started.set()
        await anyio.sleep_forever()

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_hook_task("A", block)]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            # no checkpoint: the follow-up is returned however the run ended
            return [_task("follow_up")]

    init_display_type("none")
    with anyio.CancelScope() as scope:

        async def cancel_when_started() -> None:
            with anyio.fail_after(10):
                await started.wait()
            scope.cancel()

        async with anyio.create_task_group() as tg:
            tg.start_soon(cancel_when_started)
            await eval_async(_Src(), model="mockllm/model", log_dir=str(tmp_path))

    logs = list(tmp_path.glob("*.eval"))
    assert len(logs) == 1
    assert "follow-up" not in logs[0].name and "follow_up" not in logs[0].name


class _BlockingNextTasks(TaskSource):
    """Seeds one task; next_tasks() then blocks until the run is cancelled."""

    def __init__(self) -> None:
        self._entered: anyio.Event | None = None

    def entered(self) -> anyio.Event:
        if self._entered is None:
            self._entered = anyio.Event()
        return self._entered

    def initial_tasks(self) -> list[Task]:
        return [_task("seed")]

    async def next_tasks(self) -> list[Task] | None:
        self.entered().set()
        await anyio.sleep_forever()
        return None


@pytest.mark.parametrize("max_tasks", [1, 2])
async def test_cancellation_while_next_tasks_blocks_keeps_completed_logs(
    tmp_path: Path, max_tasks: int
) -> None:
    source = _BlockingNextTasks()
    init_display_type("none")
    with anyio.fail_after(30):
        with anyio.CancelScope() as scope:

            async def cancel_when_blocked() -> None:
                await source.entered().wait()
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel_when_blocked)
                await eval_async(
                    source,
                    model="mockllm/model",
                    max_tasks=max_tasks,
                    log_dir=str(tmp_path),
                )

    assert scope.cancel_called
    [info] = list_eval_logs(str(tmp_path))
    log = await read_eval_log_async(info.name)
    assert (log.eval.task, log.status) == ("seed", "success")


_SIGINT_WHILE_NEXT_TASKS_BLOCKS = """
import signal
import sys
import tempfile

import anyio
from inspect_ai import Task, TaskSource, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, read_eval_log


class Source(TaskSource):
    def initial_tasks(self):
        return [Task(dataset=[Sample(input="x")], name="seed")]

    async def next_tasks(self):
        signal.raise_signal(signal.SIGINT)
        await anyio.sleep(30)
        return None


for max_tasks in (1, 2):
    log_dir = tempfile.mkdtemp()
    try:
        logs = eval(
            Source(),
            model="mockllm/model",
            max_tasks=max_tasks,
            display="none",
            log_dir=log_dir,
        )
        outcome = "returned " + ",".join(log.status for log in logs)
    except KeyboardInterrupt:
        outcome = "KeyboardInterrupt"
    on_disk = ",".join(read_eval_log(info.name).status for info in list_eval_logs(log_dir))
    print(f"max_tasks={max_tasks}: {outcome}; on disk {on_disk}")
"""


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_sigint_while_next_tasks_blocks_keeps_completed_logs(backend: str) -> None:
    # a Ctrl-C while next_tasks() blocks is handled like one during a task:
    # eval() returns the logs on asyncio, and on trio run_main raises
    # KeyboardInterrupt after the run has written them
    result = subprocess.run(
        [sys.executable, "-I", "-c", _SIGINT_WHILE_NEXT_TASKS_BLOCKS],
        env={**os.environ, "INSPECT_ASYNC_BACKEND": backend},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = "returned success" if backend == "asyncio" else "KeyboardInterrupt"
    lines = [line for line in result.stdout.splitlines() if line.startswith("max_")]
    assert lines == [
        f"max_tasks=1: {outcome}; on disk success",
        f"max_tasks=2: {outcome}; on disk success",
    ], result.stdout + result.stderr


async def test_next_tasks_batch_is_freed_once_its_tasks_end(tmp_path: Path) -> None:
    # the dispatcher keeps no reference to a batch next_tasks() returned, so
    # a finished task and its dataset are freed while the next call blocks
    task_ref: list[weakref.ref[Task]] = []
    alive_during_next_pull: list[bool] = []

    class _Src(TaskSource):
        calls = 0

        def initial_tasks(self) -> list[Task]:
            return [_task("seed")]

        async def next_tasks(self) -> list[Task] | None:
            self.calls += 1
            if self.calls == 1:
                pulled = _task("pulled")
                task_ref.append(weakref.ref(pulled))
                return [pulled]
            if self.calls == 2:
                assert _record("pulled").phase == "ended"
                gc.collect()
                alive_during_next_pull.append(task_ref[0]() is not None)
            return None

    init_display_type("none")
    logs = await eval_async(_Src(), model="mockllm/model", log_dir=str(tmp_path))
    assert [log.eval.task for log in logs] == ["seed", "pulled"]
    assert alive_during_next_pull == [False]


@pytest.mark.parametrize("early_end", ["log_init_failure", "queued_abort"])
async def test_attempt_report_runs_under_its_own_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, early_end: str
) -> None:
    # an attempt that ends before its log starts is still reported to the
    # source in its own task context (its model, not the last one resolved)
    seen: list[tuple[str, str, str]] = []
    init = TaskLogger.init

    async def failing_init(self: TaskLogger) -> None:
        if self.eval.task == "B" and self.eval.model == "mockllm/first":
            raise OSError("cannot start log")
        await init(self)

    async def cancel_b_first() -> None:
        queue = get_run_queue()
        assert queue is not None
        record = next(
            r for r in queue.records if r.task == "B" and r.model == "mockllm/first"
        )
        queue.cancel(record)

    if early_end == "log_init_failure":
        monkeypatch.setattr(TaskLogger, "init", failing_init)
        seed = [_task("B")]
    else:
        # A (both models) runs first at max_tasks=1 and cancels B's first-model
        # record while it is queued
        seed = [_hook_task("A", cancel_b_first), _task("B")]

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return seed

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            seen.append((log.eval.task, log.eval.model, str(get_model())))
            return None

    init_display_type("none")
    await eval_async(
        _Src(),
        model=["mockllm/first", "mockllm/second"],
        log_dir=str(tmp_path),
        max_tasks=1,
    )
    [(_, model, active)] = [r for r in seen if r[0] == "B" and r[1] == "mockllm/first"]
    assert active == model
    assert all(r[1] == r[2] for r in seen), seen


async def test_interrupted_retry_preparation_releases_the_attempts_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the attempt owns its logger until its retry is published: a
    # cancellation while the retry is prepared still closes the buffer of an
    # attempt whose final write failed and releases its recorder entry
    reinit_entered = anyio.Event()
    loggers: list[TaskLogger] = []

    async def failing_log_finish(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        raise OSError("final write failed")

    async def held_reinit(self: TaskLogger) -> None:
        loggers.append(self)
        reinit_entered.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(TaskLogger, "log_finish", failing_log_finish)
    monkeypatch.setattr(TaskLogger, "reinit", held_reinit)
    init_display_type("none")
    with anyio.fail_after(30):
        with anyio.CancelScope() as scope:

            async def cancel_when_preparing_retry() -> None:
                await reinit_entered.wait()
                [logger] = loggers
                # held by the failed attempt until reinit releases it
                assert logger.buffer_db is not None
                assert not logger.finished
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel_when_preparing_retry)
                await eval_async(
                    _task("A"),
                    model="mockllm/model",
                    log_dir=str(tmp_path),
                    task_retry_attempts=1,
                )

    [logger] = loggers
    assert logger.buffer_db is None
    with pytest.raises(RuntimeError, match="No log in progress"):
        logger.recorder.destination_written(logger.eval)


@skip_if_trio  # an asyncio task cancelled on its own, outside the run
async def test_next_tasks_cancelled_by_its_own_producer_fails_the_run(
    tmp_path: Path,
) -> None:
    # a cancellation the run did not cause must not read as the source
    # finishing: the run fails instead of returning its partial logs
    import asyncio

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_task("seed")]

        async def next_tasks(self) -> list[Task] | None:
            producer = asyncio.create_task(asyncio.sleep(30))
            await asyncio.sleep(0)
            producer.cancel()
            await producer  # raises CancelledError into next_tasks()
            return None

    init_display_type("none")
    with anyio.fail_after(30):
        with pytest.raises(RuntimeError, match="next_tasks"):
            await eval_async(_Src(), model="mockllm/model", log_dir=str(tmp_path))
