from functools import wraps
from typing import Any, Callable, ParamSpec, Protocol, cast, overload, runtime_checkable

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
)
from inspect_ai.model._model_output import ModelOutput

# distinguish the speaker in coversation history


@runtime_checkable
class Agent(Protocol):
    async def __call__(
        self,
        messages: list[ChatMessage],
        *args: Any,
        **kwargs: Any,
    ) -> tuple[list[ChatMessage], ModelOutput | None]:
        """Agents perform tasks and participate in conversations.

        Agents are similar to tools however they are participants
        in conversation history and can optionally append messages
        and model output to the current conversation.

        You can give the model a tool that enables handoff to
        your agent using the `handoff()` function.

        You can create a simple tool (that receives a string as
        input) from an agent using `agent_as_tool()` and create
        a solver from an agent using `agent_as_solver()`.

        Args:
            messages: Previous conversation history
            *args: Arguments for the agent.
            **kwargs: Keyword arguments for the agent.

        Returns:
            Tuple of `list[ChatMessage], ModelOutput | None` (returns
            None if no generates were done by the solver)
        """
        ...


P = ParamSpec("P")


@overload
def agent(func: Callable[P, Agent]) -> Callable[P, Agent]: ...


@overload
def agent() -> Callable[[Callable[P, Agent]], Callable[P, Agent]]: ...


@overload
def agent(
    *,
    name: str | None = None,
) -> Callable[[Callable[P, Agent]], Callable[P, Agent]]: ...


def agent(
    func: Callable[P, Agent] | None = None,
    *,
    name: str | None = None,
) -> Callable[P, Agent] | Callable[[Callable[P, Agent]], Callable[P, Agent]]:
    r"""Decorator for registering agents.

    Args:
        func: Agent function
        name: Optional name for agent. If the decorator has no name
            argument then the name of the agent creation function
            will be used as the name of the agent.

    Returns:
        Agent with registry attributes.
    """

    def create_agent_wrapper(agent_type: Callable[P, Agent]) -> Callable[P, Agent]:
        # determine the name (explicit or implicit from object)
        agent_name = registry_name(
            agent_type, name if name else getattr(agent_type, "__name__")
        )

        # wrap instantiations of scorer so they carry registry info and metrics
        @wraps(agent_type)
        def agent_wrapper(*args: P.args, **kwargs: P.kwargs) -> Agent:
            agent = agent_type(*args, **kwargs)
            registry_tag(
                agent_type,
                agent,
                RegistryInfo(
                    type="agent",
                    name=agent_name,
                ),
                *args,
                **kwargs,
            )
            return agent

        # register
        return agent_register(cast(Callable[P, Agent], agent_wrapper), agent_name)

    if func is not None:
        return create_agent_wrapper(func)
    else:
        return create_agent_wrapper


def agent_register(agent: Callable[P, Agent], name: str) -> Callable[P, Agent]:
    r"""Register a function or class as an agent.

    Args:
        agent: Agent function or a class derived from Agent.
        name (str): Name of agent (Optional, defaults to object name)

    Returns:
        Agent with registry attributes.
    """
    registry_add(
        agent,
        RegistryInfo(type="agent", name=name),
    )
    return agent
