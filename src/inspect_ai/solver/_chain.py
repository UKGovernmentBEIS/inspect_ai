from ._solver import Generate, Solver
from ._task_state import TaskState
from ._transcript import solver_transcript


def chain(*solvers: Solver) -> Solver:
    """Compose a solver from multiple other solvers.

    Solvers are executed in turn, and a sovler step event
    is added to the transcript for each. If a solver returns
    a state with `completed=True`, the chain is terminated
    early.

    Args:
      solvers (*Solver): One or more solvers to chain together.

    Returns:
      Solver that executes the passed solvers as a chain.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for solver in solvers:
            # run solver with transcript and StepEvent
            with solver_transcript(solver, state) as st:
                state = await solver(state, generate)
                st.complete(state)

            # check for completed
            if state.completed:
                break

        # return state
        return state

    return solve
