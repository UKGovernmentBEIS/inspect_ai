"""
Loop solver for inspect_ai.

This solver repeatedly applies a provided solver until a termination condition
is met or until a maximum number of iterations is reached.
"""

from typing import Callable

from ._solver import Generate, Solver, solver
from ._task_state import TaskState
from ._transcript import solver_transcript


@solver
def loop(
    *,
    solver: Solver,
    condition: Callable[[TaskState], bool] | None = None,
    max_iterations: int = 10,
) -> Solver:
    """Repeatedly applies a solver until the provided condition is satisfied.

    The solver will run for a maximum number of iterations or until either the condition
    is met or the state is marked as completed.

    Args:
        solver: The solver to be applied repeatedly.
        condition: Optional callable that checks the state. If it returns True, the loop terminates early.
        max_iterations: The maximum number of iterations to execute.

    Returns:
        A solver that encapsulates the looping behavior.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # Helper to decide if we should exit early.
        def should_exit() -> bool:
            return (condition is not None and condition(state)) or state.completed

        iteration = 0
        while iteration < max_iterations:
            if should_exit():
                break

            # Execute the provided solver, recording a transcript event.
            with solver_transcript(solver, state) as st:
                state = await solver(state, generate)
                st.complete(state)

            iteration += 1

            if should_exit():
                break

        return state

    return solve
