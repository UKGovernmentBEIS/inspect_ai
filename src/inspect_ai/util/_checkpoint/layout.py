"""Pydantic models for the on-disk checkpoint layout.

Defines the shape of the per-sample ``sample.json`` and the per-checkpoint
``ckpt-NNNNN.json`` sidecar files. See ``design/plans/checkpointing-working.md``
§1 for the full layout description. These are pure data types — read/write
helpers live with the Phase 3 write code.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .triggers import CheckpointTriggerKind


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

    trigger: CheckpointTriggerKind
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


class CheckpointSample(BaseModel):
    """Per-sample state file (``<sample_checkpoints_dir>/sample.json``).

    Peer of the sidecars. Written once at first checkpoint setup for a
    sample; never rewritten. Preserved across retries of the same sample
    via the FS copy at resume — so the same password unlocks the FS-copied
    ``host/`` and ``sandboxes/<name>/`` repos in the new sample dir.
    """

    model_config = ConfigDict(extra="allow")

    restic_password: str
    """Password used by every repo (host + each sandbox) under this
    sample. See ``design/plans/checkpointing-hydration.md`` for how it
    reaches sandbox-side restic without being persisted in the sandbox."""
