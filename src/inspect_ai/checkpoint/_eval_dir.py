"""Eval-level checkpoint directory init.

For an eval log at ``<log>.eval``, the checkpoint tree lives at
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


def checkpoint_dir_for_log(log_location: str) -> str:
    """Return the canonical checkpoint directory for an eval log."""
    return f"{log_location}.checkpoints"


async def init_eval_dir(log_location: str, eval_id: str) -> str:
    """Ensure the eval-level checkpoint directory and manifest exist.

    Idempotent: if the manifest is already present (e.g. another sample
    in the same eval got there first), the existing one is left alone
    and its ``eval_id`` is verified to match. Returns the directory path.
    """
    return await anyio.to_thread.run_sync(
        _init_eval_dir_blocking, log_location, eval_id
    )


def _init_eval_dir_blocking(log_location: str, eval_id: str) -> str:
    checkpoint_dir = checkpoint_dir_for_log(log_location)
    fs = filesystem(checkpoint_dir)
    fs.mkdir(checkpoint_dir, exist_ok=True)

    manifest_path = f"{checkpoint_dir}/manifest.json"
    if fs.exists(manifest_path):
        with file(manifest_path, "r") as f:
            existing = CheckpointManifest.model_validate_json(f.read())
        if existing.eval_id != eval_id:
            raise RuntimeError(
                f"Checkpoint manifest at {manifest_path} has eval_id "
                f"{existing.eval_id!r}, but the active eval is {eval_id!r}. "
                "The checkpoint directory may belong to a different eval."
            )
        return checkpoint_dir

    # TODO(checkpointing-phase-3): two samples in the same eval racing
    # here will both write a manifest, and the loser's password will be
    # silently replaced. Acceptable while `_fire()` is still a no-op;
    # before the host repo write lands, switch to an exclusive-create
    # primitive (or have the eval init layer write the manifest once
    # before samples start).
    manifest = CheckpointManifest(
        eval_id=eval_id,
        layout_version=_LAYOUT_VERSION,
        engine="restic",
        restic_password=secrets.token_urlsafe(32),
    )
    with file(manifest_path, "w") as f:
        f.write(manifest.model_dump_json(indent=2))
    return checkpoint_dir


__all__ = ["checkpoint_dir_for_log", "init_eval_dir"]
