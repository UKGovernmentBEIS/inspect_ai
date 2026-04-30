"""Eval checkpoints dir init.

For an eval log at ``<log>.eval``, the eval checkpoints dir lives at
``<log>.eval.checkpoints/`` and is rooted by an eval-level
``manifest.json`` (see ``design/plans/checkpointing-working.md`` §1).
The manifest is created on the first checkpoint; subsequent calls are
idempotent.
"""

from __future__ import annotations

import secrets

import anyio

from inspect_ai._util.file import file, filesystem

from ._layout import CheckpointManifest

_LAYOUT_VERSION = 1


def _eval_checkpoints_dir(log_location: str) -> str:
    """Return the eval checkpoints dir path for an eval log."""
    return f"{log_location}.checkpoints"


async def init_eval_checkpoints_dir(log_location: str, eval_id: str) -> str:
    """Ensure the eval checkpoints dir and manifest exist.

    Idempotent: if the manifest is already present (e.g. another sample
    in the same eval got there first), the existing one is left alone
    and its ``eval_id`` is verified to match. Returns the directory path.
    """
    return await anyio.to_thread.run_sync(
        _init_eval_checkpoints_dir_blocking, log_location, eval_id
    )


def _init_eval_checkpoints_dir_blocking(log_location: str, eval_id: str) -> str:
    eval_checkpoints_dir = _eval_checkpoints_dir(log_location)
    fs = filesystem(eval_checkpoints_dir)
    fs.mkdir(eval_checkpoints_dir, exist_ok=True)

    manifest_path = f"{eval_checkpoints_dir}/manifest.json"
    if fs.exists(manifest_path):
        with file(manifest_path, "r") as f:
            existing = CheckpointManifest.model_validate_json(f.read())
        if existing.eval_id != eval_id:
            raise RuntimeError(
                f"Checkpoint manifest at {manifest_path} has eval_id "
                f"{existing.eval_id!r}, but the active eval is {eval_id!r}. "
                "The checkpoint directory may belong to a different eval."
            )
        return eval_checkpoints_dir

    # TODO(checkpointing-phase-3): two samples in the same eval racing
    # here will both write a manifest, and the loser's password will be
    # silently replaced. Acceptable while `_fire()` writes no real
    # snapshot; before the host repo write lands, switch to an
    # exclusive-create primitive (or have the eval init layer write the
    # manifest once before samples start).
    manifest = CheckpointManifest(
        eval_id=eval_id,
        layout_version=_LAYOUT_VERSION,
        engine="restic",
        restic_password=secrets.token_urlsafe(32),
    )
    with file(manifest_path, "w") as f:
        f.write(manifest.model_dump_json(indent=2))
    return eval_checkpoints_dir
