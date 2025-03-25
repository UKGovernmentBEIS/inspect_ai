from copy import copy

from inspect_ai.model import ChatMessage, ChatMessageUser, ModelName, ModelOutput

from ._fork import task_generate
from ._solver import Solver
from ._task_state import TaskState


async def run(
    solver: Solver, input: str | list[ChatMessage]
) -> tuple[list[ChatMessage], ModelOutput | None]:
    """Run a solver over chat message input.

    Args:
        solver: Solver to run.
        input: Chat message input

    Returns:
        Tuple of `list[ChatMessage], ModelOutput | None` (returns
        [], None if no generates were done by the solver)
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
        messages=copy(messages),
    )

    # run solver
    state = await solver(state, generate)

    # return any messages that don't match our initial prefix
    new_messages: list[ChatMessage] = []
    for index, message in enumerate(state.messages):
        if index >= len(messages) or message.id != messages[index].id:
            new_messages.append(message)

    return new_messages, state.output if len(state.output.choices) > 0 else None
