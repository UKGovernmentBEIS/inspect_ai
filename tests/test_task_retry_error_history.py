"""Reproductions for surfacing task-level retries at the sample level.

When an eval-set retries a whole task (``retry_attempts`` / the default
``retry_immediate`` path), the failed sample is re-run in a fresh log and
the failed attempt's log is removed by ``retry_cleanup``. The re-run sample
must therefore carry the prior attempt's error in ``error_retries`` so that:

- ``EvalSample.error_retries`` records the prior error (run path), and
- the stored ``EvalSampleSummary.retries`` reflects it (the path the
  control channel reads — both the live recorder and the on-disk log).
"""

import tempfile
from pathlib import Path

from inspect_ai import Task, eval_set, task
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log, read_eval_log_sample_summaries
from inspect_ai.solver import Generate, Solver, TaskState, solver


def _fail_once_task() -> Task:
    """A one-sample task whose sample errors on its first attempt only."""
    attempts = {"n": 0}

    @solver
    def fail_first_attempt() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient task failure")
            return state

        return solve

    @task
    def retry_task() -> Task:
        return Task(
            dataset=[Sample(id=1, input="x", target="y")],
            solver=[fail_first_attempt()],
            name="retry_task",
        )

    return retry_task()


def _run_task_retry(log_dir: str) -> str:
    """Run an eval-set that retries one failing task; return the log path."""
    ok, logs = eval_set(
        tasks=[_fail_once_task()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=2,
        retry_on_error=0,  # no sample-level retry -> task-level retry kicks in
    )
    assert ok, "eval-set did not succeed after task retry"
    assert len(logs) == 1
    return logs[0].location


def test_task_retry_seeds_error_retries_on_sample() -> None:
    """Run path: the re-run sample carries the prior attempt's error."""
    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        location = _run_task_retry(log_dir)

        log = read_eval_log(location)
        assert log.samples is not None and len(log.samples) == 1
        sample = log.samples[0]
        assert sample.error is None, "final attempt should have succeeded"
        assert sample.error_retries is not None
        assert len(sample.error_retries) == 1
        assert "transient task failure" in sample.error_retries[0].message


def test_task_retry_retries_in_sample_summaries() -> None:
    """Endpoint path: the stored summary reports the retry count.

    This is the exact data the control channel reads for a finished /
    keep-alive-parked eval (recorder gone -> on-disk summaries).
    """
    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        location = _run_task_retry(log_dir)

        summaries = read_eval_log_sample_summaries(location)
        assert len(summaries) == 1
        assert summaries[0].retries == 1


def test_is_cancellation_error_distinguishes_cancellations() -> None:
    """The cancellation guard matches backend cancellation reprs only."""
    from inspect_ai._eval.task.run import _is_cancellation_error
    from inspect_ai.log import EvalError

    def err(message: str) -> EvalError:
        return EvalError(message=message, traceback="", traceback_ansi="")

    # asyncio / trio cancellation reprs
    assert _is_cancellation_error(err("CancelledError('Cancelled via cancel scope 1')"))
    assert _is_cancellation_error(err("CancelledError()"))
    assert _is_cancellation_error(err("Cancelled()"))
    # genuine errors must not be treated as cancellations
    assert not _is_cancellation_error(err("RuntimeError('boom')"))
    assert not _is_cancellation_error(err("CancelledByUserError('nope')"))


def test_task_retry_does_not_count_cancelled_siblings() -> None:
    """A sibling cancelled by another sample's failure isn't a retry.

    Sample 1 errors on its first attempt; sample 2 is in-flight and gets
    cancelled when the task is torn down for the task-level retry. On the
    retry sample 1 succeeds. Sample 1 should report ``retries == 1`` (a
    genuine failure) while sample 2 reports ``retries == 0`` (it was only
    cancelled, never genuinely failed).
    """
    import anyio

    attempts = {"n": 0}

    @solver
    def mixed() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) == 1:
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("boom")
            else:
                # in-flight when sample 1 errors -> cancelled on attempt 1;
                # completes on the retry (sample 1 succeeds, no teardown)
                await anyio.sleep(2)
            return state

        return solve

    @task
    def mixed_task() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2)],
            solver=[mixed()],
            name="mixed_task",
        )

    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        ok, logs = eval_set(
            tasks=[mixed_task()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=2,
            retry_on_error=0,
            max_samples=2,
        )
        assert ok

        summaries = {s.id: s for s in read_eval_log_sample_summaries(logs[0].location)}
        assert summaries[1].retries == 1, "genuine error should count as a retry"
        assert summaries[2].retries == 0, "cancelled sibling must not count as a retry"


def test_task_retry_accumulates_across_attempts() -> None:
    """Retries accumulate across multiple sequential task attempts.

    Sample 3 errors on its first two runs and succeeds on the third, so its
    history must grow to two entries (``retries == 2``); sample 1 errors once
    (``retries == 1``); sample 2 never errors (``retries == 0``). No solver
    awaits before raising, so there is no cancellation point and the schedule
    is deterministic.
    """
    runs = {1: 0, 2: 0, 3: 0}

    @solver
    def flaky() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sid = int(state.sample_id)
            runs[sid] += 1
            if sid == 1 and runs[1] == 1:
                raise RuntimeError("s1 fail")
            if sid == 3 and runs[3] <= 2:
                raise RuntimeError(f"s3 fail {runs[3]}")
            return state

        return solve

    @task
    def accum_task() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3)],
            solver=[flaky()],
            name="accum_task",
        )

    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        ok, logs = eval_set(
            tasks=[accum_task()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=5,
            retry_on_error=0,
            max_samples=3,
        )
        assert ok

        summaries = {s.id: s for s in read_eval_log_sample_summaries(logs[0].location)}
        assert summaries[1].retries == 1
        assert summaries[2].retries == 0
        assert summaries[3].retries == 2


async def test_finish_task_log_carries_forward_on_every_non_success_status(
    monkeypatch,
) -> None:
    """All terminal finishes preserve retry history; success skips it.

    `_finish_task_log` is the single finish chokepoint: before it existed,
    carry-forward was called at two of the three teardown branches and the
    external-cancellation (Ctrl-C) branch silently dropped retry history —
    and a cancelled log IS the seed for the next attempt. The chokepoint
    makes the omission structurally impossible; this pins the status gating.
    """
    from types import SimpleNamespace
    from typing import Any

    import inspect_ai._eval.task.run as run_mod
    from inspect_ai._eval.task.run import _finish_task_log
    from inspect_ai.log import EvalStats

    carried: list[str] = []
    finished: list[tuple[str, Any]] = []

    async def fake_carry_forward(
        logger: Any, sample_source: Any, sample_ids: Any, epochs: Any, log_images: Any
    ) -> None:
        carried.append("called")

    monkeypatch.setattr(run_mod, "carry_forward_unlogged_samples", fake_carry_forward)

    async def log_finish(
        status: str,
        stats: Any,
        results: Any = None,
        reductions: Any = None,
        error: Any = None,
    ) -> Any:
        finished.append((status, error))
        return SimpleNamespace(status=status)

    logger = SimpleNamespace(log_finish=log_finish)

    for status, expect_carry in (
        ("cancelled", True),  # the branch that used to skip it (Ctrl-C)
        ("error", True),
        ("success", False),
    ):
        carried.clear()
        log = await _finish_task_log(
            logger=logger,  # type: ignore[arg-type]
            sample_source=None,
            sample_ids=[1],
            epochs=1,
            log_images=False,
            status=status,  # type: ignore[arg-type]
            stats=EvalStats(),
        )
        assert log.status == status
        assert bool(carried) == expect_carry, f"{status}: carry={carried}"

    # the finish itself always ran
    assert [s for s, _ in finished] == ["cancelled", "error", "success"]


async def test_carry_forward_probes_only_error_history_candidates() -> None:
    """Carry-forward probes the prior attempt's errored samples only.

    Probing the full plan (one prior-log sample read per planned (id, epoch))
    stalled Ctrl-C teardown of large remote retries for minutes inside the
    cancellation shield; only errored prior samples can yield PreviousError,
    so the probe set is the source's error_history_ids — minus already-logged
    samples and anything outside the current plan.
    """
    from types import SimpleNamespace
    from typing import Any

    from inspect_ai._eval.task.run import (
        EvalSampleSource,
        carry_forward_unlogged_samples,
    )

    lookups: list[tuple[Any, int]] = []

    async def lookup(id: Any, epoch: int) -> Any:
        lookups.append((id, epoch))
        return None  # probed, but yields no PreviousError

    async def error_ids() -> set[tuple[Any, int]]:
        return {(5, 1), (7, 1), (999, 1)}  # 999 is outside the plan

    async def sample_summaries() -> Any:
        # sample 7 already logged this attempt
        return [SimpleNamespace(id=7, epoch=1)]

    logger = SimpleNamespace(sample_summaries=sample_summaries)
    source = EvalSampleSource(lookup=lookup, error_history_ids=error_ids)

    await carry_forward_unlogged_samples(
        logger,  # type: ignore[arg-type]
        source,
        sample_ids=list(range(100)),
        epochs=1,
        log_images=False,
    )

    # 100 planned samples, but only the unlogged, in-plan candidate is probed
    assert lookups == [(5, 1)]


async def test_carry_forward_skips_entirely_without_candidates() -> None:
    """No errored prior samples → no recorder read and no probes at all."""
    from types import SimpleNamespace
    from typing import Any

    from inspect_ai._eval.task.run import (
        EvalSampleSource,
        carry_forward_unlogged_samples,
    )

    async def lookup(id: Any, epoch: int) -> Any:
        raise AssertionError("no candidates — lookup must not be called")

    async def error_ids() -> set[tuple[Any, int]]:
        return set()

    async def sample_summaries() -> Any:
        raise AssertionError("no candidates — recorder must not be read")

    logger = SimpleNamespace(sample_summaries=sample_summaries)
    source = EvalSampleSource(lookup=lookup, error_history_ids=error_ids)

    await carry_forward_unlogged_samples(
        logger,  # type: ignore[arg-type]
        source,
        sample_ids=list(range(100)),
        epochs=1,
        log_images=False,
    )
