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
from .sidecar import CheckpointDetails, CheckpointSample, SnapshotDetails
from .working_dir import ensure_sample_working_dir

# `host_context` is intentionally NOT imported here. It imports
# `inspect_ai.event._event.Event`, which is itself the union that
# (since `CheckpointEvent` landed) imports `CheckpointDetails` from
# `.sidecar` below — eager `host_context` here would create a cycle
# at package-init time. Callers import the submodule directly:
# `from inspect_ai.util._checkpoint.layout import host_context`
# still works via Python's submodule-attribute fallback at the time
# of the import statement.

__all__ = [
    "CheckpointSample",
    "CheckpointDetails",
    "SnapshotDetails",
    "ensure_sample_checkpoints_dir",
    "ensure_sample_json",
    "ensure_sample_working_dir",
    "eval_checkpoints_dir",
    "eval_checkpoints_dir_from_config",
    "has_sample_checkpoint",
    "log_basename",
    "sample_checkpoints_dir",
    "scan_latest_committed_id",
    "write_sidecar",
]
