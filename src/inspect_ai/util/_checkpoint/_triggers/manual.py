"""Concrete trigger for :class:`Manual` specs."""

from __future__ import annotations

from .types import CheckpointTriggerKind


class _ManualTrigger:
    """Never fires from ``tick()`` — only explicit ``cp.checkpoint()``."""

    def tick(self) -> CheckpointTriggerKind | None:
        return None
