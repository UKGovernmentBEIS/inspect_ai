from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any

from inspect_ai.model._chat_message import ChatMessage

from ._context import active_sentinel
from ._conversation import current_conversation

if TYPE_CHECKING:
    from inspect_ai.agent._agent import Agent, AgentState


@dataclass
class _Running:
    conversation: str
    # None while a bridge request is handled
    state: "AgentState | None"
    # cleared when the registering call exits: tasks it started hold copies of
    # the context, and must not read or keep its state after it
    active: bool = True

    def end(self) -> None:
        self.active = False
        self.state = None


_running: ContextVar[_Running | None] = ContextVar("sentinel_agent_state", default=None)


def _registered(conversation: str) -> _Running | None:
    current = _running.get()
    if current is None or not current.active or current.conversation != conversation:
        return None
    return current


# set on the wrapper running() returns, to itself: functools.wraps copies it to
# a new function, which must not pass for the wrapper
_RUNNING = "_inspect_sentinel_running"


def running(agent: "Agent") -> "Agent":
    """Wrap an `@agent` agent so the stages of its conversation can read its state.

    The outermost agent running in a conversation registers the `AgentState` object it was called with, until it returns, raises or is cancelled; agents it calls do not change the registration, whatever state they return. A task that outlives the registering call reads no state and can register its own. An agent already wrapped is returned as it is, so a factory that returns a decorated agent (`return react(...)`) adds no frame.
    """
    from inspect_ai.agent._agent import AgentState

    wrapper: object = getattr(agent, _RUNNING, None)
    if wrapper is agent:
        return agent

    @wraps(agent)
    async def run(*args: Any, **kwargs: Any) -> AgentState:
        state = args[0] if args else kwargs.get("state")
        if active_sentinel() is None or not isinstance(state, AgentState):
            return await agent(*args, **kwargs)
        here = current_conversation()
        if _registered(here) is not None:
            return await agent(*args, **kwargs)
        registration = _Running(here, state)
        token = _running.set(registration)
        try:
            return await agent(*args, **kwargs)
        finally:
            registration.end()
            _running.reset(token)

    setattr(run, _RUNNING, run)
    return run


@contextmanager
def bridge_request() -> Iterator[None]:
    """Hide the running agent's state from the stages of one bridge request.

    The request's generates (the bridge's own, and any its filters make) belong to the bridged scaffold, whose state the bridge rebuilds from its requests, so the enclosing agent's list is not theirs. An agent called during the request in the same conversation does not register either. A separate marker from `bridge_model_generate()`, which covers only the bridge's own generation and is what ACP's event mapping relies on.
    """
    if active_sentinel() is None:
        yield
        return
    request = _Running(current_conversation(), None)
    token = _running.set(request)
    try:
        yield
    finally:
        request.end()
        _running.reset(token)


def agent_messages(conversation: str) -> list[ChatMessage] | None:
    """A stage's `agent_messages`: the `messages` of the `AgentState` object the outermost `@agent` agent running in the conversation was called with, read when the stage runs.

    The list is the agent's own, by reference, not a copy. A scaffold that mutates its state shows it at every stage; react keeps its own object when its `model=` agent returns a new one. A scaffold that continues with another `AgentState` object (one a callee returned, or one it built) shows the object it was called with, never the other one. Messages a scaffold keeps out of its list (a policy's hidden instructions) stay out only when that scaffold is the outermost `@agent` agent in its conversation: when an undecorated scaffold calls an `@agent` policy, the policy registers the state it is given. `None` when no `@agent` agent is running in the conversation (a solver calling `generate()`, or an undecorated agent loop that calls no `@agent` agent) and during a bridge request (see `bridge_request()`). A replay has no agent running, so it is `None` there too.
    """
    current = _registered(conversation)
    if current is None or current.state is None:
        return None
    return current.state.messages
