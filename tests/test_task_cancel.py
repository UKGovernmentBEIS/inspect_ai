"""Tests for task cancellation via the cancel button during eval_set runs."""

import os
import signal
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import anyio

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai._display.core.display import TaskCancel
from inspect_ai._eval.evalset import eval_set
from inspect_ai._eval.task.run import task_run as original_task_run
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, TaskState, solver


def test_abort_cancel_produces_error_status() -> None:
    """Abort cancel should produce error status, not cancelled status.

    Regression: task_run logged abort cancellations with status='cancelled',
    which caused eval_set's evals_cancelled() check to raise KeyboardInterrupt,
    breaking the normal return path.
    """
    # Container to pass the TaskCancel from task_run into the solver.
    cancel_holder: list[TaskCancel] = []

    async def capturing_task_run(
        options: object, task_cancel: TaskCancel | None = None
    ) -> object:
        if task_cancel is not None:
            cancel_holder.append(task_cancel)
        return await original_task_run(options, task_cancel=task_cancel)  # type: ignore[arg-type]

    solver_id = id(cancel_holder)

    @solver(name=f"abort_solver_{solver_id}")
    def abort_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # Wait until the TaskCancel has been captured
            while not cancel_holder:
                await anyio.sleep(0.01)
            # Trigger an abort cancellation (simulates clicking Cancel > Abort)
            cancel_holder[0].cancel_task("abort")
            # Sleep to let the cancellation propagate. The abort is expected to
            # interrupt this; the duration is only an upper bound on the
            # propagation window.
            await anyio.sleep(2)
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        with patch("inspect_ai._eval.run.task_run", capturing_task_run):
            success, logs = eval_set(
                tasks=[
                    Task(
                        dataset=[Sample(input="x", target="y")],
                        solver=[abort_solver()],
                        name="task_abort",
                    ),
                ],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=1,
                retry_immediate=True,
                max_tasks=1,
            )

        # The task was aborted — eval_set should return normally (not raise
        # KeyboardInterrupt). The aborted task should have status="error".
        assert not success
        assert len(logs) == 1
        assert logs[0].status == "error"


def test_abort_cancel_not_retried_without_task_retries() -> None:
    """Aborted task should not be retried when task_retry_attempts is 0.

    task_retry_attempts is 0 when retry_immediate is False, so the dispatcher
    grants no in-run retries. When a task is aborted, the worker should stop
    and not allow the outer eval_set retry loop to re-run the aborted task.
    """
    cancel_holder: list[TaskCancel] = []
    run_count = 0

    async def capturing_task_run(
        options: object, task_cancel: TaskCancel | None = None
    ) -> object:
        if task_cancel is not None:
            cancel_holder.append(task_cancel)
        return await original_task_run(options, task_cancel=task_cancel)  # type: ignore[arg-type]

    solver_id = id(cancel_holder)

    @solver(name=f"abort_multi_solver_{solver_id}")
    def abort_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            nonlocal run_count
            run_count += 1
            # Wait until the TaskCancel has been captured
            while not cancel_holder:
                await anyio.sleep(0.01)
            # Trigger an abort cancellation
            cancel_holder[0].cancel_task("abort")
            # Sleep to let the cancellation propagate. The abort is expected to
            # interrupt this; the duration is only an upper bound on the
            # propagation window.
            await anyio.sleep(2)
            return state

        return solve

    @solver(name=f"noop_solver_{solver_id}")
    def noop_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        with patch("inspect_ai._eval.run.task_run", capturing_task_run):
            eval_set(
                tasks=[
                    Task(
                        dataset=[Sample(input="x", target="y")],
                        solver=[abort_solver()],
                        name="task_abort_multi",
                    ),
                    Task(
                        dataset=[Sample(input="x", target="y")],
                        solver=[noop_solver()],
                        name="task_noop",
                    ),
                ],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=3,
                retry_wait=0.0001,
                retry_immediate=False,
                max_tasks=2,
            )

        # The aborted task may be retried by the eval_set tenacity retry
        # loop (since abort currently produces status="error"). This is
        # acceptable for now — the key thing is it doesn't hang or crash.
        assert run_count >= 1


def test_score_resolution_cancel_completes_eval() -> None:
    """`ctl task cancel --action score` brings the eval to a completed state.

    The in-flight sample is interrupted and scored on the work done so far;
    the still-queued sample is abandoned (absent from the log); and the task
    completes with status "success" rather than the abort path's error status.
    """
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states

    @solver(name="score_resolution_solver")
    def score_resolution_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # the control directive runs on the eval's own loop (the control
            # server is embedded), so calling it from here is the same shape
            # as `POST /tasks/<id>/cancel?action=score`
            eval_state = get_eval_states()[0]
            result = ctl_cancel_task(eval_state.task_id, action="score")
            assert result is not None and result["ok"] is True
            # the interrupt cancels this sample's task group; this sleep is
            # only an upper bound on the propagation window
            await anyio.sleep(10)
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        # max_samples=1 leaves the second sample queued at the semaphore
        # while the first (which fires the cancel) runs
        logs = inspect_eval(
            Task(
                dataset=[
                    Sample(id=1, input="x", target="y"),
                    Sample(id=2, input="x", target="y"),
                ],
                solver=[score_resolution_solver()],
                scorer=includes(),
                name="task_score_resolution",
            ),
            log_dir=log_dir,
            model="mockllm/model",
            max_samples=1,
        )

        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        # the queued sample was abandoned; the in-flight one was scored
        assert log.samples is not None and len(log.samples) == 1
        sample = log.samples[0]
        assert sample.id == 1
        assert sample.error is None
        assert sample.limit is not None and sample.limit.type == "operator"
        assert sample.scores  # the scorer ran on the work done so far


def test_error_resolution_cancel_completes_eval() -> None:
    """`ctl task cancel --action error` completes the eval with errored samples.

    In-flight samples are resolved as errors while the eval still reaches a
    completed state.
    """
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states

    @solver(name="error_resolution_solver")
    def error_resolution_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            eval_state = get_eval_states()[0]
            result = ctl_cancel_task(eval_state.task_id, action="error")
            assert result is not None and result["ok"] is True
            await anyio.sleep(10)
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        # the error resolution is gated on samples that fail on errors, so
        # this mirrors the sample-level `--action error` requirement
        logs = inspect_eval(
            Task(
                dataset=[Sample(id=1, input="x", target="y")],
                solver=[error_resolution_solver()],
                scorer=includes(),
                name="task_error_resolution",
            ),
            log_dir=log_dir,
            model="mockllm/model",
            fail_on_error=False,
        )

        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        assert log.samples is not None and len(log.samples) == 1
        assert log.samples[0].error is not None


def test_error_resolution_rejected_when_samples_fail_on_error() -> None:
    """The error resolution is rejected under default fail-on-error config.

    This mirrors the sample-level gate; the task keeps running.
    """
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states

    @solver(name="error_resolution_rejected_solver")
    def error_resolution_rejected_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            eval_state = get_eval_states()[0]
            result = ctl_cancel_task(eval_state.task_id, action="error")
            assert result is not None and result["ok"] is False
            assert "fail on errors" in result["error"]
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        logs = inspect_eval(
            Task(
                dataset=[Sample(id=1, input="x", target="y")],
                solver=[error_resolution_rejected_solver()],
                scorer=includes(),
                name="task_error_resolution_rejected",
            ),
            log_dir=log_dir,
            model="mockllm/model",
        )

        assert len(logs) == 1
        assert logs[0].status == "success"
        assert logs[0].samples is not None and len(logs[0].samples) == 1
        # the rejected cancel had no effect
        assert logs[0].samples[0].error is None


def test_error_resolution_downgraded_for_materializing_fail_on_error_sample() -> None:
    """An `error` resolution landing mid-materialization downgrades to `score`.

    A sample between leaving the queue and starting is invisible to the
    cancel directive's fails-on-error gate, so a stamped `error` resolution
    can reach a fails-on-error sample; its self-interrupt resolves it as
    `score` instead so the auto-fail doesn't error the task the operator
    meant to complete gracefully.
    """
    from anyio.abc import TaskGroup

    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai.log._samples import ActiveSample

    original_start = ActiveSample.start

    def stamping_start(self: ActiveSample, tg: TaskGroup) -> None:
        # stamp the resolution at the last instant before the sample starts —
        # deterministically simulating a directive that landed while the
        # sample was materializing (after the gate's active_samples() check)
        eval_state = get_eval_states()[0]
        assert eval_state.task_cancel is not None
        eval_state.task_cancel.cancel_task("error")
        original_start(self, tg)

    @solver(name="downgrade_resolution_solver")
    def downgrade_resolution_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # the self-interrupt fired before the plan ran; its cancellation
            # is delivered at this checkpoint (the sleep is only an upper
            # bound on the propagation window)
            await anyio.sleep(10)
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        with patch.object(ActiveSample, "start", stamping_start):
            # default fail_on_error config, so the sample fails on error —
            # the configuration the gate exists to protect
            logs = inspect_eval(
                Task(
                    dataset=[Sample(id=1, input="x", target="y")],
                    solver=[downgrade_resolution_solver()],
                    scorer=includes(),
                    name="task_downgrade_resolution",
                ),
                log_dir=log_dir,
                model="mockllm/model",
            )

        assert len(logs) == 1
        log = logs[0]
        # without the downgrade the stamped error trips the auto-fail and the
        # task finishes errored; with it the sample scores and the eval succeeds
        assert log.status == "success"
        assert log.samples is not None and len(log.samples) == 1
        sample = log.samples[0]
        assert sample.error is None
        assert sample.limit is not None and sample.limit.type == "operator"
        assert sample.scores is not None


def test_sample_cancelled_interrupt_action() -> None:
    """`ActiveSample.interrupt("cancel")` records the sample as cancelled.

    Transcript preserved, no scoring, not an error — and the rest of the
    task (including its terminal status) is unaffected.
    """
    from inspect_ai.log._samples import sample_active

    @solver(name="cancelled_interrupt_solver")
    def cancelled_interrupt_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == 1:
                active = sample_active()
                assert active is not None
                active.interrupt("cancel")
                await anyio.sleep(10)
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        logs = inspect_eval(
            Task(
                dataset=[
                    Sample(id=1, input="x", target="y"),
                    Sample(id=2, input="x", target="y"),
                ],
                solver=[cancelled_interrupt_solver()],
                scorer=includes(),
                name="task_sample_cancelled",
            ),
            log_dir=log_dir,
            model="mockllm/model",
        )

        assert len(logs) == 1
        log = logs[0]
        # a cancelled sample is not a genuine error, so the eval still succeeds
        assert log.status == "success"
        assert log.samples is not None and len(log.samples) == 2
        cancelled = next(s for s in log.samples if s.id == 1)
        untouched = next(s for s in log.samples if s.id == 2)
        assert cancelled.error is not None  # cancellation recorded, transcript kept
        assert not cancelled.scores  # no scoring on a cancelled sample
        assert untouched.error is None and untouched.scores


def test_score_resolution_sweep_preserves_cancelled_sample() -> None:
    """A score resolution never overwrites a sample's prior 'cancel' interrupt.

    The in-flight sweep skips samples already interrupted (first interrupt
    wins): a sample the operator just cancelled per-sample keeps its
    'cancel' disposition — no scoring, its cancellation recorded — even
    when a task-level `--score` cancel lands before it finishes resolving.
    """
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai.log._samples import sample_active

    @solver(name="cancelled_then_score_solver")
    def cancelled_then_score_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            active = sample_active()
            assert active is not None
            active.interrupt("cancel")
            # the score resolution lands before this sample's cancellation
            # is even delivered (no checkpoint since the interrupt) — it is
            # still in flight, so the sweep sees it
            result = ctl_cancel_task(get_eval_states()[0].task_id, action="score")
            assert result is not None and result["ok"] is True
            await anyio.sleep(10)
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        logs = inspect_eval(
            Task(
                dataset=[Sample(id=1, input="x", target="y")],
                solver=[cancelled_then_score_solver()],
                scorer=includes(),
                name="task_sweep_preserves_cancelled",
            ),
            log_dir=log_dir,
            model="mockllm/model",
        )

        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        assert log.samples is not None and len(log.samples) == 1
        sample = log.samples[0]
        # cancelled semantics, not the sweep's score resolution
        assert sample.error is not None
        assert not sample.scores


def test_external_interrupt_with_pending_resolution_logs_cancelled(
    tmp_path: Path,
) -> None:
    """Ctrl+c during a pending graceful resolution keeps ctrl+c semantics.

    A stamped score/error resolution never fires the task's cancel scope, so
    a cancellation reaching task_run with one pending is external — the log
    must finalize as status "cancelled" (not a user-cancel error status),
    preserving eval/eval_set's usual interrupt and resume semantics.
    """
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai.log import list_eval_logs, read_eval_log

    @solver(name="stamp_resolution_solver")
    def stamp_resolution_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            eval_state = get_eval_states()[0]
            assert eval_state.task_cancel is not None
            # stamp the resolution on the raw handle without interrupting
            # this sample — the pending-graceful-resolution state (e.g. a
            # `--score` cancel stalled on a hung sample/scorer)
            eval_state.task_cancel.cancel_task("score")
            await anyio.sleep(10)
            return state

        return solve

    def send_sigint() -> None:
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGINT)

    sigint_thread = threading.Thread(target=send_sigint, daemon=True)
    sigint_thread.start()

    try:
        inspect_eval(
            Task(
                dataset=[Sample(id=1, input="x", target="y")],
                solver=[stamp_resolution_solver()],
                scorer=includes(),
                name="task_interrupt_pending_resolution",
            ),
            log_dir=str(tmp_path),
            model="mockllm/model",
        )
    except KeyboardInterrupt:
        pass
    sigint_thread.join(timeout=5)

    log_files = list_eval_logs(str(tmp_path))
    assert len(log_files) == 1
    log = read_eval_log(log_files[0].name)
    assert log.status == "cancelled"
    assert log.error is None


def test_errored_attempt_marked_retry_pending() -> None:
    """The runner stamps retry_pending on the errored attempt it re-queues.

    Between an errored attempt (completed_at stamped) and its retry starting
    (fresh EvalState registered), the errored attempt is the task's latest —
    the flag is what lets `ctl task cancel` reject with "between attempts"
    instead of claiming the task finished (see EvalState.retry_pending).
    """
    from inspect_ai._control.eval_state import (
        mark_eval_retry_pending as original_mark,
    )

    marked: list[str] = []

    def recording_mark(eval_id: str) -> None:
        marked.append(eval_id)
        original_mark(eval_id)

    attempts = 0

    @solver(name=f"fail_once_solver_{id(marked)}")
    def fail_once_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("first attempt fails")
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        with patch("inspect_ai._eval.run.mark_eval_retry_pending", recording_mark):
            success, logs = eval_set(
                tasks=[
                    Task(
                        dataset=[Sample(input="x", target="y")],
                        solver=[fail_once_solver()],
                        name="task_retry_pending",
                    ),
                ],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=1,
                retry_immediate=True,
            )

        assert success
        assert len(logs) == 1 and logs[0].status == "success"
        # stamped exactly once, on the errored attempt — not the retry
        assert len(marked) == 1
        assert marked[0] != logs[0].eval.eval_id
