"""Fire every N of wall-clock time."""

from __future__ import annotations

import time
from datetime import timedelta

from ._base import CheckpointTrigger, CheckpointTriggerKind


class TimeInterval(CheckpointTrigger):
    """Fire after a wall-clock interval.

    Fires when at least ``every`` has elapsed since the last fire (or
    since the session opened, for the first fire).
    """

    def __init__(self, every: timedelta) -> None:
        self.every = every
        self._last_fire_monotonic = time.monotonic()

    def tick(self) -> CheckpointTriggerKind | None:
        elapsed = time.monotonic() - self._last_fire_monotonic
        if elapsed >= self.every.total_seconds():
            self._last_fire_monotonic = time.monotonic()
            return "time"
        return None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TimeInterval) and other.every == self.every

    def __hash__(self) -> int:
        return hash((type(self), self.every))

    def __repr__(self) -> str:
        return f"TimeInterval(every={self.every!r})"
