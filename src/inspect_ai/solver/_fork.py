import asyncio
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, cast

from typing_extensions import overload

from inspect_ai._util.registry import registry_log_name, registry_params
from inspect_ai.util._subtask import subtask

from ._chain import Chain
from ._solver import Generate, Solver
from ._task_state import TaskState


@overload
async def fork(state: TaskState, solvers: Solver) -> TaskState: ...


@overload
async def fork(state: TaskState, solvers: list[Solver]) -> list[TaskState]: ...


async def fork(
    state: TaskState, solvers: Solver | list[Solver]
) -> TaskState | list[TaskState]:
    """Fork the TaskState and evaluate it against multiple solvers in parallel.

    Run several solvers against independent copies of a TaskState. Each
    Solver gets its own copy of the TaskState and is run (in parallel)
    in an independent Subtask (meaning that is also has its own independent
    Store that doesn't affect the Store of other subtasks or the parent).

    Args:
      state (TaskState): Beginning TaskState
      solvers (Solver | list[Solver]): Solvers to apply on the TaskState.
        Each Solver will get a standalone copy of the TaskState.

    Returns:
      Single TaskState or list of TaskState (depending on the input)
      with the results of applying the solver(s) to a forked copy
      of the TaskState.
    """
    if isinstance(solvers, Solver):
        return await solver_subtask(state, solvers)
    else:
        subtasks = [solver_subtask(state, solver) for solver in solvers]
        return await asyncio.gather(*subtasks)


async def solver_subtask(state: TaskState, solver: Solver) -> TaskState:
    # get the generate function for the current task
    generate = _generate.get(None)
    if generate is None:
        raise RuntimeError("Called fork() outside of a running task.")

    # deepcopy the state
    state = deepcopy(state)

    # create a subtask so we get an independent store and transcript
    from ._transcript import solver_transcript

    # derive name and input
    if isinstance(solver, Chain):
        name = "chain"
        input: dict[str, Any] = {}
    else:
        name = registry_log_name(solver)
        input = registry_params(solver)

    @subtask(name=name, store=state.store, type="fork", input=input)  # type: ignore
    async def solve() -> TaskState:
        if not isinstance(solver, Chain):
            with solver_transcript(solver, state) as st:
                new_state = await solver(state, generate)
                st.complete(new_state)
            return new_state
        else:
            return await solver(state, generate)

    # call it and return TaskState
    return cast(TaskState, await solve())


def set_task_generate(generate: Generate) -> None:
    _generate.set(generate)


_generate: ContextVar[Generate] = ContextVar("_generate")
