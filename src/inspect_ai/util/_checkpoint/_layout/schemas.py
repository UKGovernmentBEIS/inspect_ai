"""Pydantic models for the on-disk checkpoint layout.

Defines the shape of the per-sample ``restic/restic-config.json`` and
the per-checkpoint ``ckpt-NNNNN.json`` checkpoint files. These are pure
data types — read/write helpers live with the write code.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .._triggers import CheckpointTriggerKind


class SnapshotDetails(BaseModel):
    """Per-backup stats captured in the checkpoint file.

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

    files: list[str] | None = None
    """Absolute paths of files added or changed in this snapshot (relative
    to its parent; the full file set for the first snapshot), capped at
    ``MAX_LISTED_FILES``."""

    additional_files: int | None = None
    """Count of files beyond ``MAX_LISTED_FILES`` not included in
    ``files``. ``None`` when nothing was truncated."""


class Checkpoint(BaseModel):
    """Per-checkpoint metadata file (``<attempt>/ckpt-NNNNN.json``).

    Written atomically at each successful checkpoint. This file's
    existence is the commit point — the checkpoint is visible to
    resume only when this file is in place. See §1 and §4d.
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

    host: SnapshotDetails
    """Stats for the host repo backup this cycle."""

    sandboxes: dict[str, SnapshotDetails] = Field(default_factory=dict)
    """Per-sandbox stats keyed by sandbox name. Empty when checkpointing is
    host-only."""


class ResticConfig(BaseModel):
    """Per-sample restic config file (``<sample-root>/restic/restic-config.json``).

    Lives alongside the per-sample restic repos under ``restic/``.
    Written once at first checkpoint setup for a sample; never
    rewritten. Preserved across retries of the same sample via the FS
    copy at resume — so the same password unlocks the FS-copied
    ``host/`` and ``sandboxes/<name>/`` repos in the new sample dir.
    """

    model_config = ConfigDict(extra="allow")

    restic_password: str
    """Password used by every repo (host + each sandbox) under this
    sample. Reaches sandbox-side restic via the per-exec environment;
    never persisted in the sandbox."""
