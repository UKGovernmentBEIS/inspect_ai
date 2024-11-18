from typing import Sequence, overload

from typing_extensions import override

from ._solver import Generate, Solver
from ._task_state import TaskState


def chain(*solvers: Solver | list[Solver]) -> Solver:
    """Compose a solver from multiple other solvers.

    Solvers are executed in turn, and a solver step event
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
        all_solvers.extend(unroll(solver))

    return Chain(all_solvers)


def unroll(solver: Solver | list[Solver]) -> list[Solver]:
    if isinstance(solver, Solver):
        if isinstance(solver, Chain):
            return unroll(solver._solvers)
        else:
            return [solver]
    else:
        unrolled: list[Solver] = []
        for s in solver:
            unrolled.extend(unroll(s))
        return unrolled


class Chain(Sequence[Solver], Solver):
    """Solver composed from multiple other solvers.

    Args:
      solvers (*Solver): One or more solvers to chain together.
    """

    def __init__(self, solvers: list[Solver]) -> None:
        self._solvers = solvers

    @overload
    def __getitem__(self, index: int) -> Solver: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Solver]: ...

    @override
    def __getitem__(self, index: int | slice) -> Solver | Sequence[Solver]:
        return self._solvers[index]

    @override
    def __len__(self) -> int:
        return len(self._solvers)

    async def __call__(
        self,
        state: TaskState,
        generate: Generate,
    ) -> TaskState:
        from ._transcript import solver_transcript

        for solver in self._solvers:
            with solver_transcript(solver, state) as st:
                state = await solver(state, generate)
                st.complete(state)
            if state.completed:
                break

        # return state
        return state
