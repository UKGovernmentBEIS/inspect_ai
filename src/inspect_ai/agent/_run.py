from copy import copy
from typing import Any, overload

from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.util._limit import Limit, LimitExceededError, apply_limits
from inspect_ai.util._span import span

from ._agent import Agent, AgentState


@overload
async def run(
    agent: Agent,
    input: str | list[ChatMessage] | AgentState,
    limits: list[Limit] = [],
    *,
    name: str | None = None,
    **agent_kwargs: Any,
) -> tuple[AgentState, LimitExceededError | None]: ...


@overload
async def run(
    agent: Agent,
    input: str | list[ChatMessage] | AgentState,
    *,
    name: str | None = None,
    **agent_kwargs: Any,
) -> AgentState: ...


async def run(
    agent: Agent,
    input: str | list[ChatMessage] | AgentState,
    limits: list[Limit] = [],
    *,
    name: str | None = None,
    **agent_kwargs: Any,
) -> AgentState | tuple[AgentState, LimitExceededError | None]:
    """Run an agent.

    The input messages(s) will be copied prior to running so are
    not modified in place.

    Args:
        agent: Agent to run.
        input: Agent input (string, list of messages, or an `AgentState`).
        limits: List of limits to apply to the agent. Should one of these limits be
            exceeded, the `LimitExceededError` is caught and returned.
        name: Optional display name for the transcript entry. If not provided, the
            agent's name as defined in the registry will be used.
        **agent_kwargs: Additional arguments to pass to agent.

    Returns:
        AgentState: Messages and generated output. This is all that is returned if no
            limits are supplied.
        LimitExceededError | None: If a non-empty limits list is supplied, a tuple is
            returned. If a limit was exceeded, the second value in the tuple is the
            exception instance. If no limit was exceeded, the second element is None.
    """
    # copy input so we don't mutate it in place
    input = copy(input)

    # resolve str
    if isinstance(input, str):
        input_messages: list[ChatMessage] = [
            ChatMessageUser(content=input, source="input")
        ]
    elif isinstance(input, list):
        input_messages = [
            message.model_copy(update=dict(source="input")) for message in input
        ]
    else:
        input_messages = [
            message.model_copy(update=dict(source="input"))
            for message in input.messages
        ]

    # create state
    state = AgentState(messages=input_messages)

    # run the agent with limits, catching errors which are a direct result of our limits
    with apply_limits(limits, catch_errors=True) as limit_scope:
        # run the agent
        agent_name = name or registry_unqualified_name(agent)
        async with span(name=agent_name, type="agent"):
            state = await agent(state, **agent_kwargs)
            if limits:
                return state, None
            else:
                return state

    # execution reaches this point iff one of "our" limits was exceeded
    return state, limit_scope.limit_error
