"""Fire every N of wall-clock time."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import ClassVar

from inspect_ai.util._checkpoint.layout import CheckpointTriggerKind


class TimeInterval:
    """Fire after a wall-clock interval.

    Fires when at least ``every`` has elapsed since the last fire (or
    since the session opened, for the first fire).
    """

    kind: ClassVar[CheckpointTriggerKind] = "time"

    def __init__(self, every: timedelta) -> None:
        self.every = every
        self._last_fire_monotonic = time.monotonic()

    def tick(self) -> bool:
        elapsed = time.monotonic() - self._last_fire_monotonic
        if elapsed >= self.every.total_seconds():
            self._last_fire_monotonic = time.monotonic()
            return True
        return False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TimeInterval) and other.every == self.every

    def __hash__(self) -> int:
        return hash((type(self), self.every))

    def __repr__(self) -> str:
        return f"TimeInterval(every={self.every!r})"
