from typing import Any, Sequence, cast, overload

from typing_extensions import TypeGuard, override

from inspect_ai.agent._agent import Agent, is_agent
from inspect_ai.agent._as_solver import as_solver

from ._solver import Generate, Solver, solver
from ._task_state import TaskState, set_sample_state


@solver
def chain(
    *solvers: Solver | Agent | Sequence[Solver | Agent],
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
    # flatten sequences and chains
    all_solvers: list[Solver] = []
    for s in solvers:
        all_solvers.extend(unroll(s))

    return Chain(all_solvers)


def unroll(
    solver: Solver | Agent | Sequence[Solver | Agent],
) -> list[Solver]:
    if is_agent(solver):
        return [as_solver(solver)]
    elif isinstance(solver, Chain):
        return unroll(solver._solvers)
    elif is_solver_sequence(solver):
        unrolled: list[Solver] = []
        for s in solver:
            unrolled.extend(unroll(s))
        return unrolled
    else:
        return [cast(Solver, solver)]


def is_solver_sequence(value: object) -> TypeGuard[Sequence[Any]]:
    """Whether `value` is a sequence of solvers rather than a single solver.

    Callable values (individual solvers, agents, and `Chain`) are not treated
    as sequences, even when they implement `Sequence`.

    Raises:
      TypeError: If `value` is a `str`, `bytes`, or `bytearray`, which are
        sequences but never a valid collection of solvers.
    """
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(
            "Expected a solver, an agent, or a sequence of solvers, "
            f"but got {type(value).__name__} {value!r}."
        )
    return isinstance(value, Sequence) and not callable(value)


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
            prev_state = state
            async with solver_transcript(slv, state) as st:
                state = await slv(state, generate)
                st.complete(state)
            set_sample_state(state, replacing=prev_state)
            if state.completed:
                break

        # return state
        return state
