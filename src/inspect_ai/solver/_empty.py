from ._solver import Generate, Solver, solver
from ._task_state import TaskState


@solver
def empty_attempt() -> Solver:
    """Leave the state unchanged, so the task's scorers score an empty attempt.

    Pass it as the solver of an eval (`--solver inspect_ai/empty_attempt`) to
    learn what the task's scorers give a sample nobody attempted. The log of
    that eval is what `zero_samples()` copies verdicts from.

    `Task.setup` still runs: it is prepended to any solver override.

    Returns:
      A solver that does nothing.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve
