from collections.abc import Iterator
from contextlib import contextmanager
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
    # None while a bridge request is handled
    state: "AgentState | None"


_running: ContextVar[_Running | None] = ContextVar("sentinel_agent_state", default=None)

# how many decorated agents deep the current call is below the registering one
_depth: ContextVar[int] = ContextVar("sentinel_agent_depth", default=0)


def current_conversation() -> str:
    agent_span_id = current_agent_span_id()
    if agent_span_id is not None:
        return agent_span_id
    active = sample_active()
    return active.sample_uuid if active is not None else ""


def running(agent: "Agent") -> "Agent":
    """Wrap an `@agent` agent so the stages of its conversation can read its state.

    The outermost agent running in a conversation registers the state it was called with. Its direct callee among `@agent` agents (depth is counted in decorated frames only), when called with the registered state, registers the different state it returns, since the outer loop continues with it: react's `model=` agent can return one. A deeper agent never does, so the states a micro-protocol's policies return, which it may discard, are not registered while it runs. The registration is restored when the agent returns or raises.
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
            depth_token = _depth.set(0)
            try:
                return await agent(*args, **kwargs)
            finally:
                _depth.reset(depth_token)
                _running.reset(token)
        depth = _depth.get() + 1
        replaces = depth == 1 and current.state is state
        depth_token = _depth.set(depth)
        try:
            result = await agent(*args, **kwargs)
        finally:
            _depth.reset(depth_token)
        if replaces and result is not state:
            current.state = result
        return result

    return run


@contextmanager
def bridge_request() -> Iterator[None]:
    """Hide the running agent's state from the stages of one bridge request.

    The request's generates (the bridge's own, and any its filters make) belong to the bridged scaffold, whose state the bridge rebuilds from its requests, so the enclosing agent's list is not theirs. An agent called during the request in the same conversation does not register either. A separate marker from `bridge_model_generate()`, which covers only the bridge's own generation and is what ACP's event mapping relies on.
    """
    if active_sentinel() is None:
        yield
        return
    token = _running.set(_Running(current_conversation(), None))
    try:
        yield
    finally:
        _running.reset(token)


def agent_messages(conversation: str) -> list[ChatMessage] | None:
    """A stage's `agent_messages`: the `messages` of the outermost `@agent` agent running in the conversation, read when the stage runs.

    The list is the agent's own, by reference, not a copy. A scaffold that keeps its conversation in a list outside its `AgentState` shows that state at every stage. A scaffold that continues with a new `AgentState` (one its callee returned, or one it built) shows the earlier state, unless the callee that returned it is an `@agent` agent that the registering (outermost) agent called directly (see `running()`); under an `@agent` agent that wraps react, react's `model=` agent is not. Messages a scaffold keeps out of its list (a policy's hidden instructions) stay out only when that scaffold is the outermost `@agent` agent in its conversation: when an undecorated scaffold calls an `@agent` policy, the policy registers the state it is given. `None` when no `@agent` agent is running in the conversation (a solver calling `generate()`, or an undecorated agent loop that calls no `@agent` agent) and during a bridge request (see `bridge_request()`). A replay has no agent running, so it is `None` there too.
    """
    current = _running.get()
    if current is None or current.conversation != conversation:
        return None
    return current.state.messages if current.state is not None else None
