from ._solver import Generate, Solver
from ._task_state import TaskState


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
    return Chain(*solvers)


class Chain(Solver):
    """Solver composed from multiple other solvers.

    Args:
      solvers (*Solver): One or more solvers to chain together.
    """

    def __init__(self, *solvers: Solver) -> None:
        self.solvers = list(solvers)

    async def __call__(
        self,
        state: TaskState,
        generate: Generate,
    ) -> TaskState:
        for solver in self.solvers:
            state = await solver(state, generate)
            if state.completed:
                break

        # return state
        return state
