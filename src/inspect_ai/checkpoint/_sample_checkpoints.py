"""Sample checkpoints dir and sidecar writes.

Each ``(sample, epoch[, retry])`` attempt gets its own sample
checkpoints dir under the eval checkpoints dir; sidecars
(``ckpt-NNNNN.json``) live inside it as the plaintext index for each
fired checkpoint. See ``design/plans/checkpointing-working.md`` §1.

The optional ``_<retry>`` suffix is omitted until ``ActiveSample``
exposes the attempt index — see the TODO at the
``Checkpointer.__aenter__`` identity capture.
"""

from __future__ import annotations

from datetime import datetime, timezone

import anyio

from inspect_ai._util.file import file, filesystem

from ._eval_checkpoints import _eval_checkpoints_dir, init_eval_checkpoints_dir
from ._layout import CheckpointSidecar, CheckpointTrigger


def _sample_checkpoints_dir(log_location: str, sample_id: int | str, epoch: int) -> str:
    return f"{_eval_checkpoints_dir(log_location)}/{sample_id}__{epoch}"


async def ensure_sample_checkpoints_dir(
    log_location: str, sample_id: int | str, epoch: int, eval_id: str
) -> str:
    """Create (idempotent) and return the sample checkpoints dir path.

    Also ensures the eval checkpoints dir + manifest exist; that's an
    implementation detail callers shouldn't have to repeat.
    """
    await init_eval_checkpoints_dir(log_location, eval_id)
    return await anyio.to_thread.run_sync(
        _ensure_sample_checkpoints_dir_blocking, log_location, sample_id, epoch
    )


def _ensure_sample_checkpoints_dir_blocking(
    log_location: str, sample_id: int | str, epoch: int
) -> str:
    sample_dir = _sample_checkpoints_dir(log_location, sample_id, epoch)
    filesystem(sample_dir).mkdir(sample_dir, exist_ok=True)
    return sample_dir


async def write_sidecar(
    *,
    sample_checkpoints_dir: str,
    checkpoint_id: int,
    trigger: CheckpointTrigger,
    turn: int,
    host_snapshot_id: str | None = None,
) -> str:
    """Write ``ckpt-NNNNN.json`` for this checkpoint. Returns the path."""
    return await anyio.to_thread.run_sync(
        _write_sidecar_blocking,
        sample_checkpoints_dir,
        checkpoint_id,
        trigger,
        turn,
        host_snapshot_id,
    )


def _write_sidecar_blocking(
    sample_checkpoints_dir: str,
    checkpoint_id: int,
    trigger: CheckpointTrigger,
    turn: int,
    host_snapshot_id: str | None,
) -> str:
    sidecar = CheckpointSidecar(
        checkpoint_id=checkpoint_id,
        trigger=trigger,
        turn=turn,
        created_at=datetime.now(timezone.utc),
        # Phase 3 (in progress): no I/O cost reported until the cycle
        # is wrapped in timing instrumentation.
        duration_ms=0,
        size_bytes=0,
        host_snapshot_id=host_snapshot_id,
    )

    sidecar_path = f"{sample_checkpoints_dir}/ckpt-{checkpoint_id:05d}.json"
    # TODO(checkpointing-phase-3): make the sidecar write atomic (write
    # `.tmp`, fsync, rename). Per §4d, the sidecar is the commit point —
    # a torn write would expose a half-built checkpoint. Acceptable
    # while no real snapshot is referenced.
    with file(sidecar_path, "w") as f:
        f.write(sidecar.model_dump_json(indent=2))
    return sidecar_path
