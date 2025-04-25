from typing import Sequence, cast, overload

from typing_extensions import override

from inspect_ai.agent._agent import Agent, is_agent
from inspect_ai.agent._as_solver import as_solver

from ._solver import Generate, Solver, solver
from ._task_state import TaskState


@solver
def chain(
    *solvers: Solver | Agent | list[Solver] | list[Solver | Agent],
) -> Solver:
    """Compose a solver from multiple other solvers and/or agents.

    Solvers are executed in turn, and a solver step event
    is added to the transcript for each. If a solver returns
    a state with `completed=True`, the chain is terminated
    early.

    Args:
      *solvers: One or more solvers or agents to chain together.

    Returns:
      Solver that executes the passed solvers and agents as a chain.
    """
    # flatten lists and chains
    all_solvers: list[Solver] = []
    for s in solvers:
        all_solvers.extend(unroll(s))

    return Chain(all_solvers)


def unroll(
    solver: Solver | Agent | list[Solver] | list[Solver | Agent],
) -> list[Solver]:
    if isinstance(solver, list):
        unrolled: list[Solver] = []
        for s in solver:
            unrolled.extend(unroll(s))
        return unrolled
    elif is_agent(solver):
        return [as_solver(solver)]
    elif isinstance(solver, Chain):
        return unroll(solver._solvers)
    else:
        return [cast(Solver, solver)]


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

        for slv in self._solvers:
            async with solver_transcript(slv, state) as st:
                state = await slv(state, generate)
                st.complete(state)
            if state.completed:
                break

        # return state
        return state
