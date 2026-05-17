"""Manual-only trigger — never auto-fires.

The agent fires explicitly via ``cp.checkpoint()`` (which bypasses the
trigger and always writes a sidecar with ``trigger="manual"``).
"""

from __future__ import annotations

from ._base import CheckpointTrigger, CheckpointTriggerKind


class Manual(CheckpointTrigger):
    """No-op trigger: ``tick()`` always returns ``None``."""

    def tick(self) -> CheckpointTriggerKind | None:
        return None
