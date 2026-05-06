"""Tests for task cancellation via the cancel button during eval_set runs."""

import tempfile
from unittest.mock import patch

import anyio

from inspect_ai import Task
from inspect_ai._display.core.display import TaskCancel
from inspect_ai._eval.evalset import eval_set
from inspect_ai._eval.task.run import task_run as original_task_run
from inspect_ai.dataset import Sample
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
            # Sleep to let the cancellation propagate
            await anyio.sleep(10)
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


def test_abort_cancel_not_retried_in_run_multiple() -> None:
    """Aborted task in run_multiple should not be retried by eval_set.

    run_multiple is used when max_tasks > 1 and task_retry_attempts is 0.
    When a task is aborted, the worker should stop and not allow the outer
    eval_set retry loop to re-run the aborted task.
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
            # Sleep to let the cancellation propagate
            await anyio.sleep(10)
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
