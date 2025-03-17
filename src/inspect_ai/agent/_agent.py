from copy import copy
from functools import wraps
from typing import (
    Any,
    Callable,
    ParamSpec,
    Protocol,
    Type,
    cast,
    overload,
    runtime_checkable,
)

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
from inspect_ai.util._store import store
from inspect_ai.util._store_model import SMT


class AgentState:
    """Agent state."""

    def __init__(self, *, messages: list[ChatMessage], output: ModelOutput) -> None:
        self._messages = copy(messages)
        self._output = output

    @property
    def messages(self) -> list[ChatMessage]:
        """Conversation history."""
        return self._messages

    @messages.setter
    def messages(self, messages: list[ChatMessage]) -> None:
        """Set the conversation history."""
        self._messages = copy(messages)

    @property
    def output(self) -> ModelOutput:
        """Model output."""
        return self._output

    @output.setter
    def output(self, output: ModelOutput) -> None:
        """Set the model output."""
        self._output = output

    def store_as(self, model_cls: Type[SMT], instance: str | None = None) -> SMT:
        """Pydantic model interface to the store.

        Args:
            model_cls: Pydantic model type (must derive from StoreModel)
            instance: Optional instances name for store (enables multiple instances
              of a given StoreModel type within a single task/subtask)

        Returns:
            StoreModel: model_cls bound to store data.
        """
        return model_cls(store=store(), instance=instance)


@runtime_checkable
class Agent(Protocol):
    async def __call__(
        self,
        state: AgentState,
        *args: Any,
        **kwargs: Any,
    ) -> AgentState:
        """Agents perform tasks and participate in conversations.

        Agents are similar to tools however they are participants
        in conversation history and can optionally append messages
        and model output to the current conversation state.

        You can give the model a tool that enables handoff to
        your agent using the `handoff()` function.

        You can create a simple tool (that receives a string as
        input) from an agent using `as_tool()`.

        Args:
            state: Agent state (conversation history and last model output)
            *args: Arguments for the agent.
            **kwargs: Keyword arguments for the agent.

        Returns:
            AgentState: Updated agent state.
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
