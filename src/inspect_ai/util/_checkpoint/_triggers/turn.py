"""Concrete trigger for :class:`TurnInterval` specs."""

from __future__ import annotations

from .types import TriggerFire


class _TurnIntervalTrigger:
    """Fire every ``every`` turns.

    The very first ``tick()`` is informational (marks the boundary
    before turn 1) and does not count toward the threshold; subsequent
    ticks each count as one completed turn.
    """

    def __init__(self, every: int) -> None:
        self._every = every
        self._ticks = 0
        self._turns_since_fire = 0

    def tick(self) -> TriggerFire | None:
        self._ticks += 1
        if self._ticks > 1:
            self._turns_since_fire += 1
        if self._turns_since_fire >= self._every:
            self._turns_since_fire = 0
            return TriggerFire("turn", {"every": self._every})
        return None
