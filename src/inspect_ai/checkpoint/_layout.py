"""Pydantic models for the on-disk checkpoint layout.

Defines the shape of the eval-level ``manifest.json`` and the per-checkpoint
``ckpt-NNNNN.json`` sidecar files. See ``design/plans/checkpointing-working.md``
§1 for the full layout description. These are pure data types — read/write
helpers live with the Phase 3 write code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CheckpointTrigger = Literal["time", "turn", "manual", "token", "cost", "budget"]
"""All checkpoint trigger kinds, including those scheduled for Phase 5."""


class CheckpointSidecar(BaseModel):
    """Per-checkpoint metadata file (``<attempt>/ckpt-NNNNN.json``).

    Written atomically at each successful checkpoint. The sidecar's existence
    is the commit point — the checkpoint is visible to resume only when this
    file is in place. See §1 and §4d.
    """

    model_config = ConfigDict(extra="allow")

    checkpoint_id: int
    """Ordinal integer (1, 2, 3, …) chosen by inspect at write time."""

    trigger: CheckpointTrigger
    """The policy that fired this checkpoint."""

    turn: int
    """Agent turn index at which this checkpoint was taken."""

    created_at: datetime
    """When the checkpoint was committed."""

    duration_ms: int
    """How long the checkpoint cycle took, in milliseconds."""

    size_bytes: int
    """On-disk size added by this checkpoint."""

    host_snapshot_id: str | None = None
    """Restic snapshot id in the per-attempt host repo. ``None`` while the
    host-repo write path is still being wired up; required once Phase 3
    finishes."""

    sandboxes: dict[str, str] = Field(default_factory=dict)
    """Map from sandbox name to the corresponding restic snapshot id in
    that sandbox's per-attempt repo. Empty when checkpointing is host-only."""


class CheckpointManifest(BaseModel):
    """Eval-level manifest (``<destination>/manifest.json``).

    Written once at checkpoint-directory creation. Carries identity, format
    version, and repo encryption material. See §1 and §4g.
    """

    model_config = ConfigDict(extra="allow")

    eval_id: str
    """Pairs the checkpoint directory with its sibling ``.eval`` log."""

    layout_version: int
    """Currently ``1``. Bumped on incompatible directory-layout changes."""

    engine: Literal["restic"]
    """Snapshot engine. Currently restic only."""

    restic_password: str
    """Auto-generated password used by every repo (host + each sandbox) under
    this eval. See §4g for the password lifecycle and §4h for how it reaches
    sandbox-side restic without being persisted in the sandbox."""
