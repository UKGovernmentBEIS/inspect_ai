"""On-disk layout for inspect checkpointing.

Owns *where* checkpoint state lives on disk and *what shape* each file
takes:

- :mod:`.eval_checkpoints_dir` — eval checkpoints dir path computation
  (``<log-base>.checkpoints/`` durable, alongside the log).
- :mod:`.sample_checkpoints_dir` — sample dir contents:
  ``sample.json`` + ``ckpt-NNNNN.json`` sidecars.
- :mod:`.working_dir` — eval + sample working dir paths (host-local,
  ephemeral, under ``inspect_cache_dir("checkpoints")``).
- :mod:`.host_context` — read/write the 5-file JSON schema *inside* the
  sample working dir (events, events_data, attachments, store,
  agent_state).
- :mod:`.sidecar` — pydantic models for ``sample.json`` and
  ``ckpt-NNNNN.json``.
"""

from . import host_context
from .eval_checkpoints_dir import (
    eval_checkpoints_dir,
    eval_checkpoints_dir_from_config,
    log_basename,
)
from .sample_checkpoints_dir import (
    ensure_sample_checkpoints_dir,
    ensure_sample_json,
    has_sample_checkpoint,
    sample_checkpoints_dir,
    scan_latest_committed_id,
    write_sidecar,
)
from .sidecar import CheckpointSample, CheckpointSidecar, SnapshotInfo
from .working_dir import ensure_sample_working_dir

__all__ = [
    "CheckpointSample",
    "CheckpointSidecar",
    "SnapshotInfo",
    "ensure_sample_checkpoints_dir",
    "ensure_sample_json",
    "ensure_sample_working_dir",
    "eval_checkpoints_dir",
    "eval_checkpoints_dir_from_config",
    "has_sample_checkpoint",
    "host_context",
    "log_basename",
    "sample_checkpoints_dir",
    "scan_latest_committed_id",
    "write_sidecar",
]
