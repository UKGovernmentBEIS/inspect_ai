"""Sample checkpoints dir contents: ``sample.json`` + ``ckpt-*.json`` sidecars.

Each ``(sample, epoch[, retry])`` attempt gets its own sample
checkpoints dir under the eval checkpoints dir. The dir holds:

- ``sample.json`` — per-sample state (currently the restic password).
- ``ckpt-NNNNN.json`` — one plaintext sidecar per fired checkpoint;
  the index into the host + sandbox restic repos.
- ``host/`` and ``sandboxes/<name>/`` — restic repos.

See ``design/plans/checkpointing-working.md`` §1 and
``design/plans/checkpointing-hydration.md``.

The optional ``_<retry>`` suffix on the dir name is omitted until
``ActiveSample`` exposes the attempt index — see the TODO at the
``Checkpointer.__aenter__`` identity capture.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import anyio

from inspect_ai._util.file import file, filesystem

from .layout import (
    CheckpointSample,
    CheckpointSidecar,
    CheckpointTriggerKind,
    SnapshotInfo,
)


def _sample_checkpoints_dir(eval_dir: str, sample_id: int | str, epoch: int) -> str:
    return f"{eval_dir}/{sample_id}__{epoch}"


def sample_checkpoints_dir(eval_dir: str, sample_id: int | str, epoch: int) -> str:
    """Return the per-sample checkpoints dir path (no FS side effects)."""
    return _sample_checkpoints_dir(eval_dir, sample_id, epoch)


async def has_sample_checkpoint(
    eval_dir: str, sample_id: int | str, epoch: int
) -> bool:
    """Return True if any ``ckpt-*.json`` sidecar exists for this sample attempt."""
    return await anyio.to_thread.run_sync(
        _has_sample_checkpoint_blocking, eval_dir, sample_id, epoch
    )


def _has_sample_checkpoint_blocking(
    eval_dir: str, sample_id: int | str, epoch: int
) -> bool:
    sample_dir = _sample_checkpoints_dir(eval_dir, sample_id, epoch)
    fs = filesystem(sample_dir)
    if not fs.exists(sample_dir):
        return False
    for entry in fs.ls(sample_dir):
        name = entry.name.rsplit("/", 1)[-1]
        if name.startswith("ckpt-") and name.endswith(".json"):
            return True
    return False


async def ensure_sample_checkpoints_dir(
    eval_dir: str, sample_id: int | str, epoch: int
) -> str:
    """Create (idempotent) and return the sample checkpoints dir path.

    Also ensures the eval checkpoints dir exists; that's an
    implementation detail callers shouldn't have to repeat.
    """
    return await anyio.to_thread.run_sync(
        _ensure_sample_checkpoints_dir_blocking, eval_dir, sample_id, epoch
    )


def _ensure_sample_checkpoints_dir_blocking(
    eval_dir: str, sample_id: int | str, epoch: int
) -> str:
    sample_dir = _sample_checkpoints_dir(eval_dir, sample_id, epoch)
    fs = filesystem(sample_dir)
    fs.mkdir(eval_dir, exist_ok=True)
    fs.mkdir(sample_dir, exist_ok=True)
    return sample_dir


async def ensure_sample_json(sample_dir: str) -> CheckpointSample:
    """Ensure ``<sample_dir>/sample.json`` exists; return its contents.

    Mints a fresh restic password and writes the file on first call.
    Subsequent calls read and return the existing file. Idempotent
    across concurrent samples (different sample dirs) — there is no
    cross-sample race.
    """
    return await anyio.to_thread.run_sync(_ensure_sample_json_blocking, sample_dir)


def _ensure_sample_json_blocking(sample_dir: str) -> CheckpointSample:
    sample_json_path = f"{sample_dir}/sample.json"
    fs = filesystem(sample_json_path)
    if fs.exists(sample_json_path):
        with file(sample_json_path, "r") as f:
            return CheckpointSample.model_validate_json(f.read())
    sample = CheckpointSample(restic_password=secrets.token_urlsafe(32))
    with file(sample_json_path, "w") as f:
        f.write(sample.model_dump_json(indent=2))
    return sample


async def _read_sample_json(sample_dir: str) -> CheckpointSample:
    """Read ``<sample_dir>/sample.json``. Caller must have ensured it exists."""
    return await anyio.to_thread.run_sync(_read_sample_json_blocking, sample_dir)


def _read_sample_json_blocking(sample_dir: str) -> CheckpointSample:
    with file(f"{sample_dir}/sample.json", "r") as f:
        return CheckpointSample.model_validate_json(f.read())


async def write_sidecar(
    *,
    sample_checkpoints_dir: str,
    checkpoint_id: int,
    trigger: CheckpointTriggerKind,
    turn: int,
    host: SnapshotInfo,
    sandboxes: dict[str, SnapshotInfo],
    duration_ms: int,
) -> str:
    """Write ``ckpt-NNNNN.json`` for this checkpoint. Returns the path."""
    return await anyio.to_thread.run_sync(
        _write_sidecar_blocking,
        sample_checkpoints_dir,
        checkpoint_id,
        trigger,
        turn,
        host,
        sandboxes,
        duration_ms,
    )


def _write_sidecar_blocking(
    sample_checkpoints_dir: str,
    checkpoint_id: int,
    trigger: CheckpointTriggerKind,
    turn: int,
    host: SnapshotInfo,
    sandboxes: dict[str, SnapshotInfo],
    duration_ms: int,
) -> str:
    sidecar = CheckpointSidecar(
        checkpoint_id=checkpoint_id,
        trigger=trigger,
        turn=turn,
        created_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
        size_bytes=host.size_bytes + sum(s.size_bytes for s in sandboxes.values()),
        host=host,
        sandboxes=sandboxes,
    )

    sidecar_path = f"{sample_checkpoints_dir}/ckpt-{checkpoint_id:05d}.json"
    # Non-atomic on purpose. Per §4d, the commit point is "sidecar that
    # parses": resume globs `ckpt-*.json`, parse-and-skips torn / missing
    # entries, and falls back to the prior parseable sidecar. A
    # mid-write crash costs at most one checkpoint's progress — same as
    # crashing before the sidecar starts.
    with file(sidecar_path, "w") as f:
        f.write(sidecar.model_dump_json(indent=2))
    return sidecar_path
