# test that service errors are caught, logged, and re-raised

from typing import NamedTuple

import anyio

from inspect_ai import Task, eval
from inspect_ai.log import EvalLog
from inspect_ai.solver import Solver, solver
from inspect_ai.util import background

WORKER_ERROR = "Error in worker!"


class _ScenarioResult(NamedTuple):
    log: EvalLog
    worker_completed: bool


def _run_scenario(*, worker_raises: bool, foreground_raises: bool) -> _ScenarioResult:
    """Run one sample with a background worker and a foreground solver.

    Synchronization is event-driven rather than timing-based so the outcome is
    deterministic under load (e.g. `pytest -n auto`):

    - `worker_ready` guarantees the worker has entered its `try` block before
      the foreground acts, so cancellation cleanup (the `finally`) is always
      exercised.
    - When the worker is expected to raise, the foreground blocks forever, so
      the sample can only end via the worker's error — never by the foreground
      completing first and cancelling the worker before it raises.
    """
    worker_ready = anyio.Event()
    worker_completed = False

    async def worker() -> None:
        nonlocal worker_completed
        try:
            worker_ready.set()
            if worker_raises:
                raise RuntimeError(WORKER_ERROR)
            await anyio.sleep_forever()  # run until the sample cancels us
        finally:
            worker_completed = True

    @solver
    def start_worker() -> Solver:
        async def solve(state, generate):
            background(worker)
            return state

        return solve

    @solver
    def foreground() -> Solver:
        async def solve(state, generate):
            await worker_ready.wait()
            if foreground_raises:
                raise Exception("Error in solver!")
            if worker_raises:
                await anyio.sleep_forever()  # let the worker's error tear us down
            return state

        return solve

    log = eval(Task(solver=[start_worker(), foreground()]))[0]
    return _ScenarioResult(log=log, worker_completed=worker_completed)


def test_background_termination():
    # foreground errors -> background worker is cancelled and cleaned up
    assert _run_scenario(worker_raises=False, foreground_raises=True).worker_completed

    # foreground completes normally -> worker cancelled and cleaned up
    assert _run_scenario(worker_raises=False, foreground_raises=False).worker_completed

    # error in the worker -> propagates and fails the sample
    log = _run_scenario(worker_raises=True, foreground_raises=False).log
    assert log.status == "error"
    assert log.error
    assert WORKER_ERROR in log.error.traceback
