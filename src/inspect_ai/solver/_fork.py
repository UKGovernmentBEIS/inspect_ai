import asyncio
from contextvars import ContextVar
from copy import deepcopy
from typing import cast

from inspect_ai._util.registry import registry_log_name
from inspect_ai.util._subtask import subtask

from ._solver import Generate, Solver
from ._task_state import TaskState


async def fork(state: TaskState, solvers: list[Solver]) -> list[TaskState]:
    """Fork the TaskState and evaluate it against multiple solvers in parallel.

    Run several solvers against independent copies of a TaskState. Each
    Solver gets its own copy of the TaskState and is run (in parallel)
    in an independent Subtask (meaning that is also has its own independent
    Store that doesn't affect the Store of other subtasks or the parent).

    Args:
      state (TaskState): Beginning TaskState
      solvers (list[Solver]): Solvers to apply on the TaskState.
        Each Solver will get a standalone copy of the TaskState.

    Returns:
      List of TaskState with the results of applying each
      of the pass Solvers to a forked copy of the TaskState.
    """
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
    @subtask(name=registry_log_name(solver), store=state.store)
    async def solve() -> TaskState:
        return await solver(state, generate)

    # call it and return TaskState
    return cast(TaskState, await solve())


def set_task_generate(generate: Generate) -> None:
    _generate.set(generate)


_generate: ContextVar[Generate] = ContextVar("_generate")
