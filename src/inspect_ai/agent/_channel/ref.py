"""Producer-side handle to an :class:`AgentChannel`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .items import Cancel, ChannelItem

if TYPE_CHECKING:
    from .channel import AgentChannel


class AgentRef:
    """Producer-side handle wrapping an :class:`AgentChannel`.

    Producers (the ACP transport today; future subagent supervisors)
    hold an ``AgentRef`` to address an agent's channel. The handle
    exposes only the producer surface — :meth:`post` and
    :meth:`interrupt` — so producers can't accidentally consume items
    intended for the agent loop.

    Refs are cheap; create one per producer attachment.
    """

    __slots__ = ("_channel",)

    def __init__(self, channel: "AgentChannel") -> None:
        self._channel = channel

    def post(self, item: ChannelItem) -> None:
        """Enqueue ``item`` for delivery at the consumer's next drain boundary."""
        self._channel._post(item)

    def interrupt(self, item: Cancel) -> None:
        """Cancel the consumer's bound scope (if any) and enqueue ``item``.

        With no scope bound, degrades to :meth:`post`. "Interrupt" means
        *preempt if a region is running, otherwise just deliver* — producers
        don't need to special-case the no-scope window.
        """
        self._channel._interrupt(item)
