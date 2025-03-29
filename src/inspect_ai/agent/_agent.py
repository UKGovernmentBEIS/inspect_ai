from copy import copy, deepcopy
from functools import wraps
from typing import (
    Any,
    Callable,
    ParamSpec,
    Protocol,
    TypeGuard,
    cast,
    overload,
    runtime_checkable,
)

from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_add,
    registry_info,
    registry_name,
    registry_tag,
    set_registry_info,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
)
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput


class AgentState:
    """Agent state."""

    def __init__(self, *, messages: list[ChatMessage]) -> None:
        self._messages = messages
        self._output: ModelOutput | None = None

    @property
    def messages(self) -> list[ChatMessage]:
        """Conversation history."""
        return self._messages

    @messages.setter
    def messages(self, messages: list[ChatMessage]) -> None:
        """Set the conversation history."""
        self._messages = messages

    @property
    def output(self) -> ModelOutput:
        """Model output."""
        # if there is no output yet then synthesize it from the last assistant message
        if self._output is None:
            # look for the last assistant message
            for message in reversed(self.messages):
                if isinstance(message, ChatMessageAssistant):
                    self._output = ModelOutput(
                        model=message.model or "",
                        choices=[
                            ChatCompletionChoice(
                                message=message.model_copy(),
                                stop_reason="stop",
                            )
                        ],
                    )

            # no assistant message, so generate an empty model output
            if self._output is None:
                self._output = ModelOutput()

        return self._output

    @output.setter
    def output(self, output: ModelOutput) -> None:
        """Set the model output."""
        self._output = output

    def __copy__(self) -> "AgentState":
        state = AgentState(messages=copy(self.messages))
        state.output = self.output.model_copy()
        return state

    def __deepcopy__(self, memo: dict[int, Any]) -> "AgentState":
        state = AgentState(messages=deepcopy(self.messages, memo))
        state.output = self.output.model_copy(deep=True)
        return state


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
    description: str | None = None,
) -> Callable[[Callable[P, Agent]], Callable[P, Agent]]: ...


def agent(
    func: Callable[P, Agent] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[P, Agent] | Callable[[Callable[P, Agent]], Callable[P, Agent]]:
    r"""Decorator for registering agents.

    Args:
        func: Agent function
        name: Optional name for agent. If the decorator has no name
            argument then the name of the agent creation function
            will be used as the name of the agent.
        description: Description for the agent when used as
            an ordinary tool or handoff tool.

    Returns:
        Agent with registry attributes.
    """

    def create_agent_wrapper(agent_type: Callable[P, Agent]) -> Callable[P, Agent]:
        # determine the name (explicit or implicit from object)
        agent_name = registry_name(
            agent_type, name if name else getattr(agent_type, "__name__")
        )

        # wrap instantiations of agent so they carry registry info and metrics
        @wraps(agent_type)
        def agent_wrapper(*args: P.args, **kwargs: P.kwargs) -> Agent:
            # create agent
            agent = agent_type(*args, **kwargs)

            # this might already have registry info, if so capture that
            # and use it as default
            if is_registry_object(agent):
                info = registry_info(agent)
                registry_name = info.name
                registry_description = info.metadata.get(AGENT_DESCRIPTION, None)
            else:
                registry_name = None
                registry_description = None

            registry_tag(
                agent_type,
                agent,
                RegistryInfo(
                    type="agent",
                    name=registry_name or agent_name,
                    metadata={AGENT_DESCRIPTION: registry_description or description},
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


def agent_with(
    agent: Agent,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Agent:
    """Agent with modifications to name and/or description

    This function modifies the passed agent in place and
    returns it. If you want to create multiple variations
    of a single agent using `agent_with()` you should create
    the underlying agent multiple times.

    Args:
       agent: Agent instance to modify.
       name: Agent name (optional).
       description: Agent description (optional).

    Returns:
       The passed agent with the requested modifications.
    """
    # resolve name and description
    if is_registry_object(agent):
        info = registry_info(agent)
        name = name or info.name
        description = description or info.metadata.get(AGENT_DESCRIPTION, None)

    # if the name is null then raise
    if name is None:
        raise ValueError("You must provide a name to agent_with")

    # now set registry info
    set_registry_info(
        agent,
        RegistryInfo(
            type="agent",
            name=name,
            metadata={AGENT_DESCRIPTION: description}
            if description is not None
            else {},
        ),
    )

    return agent


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


def is_agent(obj: Any) -> TypeGuard[Agent]:
    return is_registry_object(obj, type="agent")


AGENT_DESCRIPTION = "description"
