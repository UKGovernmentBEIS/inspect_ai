from copy import copy
from typing import Any

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser

from ._agent import Agent, AgentState


async def run(
    agent: Agent, input: str | list[ChatMessage] | AgentState, **agent_kwargs: Any
) -> AgentState:
    """Run an agent.

    The input messages(s) will be copied prior to running so are
    not modified in place.

    Args:
        agent: Agent to run.
        input: Agent input (string, list of messages, or an `AgentState`).
        **agent_kwargs: Additional arguments to pass to agent.

    Returns:
        AgentState: Messages and generated output.
    """
    # copy input so we don't mutate it in place
    input = copy(input)

    # resolve str
    if isinstance(input, str):
        input = [ChatMessageUser(content=input)]

    # create state
    state = AgentState(messages=input) if isinstance(input, list) else input

    # run the agent
    return await agent(state, **agent_kwargs)
