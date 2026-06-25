"""Exceptions raised by the agent channel."""

from __future__ import annotations


class AgentInterrupted(Exception):
    """Raised inside :meth:`AgentChannel.turn_scope` when cancelled by an interrupt.

    Source-agnostic: any producer's interrupt (operator over ACP today, future
    subagent-supervisor kill, etc.) raises the same exception inside the
    consuming agent's turn scope. The consumer catches, drains queued items,
    and decides how to resume.

    Distinct from :class:`asyncio.CancelledError` (which is reserved for
    sample-level hard cancels propagating from the enclosing task group —
    limit exceeded, eval shutdown).
    """
