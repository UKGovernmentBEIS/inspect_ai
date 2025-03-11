from inspect_ai.model import ChatMessage, ChatMessageUser, ModelName, ModelOutput

from ._fork import task_generate
from ._solver import Solver
from ._task_state import TaskState


async def run(
    solver: Solver, input: str | list[ChatMessage]
) -> tuple[ModelOutput, list[ChatMessage]]:
    """Run a solver over chat message input.

    Args:
        solver: Solver to run.
        input: Chat message input

    Returns:
        Tuple of ModelOutput, list[ChatMessage]
    """
    from inspect_ai.log._samples import sample_active

    # get the generate function for the current task
    generate = task_generate()
    if generate is None:
        raise RuntimeError("Called run() outside of a running task.")

    # get the active sample
    active = sample_active()
    if active is None:
        raise RuntimeError("Called run() outside of a running task")
    assert active.sample.id

    # build messages list
    messages: list[ChatMessage] = (
        [ChatMessageUser(content=input)] if isinstance(input, str) else input
    )

    # build state
    state = TaskState(
        model=ModelName(active.model),
        sample_id=active.sample.id,
        epoch=active.epoch,
        input=input,
        messages=messages,
    )

    # run solver and return output and messages
    state = await solver(state, generate)
    return state.output, state.messages
