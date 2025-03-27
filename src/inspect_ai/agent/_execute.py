from copy import copy
from typing import Any, Callable

from inspect_ai.model._chat_message import ChatMessage

from ._agent import Agent, AgentState


async def agent_execute(
    agent: Agent,
    filter: Callable[[list[ChatMessage]], list[ChatMessage]] | None,
    messages: list[ChatMessage],
    *args: Any,
    **kwargs: Any,
) -> AgentState:
    from inspect_ai.solver._limit import SampleLimitExceededError

    # filter input messages and create state
    messages = copy(messages)
    input_messages = filter(messages) if filter is not None else messages
    state = AgentState(messages=input_messages)

    # run the agent
    try:
        return await agent(state, *args, **kwargs)
    except SampleLimitExceededError as ex:
        # append any new messages to ex.state so they aren't lost for error reporting
        if ex.state is not None:
            input_message_ids = [message.id for message in input_messages]
            for message in state.messages:
                if message.id not in input_message_ids:
                    ex.state.messages.append(message)

        # re-raise
        raise
