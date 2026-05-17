"""Manual-only trigger — never auto-fires.

The agent fires explicitly via ``cp.checkpoint()`` (which bypasses the
trigger and always writes a sidecar with ``trigger="manual"``).
"""

from __future__ import annotations

from typing import ClassVar

from inspect_ai.util._checkpoint.layout import CheckpointTriggerKind


class Manual:
    """No-op trigger: ``tick()`` always returns ``False``."""

    kind: ClassVar[CheckpointTriggerKind] = "manual"

    def tick(self) -> bool:
        return False
