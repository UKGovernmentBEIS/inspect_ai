from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any

from inspect_ai.log._samples import sample_active
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.util._span import current_agent_span_id

from ._context import active_sentinel

if TYPE_CHECKING:
    from inspect_ai.agent._agent import Agent, AgentState


@dataclass
class _Running:
    conversation: str
    state: "AgentState"


_running: ContextVar[_Running | None] = ContextVar("sentinel_agent_state", default=None)


def current_conversation() -> str:
    agent_span_id = current_agent_span_id()
    if agent_span_id is not None:
        return agent_span_id
    active = sample_active()
    return active.sample_uuid if active is not None else ""


def running(agent: "Agent") -> "Agent":
    """Wrap an `@agent` agent so the stages of its conversation can read its state.

    The outermost agent running in a conversation registers the state it was called with. An agent nested in the same conversation that was called with that state and returns a different one registers the returned state, since the outer loop continues with it (react's `model=` agent can). The registration is restored when the agent returns or raises.
    """
    from inspect_ai.agent._agent import AgentState

    @wraps(agent)
    async def run(*args: Any, **kwargs: Any) -> AgentState:
        state = args[0] if args else kwargs.get("state")
        if active_sentinel() is None or not isinstance(state, AgentState):
            return await agent(*args, **kwargs)
        current = _running.get()
        here = current_conversation()
        if current is None or current.conversation != here:
            token = _running.set(_Running(here, state))
            try:
                return await agent(*args, **kwargs)
            finally:
                _running.reset(token)
        result = await agent(*args, **kwargs)
        if current.state is state and result is not state:
            current.state = result
        return result

    return run


def agent_messages(conversation: str) -> list[ChatMessage] | None:
    """A stage's `agent_messages`: the `messages` of the outermost `@agent` agent running in the conversation, read when the stage runs.

    The list is the agent's own, by reference, not a copy. A scaffold that keeps its conversation in a list outside its `AgentState` shows that state at every stage. `None` when no `@agent` agent is running in the conversation (a solver calling `generate()`, or an undecorated agent loop) and for a bridged agent's generates, whose state the bridge rebuilds from the model requests. A replay has no agent running, so it is `None` there too.
    """
    from inspect_ai.agent._bridge.util import in_bridge_model_generate

    current = _running.get()
    if current is None or current.conversation != conversation:
        return None
    if in_bridge_model_generate():
        return None
    return current.state.messages
