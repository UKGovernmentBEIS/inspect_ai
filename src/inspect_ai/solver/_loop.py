from typing import Callable

from ._chain import Chain
from ._solver import Generate, Solver
from ._task_state import TaskState
from ._transcript import solver_transcript


def loop(
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
    return Loop(solver=solver, condition=condition, max_iterations=max_iterations)


class Loop(Solver):
    """A solver that repeatedly applies another solver until a condition is met.

    Args:
        solver: The solver to be applied repeatedly.
        condition: Optional callable that checks the state. If it returns True, the loop terminates early.
        max_iterations: The maximum number of iterations to execute.
    """

    def __init__(
        self,
        *,
        solver: Solver,
        condition: Callable[[TaskState], bool] | None = None,
        max_iterations: int = 10,
    ) -> None:
        self._solver = solver
        self._condition = condition
        self._max_iterations = max_iterations

    async def __call__(self, state: TaskState, generate: Generate) -> TaskState:
        # Helper to decide if we should exit early
        def should_exit(state: TaskState) -> bool:
            return (
                self._condition is not None and self._condition(state)
            ) or state.completed

        iteration = 0
        while iteration < self._max_iterations and not should_exit(state):
            if not isinstance(self._solver, Chain):
                with solver_transcript(self._solver, state) as st:
                    state = await self._solver(state, generate)
                    st.complete(state)
            else:
                state = await self._solver(state, generate)

            iteration += 1

        return state
