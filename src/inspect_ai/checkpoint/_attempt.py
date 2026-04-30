"""Per-attempt checkpoint subdirectory and sidecar writes.

Each ``(sample, epoch[, retry])`` attempt gets its own subtree under the
eval-level checkpoint directory; sidecars (``ckpt-NNNNN.json``) live
inside it as the plaintext index for each fired checkpoint. See
``design/plans/checkpointing-working.md`` §1.
"""

from __future__ import annotations

from datetime import datetime, timezone

import anyio

from inspect_ai._util.file import file, filesystem

from ._layout import CheckpointSidecar, CheckpointTrigger


def attempt_dir_for(eval_dir: str, sample_id: int | str, epoch: int) -> str:
    """Return the per-attempt subdirectory path inside an eval dir.

    Phase 3 (in progress): the optional ``_<retry>`` suffix is omitted
    until ``ActiveSample`` exposes the attempt index.
    """
    return f"{eval_dir}/{sample_id}__{epoch}"


async def write_sidecar(
    *,
    attempt_dir: str,
    checkpoint_id: int,
    trigger: CheckpointTrigger,
    turn: int,
) -> str:
    """Write ``ckpt-NNNNN.json`` for this checkpoint.

    Creates the attempt subdirectory if it doesn't exist. Returns the
    sidecar's path.
    """
    return await anyio.to_thread.run_sync(
        _write_sidecar_blocking, attempt_dir, checkpoint_id, trigger, turn
    )


def _write_sidecar_blocking(
    attempt_dir: str,
    checkpoint_id: int,
    trigger: CheckpointTrigger,
    turn: int,
) -> str:
    fs = filesystem(attempt_dir)
    fs.mkdir(attempt_dir, exist_ok=True)

    sidecar = CheckpointSidecar(
        checkpoint_id=checkpoint_id,
        trigger=trigger,
        turn=turn,
        created_at=datetime.now(timezone.utc),
        # Phase 3 (in progress): host repo write isn't wired yet, so
        # there is no real snapshot to reference and no I/O cost to
        # report. These fields get real values in subsequent slices.
        duration_ms=0,
        size_bytes=0,
    )

    sidecar_path = f"{attempt_dir}/ckpt-{checkpoint_id:05d}.json"
    # TODO(checkpointing-phase-3): make the sidecar write atomic (write
    # `.tmp`, fsync, rename). Per §4d, the sidecar is the commit point —
    # a torn write would expose a half-built checkpoint. Acceptable
    # while no real snapshot is referenced.
    with file(sidecar_path, "w") as f:
        f.write(sidecar.model_dump_json(indent=2))
    return sidecar_path


__all__ = ["attempt_dir_for", "write_sidecar"]
