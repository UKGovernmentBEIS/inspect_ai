from typing import Callable

from ._chain import Chain
from ._solver import Generate, Solver
from ._task_state import TaskState
from ._transcript import solver_transcript


def loop(
    *,
    solver: Solver,
    condition: Callable[[TaskState], bool] | None = None,
    max_iterations: int = 10,
) -> Solver:
    """Repeatedly applies a solver until a condition is satisfied.

    The solver will run for a maximum number of iterations or until either the condition
    is met or the state is marked as completed.

    Args:
        solver: The solver to be applied repeatedly.
        condition: Optional callable that checks the state. If it returns True, the loop terminates early.
        max_iterations: The maximum number of iterations to execute.

    Returns:
        A solver that implements the looping behavior.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # Helper to decide if we should exit early
        def should_exit(state: TaskState) -> bool:
            return (condition is not None and condition(state)) or state.completed

        iteration = 0
        while iteration < max_iterations:
            if should_exit(state):
                break

            # Execute the provided solver, recording a transcript event
            if not isinstance(solver, Chain):
                with solver_transcript(solver, state) as st:
                    state = await solver(state, generate)
                    st.complete(state)
            else:
                state = await solver(state, generate)

            iteration += 1

            if should_exit(state):
                break

        return state

    return solve
