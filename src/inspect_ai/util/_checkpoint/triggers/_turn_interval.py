"""Fire every N agent turns."""

from __future__ import annotations

from ._base import CheckpointTrigger, CheckpointTriggerKind


class TurnInterval(CheckpointTrigger):
    """Fire after every ``every`` agent turns of work.

    The very first ``tick()`` call marks the boundary *before* turn 1
    has run — agents place ``tick()`` at the top of their loop, so the
    opening tick stands between "no turn yet" and "turn 1." That
    boundary is informational and doesn't count toward the threshold;
    otherwise ``every=1`` would fire an empty checkpoint on the
    opening tick.
    """

    def __init__(self, every: int) -> None:
        self.every = every
        self._ticks = 0
        self._turns_since_fire = 0

    def tick(self) -> CheckpointTriggerKind | None:
        self._ticks += 1
        if self._ticks > 1:
            self._turns_since_fire += 1
        if self._turns_since_fire >= self.every:
            self._turns_since_fire = 0
            return "turn"
        return None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TurnInterval) and other.every == self.every

    def __hash__(self) -> int:
        return hash((type(self), self.every))

    def __repr__(self) -> str:
        return f"TurnInterval(every={self.every})"
