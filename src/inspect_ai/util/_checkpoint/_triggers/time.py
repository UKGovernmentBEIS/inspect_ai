"""Concrete trigger for :class:`TimeInterval` specs."""

from __future__ import annotations

import time
from datetime import timedelta

from .types import TriggerFire


class _TimeIntervalTrigger:
    """Fire when wall-clock elapsed since the last fire ≥ ``every``.

    The clock anchor is set on the first ``tick()`` (not at
    construction), so the first fire is at least ``every`` after the
    session's first turn rather than after engine construction.
    """

    def __init__(self, every: timedelta) -> None:
        self._every_seconds = every.total_seconds()
        self._last_fire_monotonic: float | None = None

    def tick(self) -> TriggerFire | None:
        now = time.monotonic()
        if self._last_fire_monotonic is None:
            self._last_fire_monotonic = now
            return None
        elapsed = now - self._last_fire_monotonic
        if elapsed >= self._every_seconds:
            self._last_fire_monotonic = now
            return TriggerFire(
                "time",
                {
                    "every_seconds": self._every_seconds,
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
        return None
