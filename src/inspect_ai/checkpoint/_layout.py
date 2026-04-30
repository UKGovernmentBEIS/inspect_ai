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


class SnapshotInfo(BaseModel):
    """Per-backup stats captured in the sidecar.

    One per repo (host repo + one per active sandbox repo). Values come
    from restic's backup summary — see :class:`ResticBackupSummary`.
    """

    model_config = ConfigDict(extra="allow")

    snapshot_id: str
    """Restic snapshot id for this backup."""

    size_bytes: int
    """Bytes this snapshot added to its repo, after compression
    (restic's ``data_added_packed``)."""

    duration_ms: int
    """How long the restic invocation took, in milliseconds."""


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
    """Total on-disk size added by this checkpoint (sum of host + sandboxes)."""

    host: SnapshotInfo
    """Stats for the host repo backup this cycle."""

    sandboxes: dict[str, SnapshotInfo] = Field(default_factory=dict)
    """Per-sandbox stats keyed by sandbox name. Empty when checkpointing is
    host-only."""


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
