"""Turn gate: a private seam for runtimes that run agents.

A runtime (such as a swarm of agents) installs a :class:`TurnGate` with
:func:`turn_gate` around the agents it runs. Every :func:`agent_channel`
opened in that block keeps the gate, nested loops included, and
:meth:`AgentChannel.before_turn` awaits it at each turn boundary. The gate
receives the channel, so the runtime decides which loop it acts on.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import TYPE_CHECKING, Iterator, Protocol, Sequence

from inspect_ai.model._chat_message import ChatMessage

if TYPE_CHECKING:
    from inspect_ai.agent._agent import AgentState

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
