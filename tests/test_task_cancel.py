"""Tests for task cancellation via the cancel button during eval_set runs."""

import tempfile
from unittest.mock import patch

import anyio
from test_helpers.utils import skip_if_trio

from inspect_ai import Task
from inspect_ai._display.core.display import TaskCancel
from inspect_ai._eval.evalset import eval_set
from inspect_ai._eval.run import task_run as original_task_run
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, solver


@skip_if_trio
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
    def abort_solver() -> object:
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
