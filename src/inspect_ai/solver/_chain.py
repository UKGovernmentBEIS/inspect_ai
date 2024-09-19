from ._solver import Generate, Solver
from ._task_state import TaskState


def chain(*solvers: Solver | list[Solver]) -> Solver:
    """Compose a solver from multiple other solvers.

    Solvers are executed in turn, and a sovler step event
    is added to the transcript for each. If a solver returns
    a state with `completed=True`, the chain is terminated
    early.

    Args:
      solvers (*Solver | list[Solver]): One or more solvers
        or lists of solvers to chain together.

    Returns:
      Solver that executes the passed solvers as a chain.
    """
    # flatten lists and chains
    all_solvers: list[Solver] = []
    for solver in solvers:
        if isinstance(solver, list):
            all_solvers.extend(solver)
        elif isinstance(solver, Chain):
            all_solvers.extend(solver.solvers)
        else:
            all_solvers.append(solver)

    return Chain(all_solvers)


class Chain(Solver):
    """Solver composed from multiple other solvers.

    Args:
      solvers (*Solver): One or more solvers to chain together.
    """

    def __init__(self, solvers: list[Solver]) -> None:
        self.solvers = solvers

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
