"""Tests for task cancellation via the cancel button during eval_set runs."""

import os
import signal
import tempfile
import threading
import time
import traceback
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, overload
from unittest.mock import patch

import anyio
import pytest
from typing_extensions import override

from inspect_ai import Task, TaskSource
from inspect_ai import eval as inspect_eval
from inspect_ai._display.core.display import CancelType, TaskCancel, TaskError
from inspect_ai._eval.evalset import eval_set
from inspect_ai._eval.task.run import task_run as original_task_run
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    sandboxenv,
)


@pytest.mark.parametrize(
    ("pending", "requested", "stamped"),
    [
        (None, "drain", "drain"),
        ("drain", "score", "score"),
        ("score", "error", "score"),
        ("error", "retry", "retry"),
        ("retry", "abort", "abort"),
        ("abort", "retry", "abort"),
        ("abort", "abort", "abort"),
        ("abort", "drain", "abort"),
        ("drain", None, "drain"),
    ],
)
def test_task_cancel_stamp_only_escalates(
    pending: CancelType, requested: CancelType, stamped: CancelType
) -> None:
    applied: list[CancelType] = []
    task_cancel = TaskCancel(can_retry=True, apply=applied.append)
    task_cancel.request(pending)
    applied.clear()

    task_cancel.request(requested)

    assert task_cancel.cancel_type == stamped
    assert applied == ([] if stamped == pending else [requested])


@pytest.mark.parametrize(
    ("ended_in_error", "requested", "stamped"),
    [
        (True, "abort", "abort"),
        (True, "retry", None),
        (False, "abort", None),
    ],
)
def test_task_cancel_after_close_accepts_only_abort_of_errored_attempt(
    ended_in_error: bool, requested: CancelType, stamped: CancelType
) -> None:
    task_cancel = TaskCancel(can_retry=True, apply=lambda _: None)
    task_cancel.close(ended_in_error=ended_in_error)

    task_cancel.request(requested)

    assert task_cancel.cancel_type == stamped


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
            cancel_holder[0].request("abort")
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
            cancel_holder[0].request("abort")
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
        assert sample.limit.reason == "Sample completed: interrupted by operator"
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
        eval_state.task_cancel.request("error")
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


def test_drain_resolution_cancels_materializing_sample() -> None:
    """A `drain` landing mid-materialization resolves the sample as cancelled.

    Drain never interrupts in-flight samples, but a sample between leaving
    the queue and starting is not yet in flight: it must not start new work,
    so its self-interrupt resolves it as cancelled — transcript preserved,
    not scored, not counted as an error (the task still succeeds under the
    default fail_on_error), and excluded from the completeness stamp so the
    remainder stays re-runnable.
    """
    from anyio.abc import TaskGroup

    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._util.error import is_cancellation_message
    from inspect_ai.log._samples import ActiveSample

    original_start = ActiveSample.start
    solved: list[int | str | None] = []

    def stamping_start(self: ActiveSample, tg: TaskGroup) -> None:
        # stamp the drain at the last instant before the second sample starts
        # — after its queue-exit check, so only this branch can resolve it
        # (max_samples=1 has the first sample fully resolved by then)
        if self.sample.id == 2:
            eval_state = get_eval_states()[0]
            assert eval_state.task_cancel is not None
            eval_state.task_cancel.request("drain")
        original_start(self, tg)

    @solver(name="drain_resolution_solver")
    def drain_resolution_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == 2:
                # the self-interrupt fired before the plan ran; its
                # cancellation is delivered at this checkpoint (the sleep is
                # only an upper bound on the propagation window)
                await anyio.sleep(10)
            solved.append(state.sample_id)
            return state

        return solve

    with tempfile.TemporaryDirectory() as log_dir:
        with patch.object(ActiveSample, "start", stamping_start):
            logs = inspect_eval(
                Task(
                    dataset=[
                        Sample(id=1, input="x", target="y"),
                        Sample(id=2, input="x", target="y"),
                    ],
                    solver=[drain_resolution_solver()],
                    scorer=includes(),
                    name="task_drain_resolution",
                ),
                log_dir=log_dir,
                model="mockllm/model",
                max_samples=1,
            )

        assert solved == [1]
        assert len(logs) == 1
        log = logs[0]
        # cancelled, not errored: the default fail_on_error would otherwise
        # have errored the task the operator meant to complete gracefully
        assert log.status == "success"
        assert log.samples is not None and len(log.samples) == 2
        finished = next(s for s in log.samples if s.id == 1)
        cancelled = next(s for s in log.samples if s.id == 2)
        assert finished.error is None and finished.scores
        assert cancelled.error is not None
        assert is_cancellation_message(cancelled.error.message)
        assert not cancelled.scores
        assert cancelled.limit is None
        # the cancelled sample is excluded from the completeness stamp, so a
        # later eval-set re-invocation re-runs it
        assert log.results is not None
        assert log.results.total_samples == 2
        assert log.results.logged_samples == 1


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


def test_interrupt_in_retry_drain_window_resolves_cancelled() -> None:
    """An interrupt in an errored sample's pre-retry drain window abandons it.

    A sample that just errored with sample-level retries remaining still looks
    in flight (`started` set, `completed` unset, no interrupt) while it drains
    its transcript events before handing back to the retry loop, so a
    task-cancel sweep interrupts it there — but the interrupt only stamps
    `interrupt_action` (the sample's task group has already exited, so the
    cancel-scope fire is a no-op). The retry must be suppressed and the sample
    resolved as the same interrupt a moment later (at the retry attempt's
    queue check) would resolve it: counted cancelled (not errored), absent
    from the log, its buffered events removed.
    """
    from inspect_ai._control.cancel import CancelTaskResult
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import (
        get_eval_states,
        record_sample_cancelled,
        record_sample_errored,
    )
    from inspect_ai._eval.task.log import TaskLogger

    attempts = 0
    sweep_results: list[CancelTaskResult] = []
    recorded: list[str] = []
    removed: list[tuple[str | int, int]] = []

    @solver(name="drain_window_error_solver")
    def drain_window_error_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("boom")

        return solve

    async def cleanup(state: TaskState) -> None:
        # runs in the errored attempt's drain window — after the sample's
        # task group has exited, before the retry decision — where the
        # sweep still sees the sample as in flight and interrupts it
        result = ctl_cancel_task(get_eval_states()[0].task_id, action="score")
        if result is not None:
            sweep_results.append(result)

    def recording_cancelled(eval_id: str, **kwargs: Any) -> None:
        recorded.append("cancelled")
        record_sample_cancelled(eval_id, **kwargs)

    def recording_errored(eval_id: str, **kwargs: Any) -> None:
        recorded.append("errored")
        record_sample_errored(eval_id, **kwargs)

    original_remove = TaskLogger.remove_sample

    def recording_remove(self: TaskLogger, id: str | int, epoch: int) -> None:
        removed.append((id, epoch))
        original_remove(self, id, epoch)

    with tempfile.TemporaryDirectory() as log_dir:
        with (
            patch(
                "inspect_ai._eval.task.run.record_sample_cancelled",
                recording_cancelled,
            ),
            patch(
                "inspect_ai._eval.task.run.record_sample_errored",
                recording_errored,
            ),
            patch.object(TaskLogger, "remove_sample", recording_remove),
        ):
            logs = inspect_eval(
                Task(
                    dataset=[Sample(id=1, input="x", target="y")],
                    solver=[drain_window_error_solver()],
                    scorer=includes(),
                    cleanup=cleanup,
                    name="task_drain_window_interrupt",
                ),
                log_dir=log_dir,
                model="mockllm/model",
                retry_on_error=3,
            )

        # the sweep saw the sample as in flight and applied
        assert len(sweep_results) == 1
        sweep = sweep_results[0]
        assert sweep["ok"] is True and sweep["in_flight"] == 1
        # the retry was suppressed
        assert attempts == 1
        # counted cancelled — never errored — and its buffered events removed
        assert recorded == ["cancelled"]
        assert removed == [(1, 1)]
        # abandoned: the eval completes with the sample absent from the log
        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        assert not log.samples


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

    resolution_pending = threading.Event()
    eval_returned = threading.Event()

    @solver(name="stamp_resolution_solver")
    def stamp_resolution_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            eval_state = get_eval_states()[0]
            assert eval_state.task_cancel is not None
            # stamp the resolution on the raw handle without interrupting
            # this sample — the pending-graceful-resolution state (e.g. a
            # `--score` cancel stalled on a hung sample/scorer)
            eval_state.task_cancel.request("score")
            resolution_pending.set()
            await anyio.sleep(10)
            return state

        return solve

    def send_sigint() -> None:
        # interrupt only once the solver has stamped the resolution: a fixed
        # head start races eval startup, and on a slow runner the SIGINT can
        # land before the log exists (so nothing is written). The timeout is
        # a hang guard for a solver that never runs — the test then fails on
        # its assertions rather than stalling.
        resolution_pending.wait(60)
        # let the solver park in its sleep first so the interrupt lands in
        # the idle event loop, as a real ctrl+c during a stall would
        time.sleep(0.5)
        # a single SIGINT can be silently lost: the KeyboardInterrupt it
        # raises lands at an arbitrary bytecode boundary in the main thread,
        # and if that happens to be inside a context that swallows exceptions
        # (e.g. a weakref finalizer callback reports it as "unraisable" and
        # drops it) the eval never sees it. Resend until the eval unwinds —
        # the interval is generous so a delivered interrupt has ample time to
        # finalize the log and return before another could land mid-write.
        while not eval_returned.is_set():
            os.kill(os.getpid(), signal.SIGINT)
            eval_returned.wait(3)

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
    finally:
        eval_returned.set()
    sigint_thread.join(timeout=5)

    log_files = list_eval_logs(str(tmp_path))
    assert len(log_files) == 1
    log = read_eval_log(log_files[0].name)
    assert log.status == "cancelled"
    assert log.error is None


# ---------------------------------------------------------------------------
# per-sample cancel of an initializing sample
# (design/ctl/initializing-sample-cancel.md)
# ---------------------------------------------------------------------------


_init_hook: Callable[[], Awaitable[None]] | None = None
_init_events: list[str] = []


@sandboxenv(name="init_cancel")
class _InitCancelSandbox(SandboxEnvironment):
    """A sandbox whose `sample_init` runs a test hook mid-initialization.

    The hook runs after the sample's ``ActiveSample`` is registered and
    before it starts — the initializing window — so a test can issue the
    cancel directive from exactly where an operator's would land.
    """

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        _init_events.append("sample_init")
        if _init_hook is not None:
            await _init_hook()
        return {"default": _InitCancelSandbox()}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        _init_events.append("sample_cleanup")

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
    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        raise NotImplementedError

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, *, user: str | None = None
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], *, user: str | None = None
    ) -> bytes: ...

    @override
    async def read_file(
        self, file: str, text: bool = True, *, user: str | None = None
    ) -> str | bytes:
        raise NotImplementedError


@contextmanager
def _init_hook_installed(hook: Callable[[], Awaitable[None]]) -> Iterator[None]:
    global _init_hook
    _init_events.clear()
    _init_hook = hook
    try:
        yield
    finally:
        _init_hook = None


def _init_cancel_task(name: str, solve_fn: Solver) -> Task:
    return Task(
        dataset=[Sample(id=1, input="x", target="y")],
        solver=[solve_fn],
        scorer=includes(),
        sandbox="init_cancel",
        name=name,
    )


@solver(name="init_cancel_solver")
def _init_cancel_solver(solved: list[int | str | None]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # a deferred interrupt fires before the plan runs; its cancellation
        # is delivered at this checkpoint (the sleep is only an upper bound
        # on the propagation window)
        await anyio.sleep(10)
        solved.append(state.sample_id)
        return state

    return solve


@pytest.mark.parametrize("action", ["cancel", "score"])
def test_sample_cancel_while_initializing_resolves_at_start(
    action: Literal["cancel", "score"], tmp_path: Path
) -> None:
    """`sample cancel` of an initializing sample is deferred and fires at start.

    The directive lands while the sandbox is being provisioned: it is
    accepted (`changed: true`, with a reason saying the sample will resolve
    as it starts), a repeat is the no-op naming the pending action, and the
    sample resolves — cancelled, or scored with an operator limit — without
    its plan ever running. The sandbox is fully built and then torn down
    normally, and a cancelled sample is counted cancelled, not errored.
    """
    from inspect_ai._control.cancel import CancelSampleResult
    from inspect_ai._control.cancel import cancel_sample as ctl_cancel_sample
    from inspect_ai._control.eval_state import (
        get_eval_states,
        record_sample_cancelled,
        record_sample_errored,
    )
    from inspect_ai._util.error import is_cancellation_message

    results: list[CancelSampleResult | None] = []
    solved: list[int | str | None] = []
    recorded: list[str] = []

    async def hook() -> None:
        eval_id = get_eval_states()[0].eval_id
        results.append(await ctl_cancel_sample(eval_id, "1", 1, action=action))
        # a repeat while still initializing: the no-op, first resolution wins
        results.append(await ctl_cancel_sample(eval_id, "1", 1, action="error"))

    def recording_cancelled(eval_id: str, **kwargs: Any) -> None:
        recorded.append("cancelled")
        record_sample_cancelled(eval_id, **kwargs)

    def recording_errored(eval_id: str, **kwargs: Any) -> None:
        recorded.append("errored")
        record_sample_errored(eval_id, **kwargs)

    with (
        _init_hook_installed(hook),
        patch("inspect_ai._eval.task.run.record_sample_cancelled", recording_cancelled),
        patch("inspect_ai._eval.task.run.record_sample_errored", recording_errored),
    ):
        logs = inspect_eval(
            _init_cancel_task(
                f"task_init_cancel_{action}", _init_cancel_solver(solved)
            ),
            log_dir=str(tmp_path),
            model="mockllm/model",
        )

    accepted, repeat = results
    assert accepted is not None and accepted["ok"] is True
    assert accepted["changed"] is True and accepted["action"] == action
    assert "initializing" in accepted["reason"]
    assert repeat is not None and repeat["ok"] is True
    assert repeat["changed"] is False
    assert repeat["reason"] == f"cancel already requested ({action})"

    # the plan never ran; the sandbox was built, then torn down normally
    assert solved == []
    assert _init_events == ["sample_init", "sample_cleanup"]

    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success"
    assert log.samples is not None and len(log.samples) == 1
    sample = log.samples[0]
    if action == "cancel":
        assert sample.error is not None
        assert is_cancellation_message(sample.error.message)
        assert not sample.scores
        assert recorded == ["cancelled"]
    else:
        assert sample.error is None
        assert sample.limit is not None and sample.limit.type == "operator"
        assert sample.scores
        assert recorded == []


def test_sample_cancel_while_initializing_wins_over_later_task_score(
    tmp_path: Path,
) -> None:
    """A per-sample intent stamped while initializing beats a later task stamp.

    The task-level `score` lands after the per-sample `cancel` and its sweep
    skips the initializing sample (not started). At start the per-sample
    intent fires first and exclusively — falling through to the task-level
    branch would overwrite the operator's `cancel` with `score`, since the
    runner handles the live `interrupt_action`.
    """
    from inspect_ai._control.cancel import cancel_sample as ctl_cancel_sample
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._util.error import is_cancellation_message

    solved: list[int | str | None] = []

    async def hook() -> None:
        state = get_eval_states()[0]
        accepted = await ctl_cancel_sample(state.eval_id, "1", 1, action="cancel")
        assert accepted is not None and accepted["ok"] is True
        assert accepted["changed"] is True
        stamped = ctl_cancel_task(state.task_id, action="score")
        assert stamped is not None and stamped["ok"] is True
        assert stamped["in_flight"] == 0  # the sweep never saw the sample

    with _init_hook_installed(hook):
        logs = inspect_eval(
            _init_cancel_task(
                "task_init_cancel_precedence", _init_cancel_solver(solved)
            ),
            log_dir=str(tmp_path),
            model="mockllm/model",
        )

    assert solved == []
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success"
    assert log.samples is not None and len(log.samples) == 1
    sample = log.samples[0]
    # cancelled semantics — not the task's score resolution
    assert sample.error is not None
    assert is_cancellation_message(sample.error.message)
    assert not sample.scores
    assert sample.limit is None


def test_sample_cancel_while_initializing_then_init_failure_abandons(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Init fails after the intent is stamped, retries remaining: abandoned.

    The retry predicate requires no interrupt, so the errored attempt takes
    the drain-window branch: resolved as cancelled (never errored), absent
    from the log, its buffered events removed, and not retried — and the
    error warning must say so rather than promise the retry (or, with
    ``score_on_error``, the scoring) that will not happen.
    """
    caplog.set_level("WARNING", logger="inspect_ai._eval.task.run")
    from inspect_ai._control.cancel import cancel_sample as ctl_cancel_sample
    from inspect_ai._control.eval_state import (
        get_eval_states,
        record_sample_cancelled,
        record_sample_errored,
    )
    from inspect_ai._eval.task.log import TaskLogger

    solved: list[int | str | None] = []
    recorded: list[str] = []
    removed: list[tuple[str | int, int]] = []

    async def hook() -> None:
        eval_id = get_eval_states()[0].eval_id
        accepted = await ctl_cancel_sample(eval_id, "1", 1, action="cancel")
        assert accepted is not None and accepted["ok"] is True
        raise RuntimeError("sandbox provisioning failed")

    def recording_cancelled(eval_id: str, **kwargs: Any) -> None:
        recorded.append("cancelled")
        record_sample_cancelled(eval_id, **kwargs)

    def recording_errored(eval_id: str, **kwargs: Any) -> None:
        recorded.append("errored")
        record_sample_errored(eval_id, **kwargs)

    original_remove = TaskLogger.remove_sample

    def recording_remove(self: TaskLogger, id: str | int, epoch: int) -> None:
        removed.append((id, epoch))
        original_remove(self, id, epoch)

    with (
        _init_hook_installed(hook),
        patch("inspect_ai._eval.task.run.record_sample_cancelled", recording_cancelled),
        patch("inspect_ai._eval.task.run.record_sample_errored", recording_errored),
        patch.object(TaskLogger, "remove_sample", recording_remove),
    ):
        logs = inspect_eval(
            _init_cancel_task("task_init_cancel_failure", _init_cancel_solver(solved)),
            log_dir=str(tmp_path),
            model="mockllm/model",
            retry_on_error=2,
            score_on_error=True,
        )

    # one init attempt, no retry; counted cancelled, never errored
    assert _init_events.count("sample_init") == 1
    assert solved == []
    assert recorded == ["cancelled"]
    assert removed == [(1, 1)]
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success"
    assert not log.samples
    # the init error was logged, naming the cancel rather than promising the
    # retry or the score that will not happen
    errors = [
        r.getMessage() for r in caplog.records if "Sample error" in r.getMessage()
    ]
    assert len(errors) == 1
    assert errors[0].endswith("Sample will be cancelled.")
    assert "will be retried" not in errors[0]
    assert "will be scored" not in errors[0]


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


def _task_cancel_handle(eval_id: str) -> TaskCancel:
    """The registered `TaskCancel` of a running attempt (what `ctl task cancel` fires)."""
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    assert state is not None and state.task_cancel is not None
    return state.task_cancel


def _fire_on_log_finish(
    monkeypatch: pytest.MonkeyPatch,
    task_name: str,
    status: str,
    cancel_type: Literal["abort", "retry"],
    hang: bool = False,
) -> None:
    """Fire `cancel_type` on `task_name`'s first attempt as it starts writing its final log with `status`.

    With `hang`, the write then never finishes.
    """
    from inspect_ai._eval.task.log import TaskLogger

    original_log_finish = TaskLogger.log_finish
    fired: list[str] = []

    async def log_finish(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        if self.eval.task == task_name and args[0] == status and not fired:
            fired.append(self.eval.eval_id)
            _task_cancel_handle(self.eval.eval_id).request(cancel_type)
            if hang:
                await anyio.sleep_forever()
        return await original_log_finish(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_finish", log_finish)


async def _disk_statuses(log_dir: Path) -> list[tuple[str, str]]:
    from inspect_ai.log import list_eval_logs, read_eval_log_async

    return sorted(
        [
            (log.eval.task, log.status)
            for log in [
                await read_eval_log_async(info, header_only=True)
                for info in list_eval_logs(str(log_dir))
            ]
        ]
    )


def _plain_task(name: str, runs: list[str]) -> Task:
    @solver(name=f"record_run_{name}_{id(runs)}")
    def record_run() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            runs.append(name)
            return state

        return solve

    return Task(dataset=[Sample(input="x", target="y")], solver=record_run(), name=name)


def _failing_task(name: str, runs: list[str], failures: int) -> Task:
    """A task whose sample raises on its first `failures` attempts."""

    @solver(name=f"fail_run_{name}_{id(runs)}")
    def fail_run() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            runs.append(name)
            if runs.count(name) <= failures:
                raise RuntimeError("sample failure")
            return state

        return solve

    return Task(dataset=[Sample(input="x", target="y")], solver=fail_run(), name=name)


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_type", ["abort", "retry"])
async def test_cancel_during_error_log_write_ends_only_that_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_type: Literal["abort", "retry"],
) -> None:
    """An abort or retry request during a failing task's error-log write ends (or retries) only that task.

    The write is shielded, so it completes: the task returns the error log
    it wrote, and the queued task still runs. An abort is not retried; a
    retry is.
    """
    from inspect_ai import eval_async

    runs: list[str] = []
    _fire_on_log_finish(monkeypatch, "a", "error", cancel_type)
    logs = await eval_async(
        [_failing_task("a", runs, failures=1), _plain_task("b", runs)],
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )

    if cancel_type == "abort":
        assert [(log.eval.task, log.status) for log in logs] == [
            ("a", "error"),
            ("b", "success"),
        ]
        assert logs[0].error is not None
        assert "sample failure" in logs[0].error.message
        assert logs[0].samples is not None and len(logs[0].samples) == 1
        assert runs == ["a", "b"]
        assert await _disk_statuses(tmp_path) == [("a", "error"), ("b", "success")]
    else:
        assert [(log.eval.task, log.status) for log in logs] == [
            ("a", "success"),
            ("b", "success"),
        ]
        # the retry is queued behind b
        assert runs == ["a", "b", "a"]
        assert await _disk_statuses(tmp_path) == [
            ("a", "error"),
            ("a", "success"),
            ("b", "success"),
        ]


@pytest.mark.anyio
async def test_abort_pending_before_error_log_write_keeps_full_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An abort made after a sample failed but before the error-log write ends only that task.

    The abort has already cancelled the task when the write starts, so the
    write is shielded: the task returns its full error log, the TaskSource
    hears about it, and the queued task runs.
    """
    from inspect_ai import eval_async
    from inspect_ai._eval.task.log import collect_eval_data

    handles: dict[str, TaskCancel] = {}
    pending_at_write: list[object] = []

    async def capturing_task_run(options: Any, task_cancel: TaskCancel) -> EvalLog:
        handles[options.task.name] = task_cancel
        return await original_task_run(options, task_cancel=task_cancel)

    def collect_and_abort(stats: Any) -> None:
        # called in task a's error handler just before its error-log write
        if "a" in handles and not pending_at_write:
            handles["a"].request("abort")
            pending_at_write.append(handles["a"].cancel_type)
        collect_eval_data(stats)

    monkeypatch.setattr("inspect_ai._eval.run.task_run", capturing_task_run)
    monkeypatch.setattr(
        "inspect_ai._eval.task.run.collect_eval_data", collect_and_abort
    )
    runs: list[str] = []
    source = _RecordingSource(
        [_failing_task("a", runs, failures=1), _plain_task("b", runs)]
    )
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )

    assert pending_at_write == ["abort"]
    assert [(log.eval.task, log.status) for log in logs] == [
        ("a", "error"),
        ("b", "success"),
    ]
    assert logs[0].error is not None
    assert "sample failure" in logs[0].error.message
    assert logs[0].samples is not None and len(logs[0].samples) == 1
    assert [e.split(":")[1:3] for e in source.events if "task_complete" in e] == [
        ["a", "error"],
        ["b", "success"],
    ]
    assert runs == ["a", "b"]
    assert await _disk_statuses(tmp_path) == [("a", "error"), ("b", "success")]


def _record_task_display_results(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[object]]:
    """Record each task display's `complete()` results, keyed by task display name."""
    import inspect_ai._eval.task.run as task_run_module
    from inspect_ai._display import display as real_display

    results: dict[str, list[object]] = {}

    class _RecordingTaskDisplay:
        def __init__(self, inner: Any, name: str) -> None:
            self.inner = inner
            self.name = name

        def __getattr__(self, attr: str) -> Any:
            return getattr(self.inner, attr)

        def complete(self, result: object) -> None:
            results.setdefault(self.name, []).append(result)
            self.inner.complete(result)

    class _RecordingDisplay:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __getattr__(self, attr: str) -> Any:
            return getattr(self.inner, attr)

        @contextmanager
        def task(self, profile: Any) -> Iterator[Any]:
            with self.inner.task(profile) as td:
                yield _RecordingTaskDisplay(td, profile.name)

    monkeypatch.setattr(
        task_run_module, "display", lambda: _RecordingDisplay(real_display())
    )
    return results


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_type", ["abort", "retry"])
async def test_abort_of_stuck_error_log_write_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_type: Literal["abort", "retry"],
) -> None:
    """An abort or retry request ends an error-log write that never finishes, after the timeout.

    The task is then reported like a failed log write, its display shows
    it finished with the sample's error, and the run continues.
    """
    import inspect_ai._eval.task.run as task_run_module
    from inspect_ai import eval_async

    monkeypatch.setattr(task_run_module, "ABORTED_LOG_WRITE_TIMEOUT", 0.2)
    displayed = _record_task_display_results(monkeypatch)
    runs: list[str] = []
    _fire_on_log_finish(monkeypatch, "a", "error", cancel_type, hang=True)
    logs = await eval_async(
        [_failing_task("a", runs, failures=1), _plain_task("b", runs)],
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )

    first_attempt = displayed["a"][0]
    assert isinstance(first_attempt, TaskError)
    assert "sample failure" in str(first_attempt.exc_value)
    if cancel_type == "abort":
        assert [(log.eval.task, log.status) for log in logs] == [
            ("a", "error"),
            ("b", "success"),
        ]
        assert logs[0].error is not None
        assert "did not finish within 0.2 seconds" in logs[0].error.message
        assert runs == ["a", "b"]
        assert await _disk_statuses(tmp_path) == [("a", "started"), ("b", "success")]
    else:
        # the failed write is retried like any failed write, behind b
        assert [(log.eval.task, log.status) for log in logs] == [
            ("a", "success"),
            ("b", "success"),
        ]
        assert runs == ["a", "b", "a"]


@pytest.mark.anyio
async def test_abort_before_error_log_write_shields_it_for_bounded_time() -> None:
    """A request made before the write shields it from the cancellation, up to the timeout."""
    import inspect_ai._eval.task.run as task_run_module
    from inspect_ai._eval.task.run import abort_bounded_write

    pending = TaskCancel(can_retry=False, apply=lambda _: None)
    pending.request("abort")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_run_module, "ABORTED_LOG_WRITE_TIMEOUT", 0.05)
        with anyio.CancelScope() as task_scope:
            task_scope.cancel()
            with abort_bounded_write(pending):
                await anyio.sleep(0)
            with pytest.raises(TimeoutError):
                with abort_bounded_write(pending):
                    await anyio.sleep_forever()
    assert pending.log_write_scope is None


@pytest.mark.anyio
async def test_run_cancel_interrupts_error_log_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run-level cancellation during a failing task's error-log write interrupts it at once.

    No abort or retry request is pending, so the write is not shielded.
    """
    from inspect_ai import eval_async
    from inspect_ai._eval.task.log import TaskLogger

    original_log_finish = TaskLogger.log_finish
    scopes: list[anyio.CancelScope] = []
    write_ran_to_bound: list[bool] = []

    async def log_finish(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        if args[0] == "error":
            scopes[0].cancel()
            # bounds the test if the write were shielded from the cancellation
            with anyio.move_on_after(5) as bound:
                await anyio.sleep_forever()
            write_ran_to_bound.append(bound.cancelled_caught)
        return await original_log_finish(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_finish", log_finish)
    runs: list[str] = []
    with anyio.CancelScope() as scope:
        scopes.append(scope)
        await eval_async(
            [_failing_task("a", runs, failures=1), _plain_task("b", runs)],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=1,
            task_retry_attempts=1,
        )

    assert write_ran_to_bound == []
    assert runs == ["a"]


def _on_log_finalized(
    monkeypatch: pytest.MonkeyPatch,
    where: str,
    action: Callable[[str], Awaitable[None]],
) -> list[str]:
    """Run `action(eval_id)` once, after the recorder has finalized task `a`'s log.

    `where` is the logger's cleanup, before it releases the realtime buffer
    (`buffer_release`) or as it stops the stale-flush timer at the end
    (`logger_cleanup`), an awaiting `on_task_end` hook (`task_end_hook`) or
    a legacy telemetry hook after `task_run`'s handlers (`telemetry`).
    Returns the eval ids it ran for.
    """
    import inspect_ai.hooks._legacy as legacy_hooks
    from inspect_ai._eval.task.log import TaskLogger

    fired: list[str] = []

    async def fire(eval_id: str) -> None:
        fired.append(eval_id)
        await action(eval_id)

    if where == "task_end_hook":
        from inspect_ai.hooks import _hooks

        original_emit_task_end = _hooks.emit_task_end

        async def emit_task_end(
            logger: TaskLogger, log: EvalLog, pending: list[Any], *, raise_limits: bool
        ) -> None:
            await original_emit_task_end(
                logger, log, pending, raise_limits=raise_limits
            )
            if log.eval.task == "a" and not fired:
                await fire(log.eval.eval_id)

        monkeypatch.setattr("inspect_ai.hooks._hooks.emit_task_end", emit_task_end)
    elif where == "telemetry":
        written: list[str] = []
        original_log_finish = TaskLogger.log_finish

        async def log_finish(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
            if self.eval.task == "a":
                written.append(self.eval.eval_id)
            return await original_log_finish(self, *args, **kwargs)

        async def send_telemetry(type: str, json: str) -> bool:
            if written and type == "eval_log_location" and not fired:
                await fire(written[0])
            return False

        monkeypatch.setattr(TaskLogger, "log_finish", log_finish)
        monkeypatch.setattr(legacy_hooks, "_send_telemetry", send_telemetry)
    elif where == "buffer_release":
        original_release = TaskLogger._release_buffer_db

        async def release_buffer_db(self: TaskLogger, *, keep: bool) -> None:
            if self.eval.task == "a" and self.finished and not fired:
                await fire(self.eval.eval_id)
            await original_release(self, keep=keep)

        monkeypatch.setattr(TaskLogger, "_release_buffer_db", release_buffer_db)
    else:
        original_stop = TaskLogger._stop_stale_flush_timer

        async def stop_stale_flush_timer(self: TaskLogger) -> None:
            if self.eval.task == "a" and self.finished and not fired:
                await fire(self.eval.eval_id)
            await original_stop(self)

        monkeypatch.setattr(
            TaskLogger, "_stop_stale_flush_timer", stop_stale_flush_timer
        )
    return fired


_POST_ABORT_WAIT = 0.5
"""Seconds an action waits after its cancellation, longer than the tests' 0.2 s write deadline.

The wait is bounded because the logger's teardown is shielded: there it
runs to its end, and the cancellation lands after the teardown.
"""


async def _abort_and_wait(eval_id: str) -> None:
    _task_cancel_handle(eval_id).request("abort")
    await anyio.sleep(_POST_ABORT_WAIT)


def _record_teardown(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """Record task `a`'s logger and its realtime buffer database as it starts finishing its log."""
    from inspect_ai._eval.task.log import TaskLogger

    finishing: list[tuple[Any, Any]] = []
    original_log_finish = TaskLogger.log_finish

    async def log_finish(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        if self.eval.task == "a":
            finishing.append((self, self._buffer_db))
        return await original_log_finish(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_finish", log_finish)
    return finishing


def _assert_torn_down(finishing: list[tuple[Any, Any]]) -> None:
    """Assert the logger cleared its pending samples and closed and removed its buffer database."""
    assert finishing
    for logger, buffer_db in finishing:
        assert logger.flush_pending == []
        assert logger._buffer_db is None
        assert buffer_db is not None
        assert not buffer_db.db_path.exists()


async def _raise_stray_cancellation() -> None:
    """Raise a cancellation caught from a scope that has since exited."""
    saved: list[BaseException] = []
    with anyio.CancelScope() as scope:
        scope.cancel()
        try:
            await anyio.sleep(0)
        except anyio.get_cancelled_exc_class() as ex:
            saved.append(ex)
            raise
    raise saved[0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "where", ["buffer_release", "logger_cleanup", "task_end_hook", "telemetry"]
)
async def test_abort_after_log_finalized_returns_written_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """An abort that lands once the recorder has finalized the log returns that log.

    It lands in the logger's cleanup after the recorder wrote the log, in an
    awaiting `on_task_end` hook, or in a legacy telemetry hook after
    `task_run`'s handlers. The logger's cleanup still completes, the task
    returns its written log, its display shows it succeeded, the TaskSource
    hears about it once, and the run continues.
    """
    from inspect_ai import eval_async

    fired = _on_log_finalized(monkeypatch, where, _abort_and_wait)
    finishing = _record_teardown(monkeypatch)
    displayed = _record_task_display_results(monkeypatch)
    runs: list[str] = []
    source = _RecordingSource([_plain_task("a", runs), _plain_task("b", runs)])
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )

    assert fired
    _assert_torn_down(finishing)
    assert [type(result).__name__ for result in displayed["a"]] == ["TaskSuccess"]
    assert [(log.eval.task, log.status) for log in logs] == [
        ("a", "success"),
        ("b", "success"),
    ]
    assert [e.split(":")[1:3] for e in source.events if "task_complete" in e] == [
        ["a", "success"],
        ["b", "success"],
    ]
    assert runs == ["a", "b"]
    assert await _disk_statuses(tmp_path) == [("a", "success"), ("b", "success")]


@pytest.mark.anyio
@pytest.mark.parametrize("where", ["buffer_release", "logger_cleanup"])
async def test_abort_deadline_in_logger_cleanup_returns_written_error_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """An abort whose write deadline expires in the logger's cleanup returns the written error log.

    The recorder had already written the full error log, so the cleanup
    completes, the task returns that log rather than a failed-write log,
    the TaskSource hears about it once, and the run continues.
    """
    import inspect_ai._eval.task.run as task_run_module
    from inspect_ai import eval_async

    monkeypatch.setattr(task_run_module, "ABORTED_LOG_WRITE_TIMEOUT", 0.2)
    fired = _on_log_finalized(monkeypatch, where, _abort_and_wait)
    finishing = _record_teardown(monkeypatch)
    displayed = _record_task_display_results(monkeypatch)
    runs: list[str] = []
    source = _RecordingSource(
        [_failing_task("a", runs, failures=1), _plain_task("b", runs)]
    )
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )

    assert fired
    _assert_torn_down(finishing)
    assert len(displayed["a"]) == 1
    assert isinstance(displayed["a"][0], TaskError)
    assert [(log.eval.task, log.status) for log in logs] == [
        ("a", "error"),
        ("b", "success"),
    ]
    assert logs[0].error is not None
    assert "sample failure" in logs[0].error.message
    assert logs[0].samples is not None and len(logs[0].samples) == 1
    assert [e.split(":")[1:3] for e in source.events if "task_complete" in e] == [
        ["a", "error"],
        ["b", "success"],
    ]
    assert runs == ["a", "b"]
    assert await _disk_statuses(tmp_path) == [("a", "error"), ("b", "success")]


@pytest.mark.anyio
@pytest.mark.parametrize("where", ["logger_cleanup", "task_end_hook", "telemetry"])
async def test_stray_cancellation_after_log_finalized_ends_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """A cancellation exception raised after the log was written, with no cancellation behind it, ends the run.

    The task group would otherwise absorb it, and the task would return no
    log, which the dispatcher reads as a run-level cancellation.
    """
    from inspect_ai import eval_async

    async def raise_stray(eval_id: str) -> None:
        await _raise_stray_cancellation()

    fired = _on_log_finalized(monkeypatch, where, raise_stray)
    runs: list[str] = []
    with pytest.raises(RuntimeError, match="Task 'a' raised a cancellation"):
        await eval_async(
            [_plain_task("a", runs), _plain_task("b", runs)],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=1,
        )

    assert fired
    assert runs == ["a"]
    assert await _disk_statuses(tmp_path) == [("a", "success")]


@pytest.mark.anyio
@pytest.mark.parametrize("where", ["logger_cleanup", "task_end_hook", "telemetry"])
async def test_run_cancel_after_log_finalized_stops_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """A run-level cancellation after the task's log was written stops the run, with no error."""
    from inspect_ai import eval_async

    scopes: list[anyio.CancelScope] = []

    async def cancel_run(eval_id: str) -> None:
        scopes[0].cancel()
        await anyio.sleep(_POST_ABORT_WAIT)

    fired = _on_log_finalized(monkeypatch, where, cancel_run)
    runs: list[str] = []
    with anyio.CancelScope() as scope:
        scopes.append(scope)
        await eval_async(
            [_plain_task("a", runs), _plain_task("b", runs)],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=1,
        )

    assert fired
    assert runs == ["a"]
    assert await _disk_statuses(tmp_path) == [("a", "success")]


@pytest.mark.anyio
async def test_abort_before_any_log_write_reports_errored_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An abort that interrupts `log_start()` leaves an errored log, and the run continues.

    The task's display shows it finished with the abort's error.
    """
    from inspect_ai import eval_async
    from inspect_ai._eval.task.log import TaskLogger

    handles: dict[str, TaskCancel] = {}

    async def capturing_task_run(options: Any, task_cancel: TaskCancel) -> EvalLog:
        handles[options.task.name] = task_cancel
        return await original_task_run(options, task_cancel=task_cancel)

    original_log_start = TaskLogger.log_start

    async def log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> None:
        if self.eval.task == "a":
            handles["a"].request("abort")
            await anyio.sleep_forever()
        await original_log_start(self, *args, **kwargs)

    monkeypatch.setattr("inspect_ai._eval.run.task_run", capturing_task_run)
    monkeypatch.setattr(TaskLogger, "log_start", log_start)
    displayed = _record_task_display_results(monkeypatch)
    runs: list[str] = []
    logs = await eval_async(
        [_plain_task("a", runs), _plain_task("b", runs)],
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )

    assert [(log.eval.task, log.status) for log in logs] == [
        ("a", "error"),
        ("b", "success"),
    ]
    assert logs[0].error is not None
    assert "cancelled by user (abort)" in logs[0].error.message
    assert runs == ["b"]
    assert len(displayed["a"]) == 1
    assert isinstance(displayed["a"][0], TaskError)
    assert "cancelled by user (abort)" in str(displayed["a"][0].exc_value)


@pytest.mark.anyio
async def test_abort_racing_success_log_write_keeps_run_going(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An abort that interrupts a successful task's log write ends only that task.

    The interrupted success write goes through the task's cancellation
    handler, which writes the abort's error log under a shield.
    """
    from inspect_ai import eval_async

    runs: list[str] = []
    _fire_on_log_finish(monkeypatch, "a", "success", "abort")
    logs = await eval_async(
        [_plain_task("a", runs), _plain_task("b", runs)],
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
        task_retry_attempts=1,
    )

    assert [(log.eval.task, log.status) for log in logs] == [
        ("a", "error"),
        ("b", "success"),
    ]
    assert logs[0].error is not None
    assert "cancelled by user (abort)" in logs[0].error.message
    assert runs == ["a", "b"]
    assert await _disk_statuses(tmp_path) == [("a", "error"), ("b", "success")]


@pytest.mark.anyio
@pytest.mark.parametrize("with_abort", [False, True])
async def test_run_cancel_stops_dispatch(tmp_path: Path, with_abort: bool) -> None:
    """A run-level cancellation stops dispatching, also when the task was aborted too.

    Pins the dispatcher's contract: only a run-level cancellation ends the
    run; a task's own abort ends only that task.
    """
    from inspect_ai import eval_async

    runs: list[str] = []
    scopes: list[anyio.CancelScope] = []

    @solver(name=f"cancel_run_{id(runs)}")
    def cancel_run() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            from inspect_ai.log._samples import sample_active

            runs.append("a")
            if with_abort:
                active = sample_active()
                assert active is not None
                _task_cancel_handle(active.eval_id).request("abort")
            scopes[0].cancel()
            await anyio.sleep_forever()
            return state

        return solve

    with anyio.CancelScope() as scope:
        scopes.append(scope)
        await eval_async(
            [
                Task(dataset=[Sample(input="x")], solver=cancel_run(), name="a"),
                _plain_task("b", runs),
            ],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=1,
            task_retry_attempts=1,
        )

    assert runs == ["a"]
    assert await _disk_statuses(tmp_path) == [
        ("a", "error" if with_abort else "cancelled")
    ]


class _RecordingSource(TaskSource):
    """A `TaskSource` that records each `task_complete` and `next_tasks` call.

    `task_complete` awaits before recording, so a call made inside a
    cancelled scope would be interrupted and not recorded. It also records
    the active model, to show which task's context the call runs in.
    """

    def __init__(self, tasks: list[Task]) -> None:
        self.tasks = tasks
        self.events: list[str] = []

    def initial_tasks(self) -> list[Task]:
        return self.tasks

    async def task_complete(self, log: EvalLog) -> list[Task] | None:
        from inspect_ai.model._model import active_model

        await anyio.sleep(0)
        error = log.error.message if log.error is not None else ""
        self.events.append(
            f"task_complete:{log.eval.task}:{log.status}:{active_model()}:{error}"
        )
        return None

    async def next_tasks(self) -> list[Task] | None:
        self.events.append("next_tasks")
        return None


@pytest.mark.anyio
async def test_task_source_task_complete_runs_to_completion_after_abort(
    tmp_path: Path,
) -> None:
    """An aborted task's `task_complete` call is not interrupted by the abort.

    The abort lands while the sample runs, so the task writes its abort
    error log; the TaskSource's `task_complete` then awaits and still
    finishes, in the task's context (its model), before `next_tasks()`.
    """
    from inspect_ai import eval_async
    from inspect_ai.log._samples import sample_active

    @solver(name=f"abort_self_{id(tmp_path)}")
    def abort_self() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            active = sample_active()
            assert active is not None
            _task_cancel_handle(active.eval_id).request("abort")
            await anyio.sleep_forever()
            return state

        return solve

    a = Task(dataset=[Sample(input="x")], solver=abort_self(), name="a")
    a.model = get_model("mockllm/a-model")
    source = _RecordingSource([a])
    logs = await eval_async(source, model="mockllm/model", log_dir=str(tmp_path))

    assert source.events == [
        "task_complete:a:error:mockllm/a-model:"
        "TerminateTaskError('Task cancelled by user (abort)')",
        "next_tasks",
    ]
    assert [(log.eval.task, log.status) for log in logs] == [("a", "error")]
    assert await _disk_statuses(tmp_path) == [("a", "error")]


@pytest.mark.anyio
async def test_preview_does_not_report_to_task_source(tmp_path: Path) -> None:
    """A preview (`run_samples=False`) runs no samples, so `task_complete` is not called."""
    from inspect_ai import eval_async

    runs: list[str] = []
    source = _RecordingSource([_plain_task("a", runs)])
    logs = await eval_async(
        source, model="mockllm/model", log_dir=str(tmp_path), run_samples=False
    )

    assert not [event for event in source.events if event.startswith("task_complete")]
    assert [(log.eval.task, log.status) for log in logs] == [("a", "started")]
    assert runs == []


@pytest.mark.anyio
async def test_cancel_handle_does_not_keep_task_log_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task's registered cancel handle does not keep its returned log alive.

    The handle stays registered after the attempt ends (a late abort can
    still stop a retry), so it must hold only what that check needs.
    """
    import gc
    import weakref

    from inspect_ai import eval_async

    handles: list[TaskCancel] = []

    async def capturing_task_run(options: Any, task_cancel: TaskCancel) -> EvalLog:
        handles.append(task_cancel)
        return await original_task_run(options, task_cancel=task_cancel)

    monkeypatch.setattr("inspect_ai._eval.run.task_run", capturing_task_run)
    runs: list[str] = []
    logs = await eval_async(
        [_plain_task("a", runs)], model="mockllm/model", log_dir=str(tmp_path)
    )
    assert logs[0].status == "success" and logs[0].samples
    log_ref = weakref.ref(logs[0])
    sample_ref = weakref.ref(logs[0].samples[0])
    del logs
    gc.collect()

    assert handles
    assert log_ref() is None
    assert sample_ref() is None


@pytest.mark.anyio
async def test_task_complete_raising_stray_cancellation_ends_run(
    tmp_path: Path,
) -> None:
    """A cancellation exception that `task_complete` raises on its own ends the run.

    No cancellation of the run caused it, so it is not absorbed: the run
    fails as for any `task_complete` error, and the queued task never runs.
    """
    from inspect_ai import eval_async

    class _StrayCancelSource(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_plain_task("a", runs), _plain_task("b", runs)]

        async def task_complete(self, log: EvalLog) -> None:
            await _raise_stray_cancellation()

    runs: list[str] = []
    with pytest.raises(RuntimeError, match="task_complete\\(\\) for task 'a'"):
        await eval_async(
            _StrayCancelSource(),
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=1,
        )

    assert runs == ["a"]
    assert await _disk_statuses(tmp_path) == [("a", "success")]


class _LateCancelSource(TaskSource):
    """Answers the task's cancel dialog with `cancel_type` while `task_complete` runs."""

    def __init__(self, task: Task, cancel_type: Literal["abort", "retry"]) -> None:
        self.task = task
        self.cancel_type: Literal["abort", "retry"] = cancel_type
        self.completed: list[str] = []

    def initial_tasks(self) -> list[Task]:
        return [self.task]

    async def task_complete(self, log: EvalLog) -> None:
        self.completed.append(log.status)
        if len(self.completed) == 1:
            _task_cancel_handle(log.eval.eval_id).request(self.cancel_type)
        await anyio.sleep(0)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failures,cancel_type,completed",
    [(0, "retry", ["success"]), (1, "abort", ["error"])],
)
async def test_cancel_after_task_finished_does_not_rerun_it(
    tmp_path: Path,
    failures: int,
    cancel_type: Literal["abort", "retry"],
    completed: list[str],
) -> None:
    """A cancel answered while `task_complete` runs cannot re-run the finished task.

    A late "retry" for a task that succeeded is ignored, so the task runs
    once and the source hears about it once. A late abort for a task that
    errored is still honoured: the dispatcher does not retry it.
    """
    from inspect_ai import eval_async

    runs: list[str] = []
    source = _LateCancelSource(_failing_task("a", runs, failures), cancel_type)
    logs = await eval_async(
        source,
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
    )

    assert runs == ["a"]
    assert source.completed == completed
    assert [log.status for log in logs] == completed
    assert await _disk_statuses(tmp_path) == [("a", completed[0])]


@pytest.mark.anyio
@pytest.mark.parametrize("debug_errors", [False, True])
async def test_task_complete_error_keeps_task_log(
    tmp_path: Path, debug_errors: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """An exception from `task_complete` is logged, and the task keeps its log.

    It is not reported as a failure of the task's log write: the task's
    success log stays as written, is returned, and the task is not retried.
    With `debug_errors` the exception ends the run, naming `task_complete`.
    The logged error keeps the callback's traceback.
    """
    from inspect_ai import eval_async

    caplog.set_level("ERROR", logger="inspect_ai._eval.task.run")

    class _RaisingSource(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_plain_task("a", runs)]

        async def task_complete(self, log: EvalLog) -> None:
            raise RuntimeError("task_complete failed")

    runs: list[str] = []
    kwargs: dict[str, Any] = dict(
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
        debug_errors=debug_errors,
    )
    if debug_errors:
        with pytest.raises(RuntimeError, match="task_complete failed") as raised:
            await eval_async(_RaisingSource(), **kwargs)
        assert "TaskSource.task_complete() for task 'a'" in "".join(
            raised.value.__notes__
        )
    else:
        logs = await eval_async(_RaisingSource(), **kwargs)
        assert [log.status for log in logs] == ["success"]
        assert logs[0].error is None
        (record,) = [
            r for r in caplog.records if "task_complete() raised" in r.getMessage()
        ]
        assert record.exc_info is not None
        assert record.exc_info[1] is not None
        assert str(record.exc_info[1]) == "task_complete failed"
        assert any(
            frame.name == "task_complete"
            for frame in traceback.extract_tb(record.exc_info[2])
        )

    assert runs == ["a"]
    assert await _disk_statuses(tmp_path) == [("a", "success")]
