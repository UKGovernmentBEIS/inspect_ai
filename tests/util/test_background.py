# test that service errors are caught, logged, and re-raised

import anyio

from inspect_ai import Task, eval
from inspect_ai.solver import Solver, solver
from inspect_ai.util import background


def test_background_termination():
    WORKER_ERROR = "Error in worker!"

    worker_completed = False

    async def worker(raise_error: bool):
        try:
            while True:
                await anyio.sleep(0.5)
                if raise_error:
                    raise RuntimeError(WORKER_ERROR)
        finally:
            nonlocal worker_completed
            worker_completed = True

    @solver
    def start_worker(raise_error: bool) -> Solver:
        async def solve(state, generate):
            background(worker, raise_error)
            return state

        return solve

    # does the worker complete with a normal sample exit?
    eval(Task(solver=[start_worker(False), foreground_solver(True)]))
    assert worker_completed

    # does the worker complete with a sample error?
    eval(Task(solver=[start_worker(False), foreground_solver(False)]))
    assert worker_completed

    # does an error in the worker get handled?
    log = eval(Task(solver=[start_worker(True), foreground_solver(False)]))[0]
    assert log.status == "error"
    assert log.error
    assert WORKER_ERROR in log.error.traceback


@solver
def foreground_solver(raise_error: bool) -> Solver:
    async def solver(state, generate):
        await anyio.sleep(0.5)
        if raise_error:
            raise Exception("Error in solver!")
        return state

    return solver
