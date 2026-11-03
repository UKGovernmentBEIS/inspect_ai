"""Turn gate: a private seam for runtimes that run agents.

A runtime (such as a swarm of agents) installs a :class:`TurnGate` with
:func:`turn_gate` around the agents it runs. Every :func:`agent_channel`
opened in that block keeps the gate, nested loops included, and
:meth:`AgentChannel.before_turn` awaits it at each turn boundary. The gate
receives the channel, so the runtime decides which loop it acts on.

A react loop that has an answer and would return it asks
:func:`after_answer` first, so a runtime can keep the loop going to its
next turn boundary. The loops that ask carry a :class:`TurnLoop` mark,
which :func:`turn_loop` reads.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterator, Protocol, Sequence

from inspect_ai._sentinel._agent_state import _RUNNING
from inspect_ai.model._chat_message import ChatMessage

if TYPE_CHECKING:
    from inspect_ai.agent._agent import Agent, AgentState

    from .channel import AgentChannel


class TurnGate(Protocol):
    """Code that runs at the turn boundaries of agent loops."""

    async def before_turn(
        self,
        channel: AgentChannel,
        messages: Sequence[ChatMessage],
        state: AgentState | None,
    ) -> bool:
        """Run at a turn boundary, before the channel drains its queue.

        Args:
            channel: The channel of the loop at the boundary.
            messages: The loop's conversation. The gate changes it in place,
                if at all.
            state: The loop's state, or `None` from a loop that passes none.

        Returns:
            `True` after removing, replacing, reordering or inserting
            messages, or adding a system message anywhere. `False` for an
            unchanged conversation or an append of only non-system messages.
            The loop's compaction handler keeps system messages in a prefix
            saved earlier, so an appended system message counts as a rewrite.
        """
        ...

    async def after_answer(self, channel: AgentChannel, state: AgentState) -> bool:
        """Run when a react loop has an answer and would return it.

        Args:
            channel: The channel of the loop that answered.
            state: The state the loop would return.

        Returns:
            `True` to continue the loop to its next turn boundary instead
            of returning. `False` to return as the loop would without a gate.
        """
        ...

    def closed(self, channel: AgentChannel) -> None:
        """Called synchronously when the block of a channel with this gate exits."""
        ...


_turn_gate: ContextVar[TurnGate | None] = ContextVar("_turn_gate", default=None)


@contextlib.contextmanager
def turn_gate(gate: TurnGate | None) -> Iterator[None]:
    """Set the gate for agent channels opened in the block."""
    token = _turn_gate.set(gate)
    try:
        yield
    finally:
        _turn_gate.reset(token)


def current_turn_gate() -> TurnGate | None:
    """The gate for an agent channel opened now, if any."""
    return _turn_gate.get()


async def after_answer(channel: AgentChannel, state: AgentState) -> bool:
    """Whether a loop that has an answer continues instead of returning.

    `False` for a channel without a gate (the inert channel included), else
    the gate's :meth:`TurnGate.after_answer`.
    """
    if channel._gate is None:
        return False
    return await channel._gate.after_answer(channel, state)


@dataclass(frozen=True)
class TurnLoop:
    """The mark a loop constructor sets on the inner function it returns."""

    loop: Callable[..., Any]
    """The constructor's inner function, the one the mark is set on."""

    background: bool
    """Whether the loop dispatches background work (`deepagent()`'s `background`)."""


_TURN_LOOP = "_inspect_turn_loop"


def mark_turn_loop(loop: Callable[..., Any], background: bool = False) -> None:
    """Mark a loop's inner function, before `@agent` wraps it."""
    setattr(loop, _TURN_LOOP, TurnLoop(loop, background))


def turn_loop(agent: Agent) -> TurnLoop | None:
    """The mark of the loop `agent` runs, if `agent` is that loop.

    `@agent` wraps a loop's inner function with `running()`, whose wrapper
    gets a copy of the mark. The mark counts only on that wrapper itself
    (its running marker points to it) and only when the wrapper's
    `__wrapped__` is the marked function. So it survives retagging (a
    builder that returns the loop, `agent_with()`) and fails for a
    `functools.wraps` copy, or a builder whose own function wraps the loop.
    """
    mark = getattr(agent, _TURN_LOOP, None)
    if not isinstance(mark, TurnLoop):
        return None
    if getattr(agent, _RUNNING, None) is not agent:
        return None
    if getattr(agent, "__wrapped__", None) is not mark.loop:
        return None
    return mark
