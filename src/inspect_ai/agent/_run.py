from typing import Any

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser

from ._agent import Agent, AgentState


async def run(
    agent: Agent, input: str | list[ChatMessage] | AgentState, **agent_kwargs: Any
) -> AgentState:
    """Run an agent.

    Args:
        agent: Agent to run.
        input: Agent input (string, list of messages, or an `AgentState`).
        **agent_kwargs: Additional arguments to pass to agent.

    Returns:
        AgentState: Messages and generated output.
    """
    input = [ChatMessageUser(content=input)] if isinstance(input, str) else input
    state = AgentState(messages=input) if isinstance(input, list) else input
    return await agent(state, **agent_kwargs)
