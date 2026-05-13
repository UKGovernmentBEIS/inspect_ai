"""Eval checkpoints dir init.

For an eval log at ``<log>.eval`` with no override, the eval
checkpoints dir lives at ``<log-base>.checkpoints/`` (sibling to the
log; ``.eval`` stripped from the basename). With a ``checkpoints_dir``
override on :class:`CheckpointConfig`, the dir lands at
``<override>/<log-base>.checkpoints/``.

The dir is rooted by an eval-level ``manifest.json``
(see ``design/plans/checkpointing-working.md`` §1). The manifest is
created on first use; subsequent calls are idempotent.
"""

from __future__ import annotations

import secrets
import threading

import anyio

from inspect_ai._util.file import basename, dirname, file, filesystem

from .config import CheckpointConfig
from .layout import CheckpointManifest

# Serialize manifest init within a single inspect process. Multiple
# samples in an eval can hit `_init_eval_checkpoints_dir_blocking`
# concurrently from worker threads (each `init_eval_checkpoints_dir`
# call is wrapped in `anyio.to_thread.run_sync`); without a lock, both
# could see no manifest, both generate fresh passwords, and the second
# `open("w")` would either overwrite or tear the first's bytes.
#
# Cross-process races aren't covered. The eval_dir is derived from the
# log filename, which embeds the eval_id UUID — two processes sharing
# an eval_dir requires running `inspect eval retry <log>` against a
# log another process is still writing, and the `eval_id` mismatch
# check catches that loudly.
_manifest_lock = threading.Lock()

_LAYOUT_VERSION = 1
_LOG_SUFFIX = ".eval"


def eval_checkpoints_dir(log_location: str, override_root: str | None) -> str:
    """Compute the eval checkpoints dir path.

    Strips a trailing ``.eval`` from the log basename and appends
    ``.checkpoints``. Parent is ``override_root`` if provided, else the
    log's directory.
    """
    base = basename(log_location)
    if base.endswith(_LOG_SUFFIX):
        base = base[: -len(_LOG_SUFFIX)]
    parent = override_root if override_root else dirname(log_location)
    return f"{parent}/{base}.checkpoints"


def eval_checkpoints_dir_from_config(
    log_location: str,
    task: CheckpointConfig | None,
    eval_: CheckpointConfig | None,
) -> str | None:
    """Resolve the eval checkpoints dir from task + eval config layers.

    Returns ``None`` if neither layer supplies a config — meaning the
    eval was run without checkpointing. Otherwise computes the dir,
    honoring an explicit ``checkpoints_dir`` override (eval layer wins
    over task; sample layer cannot set this field).
    """
    if task is None and eval_ is None:
        return None
    override: str | None = None
    for layer in (task, eval_):
        if layer is not None and layer.checkpoints_location is not None:
            override = layer.checkpoints_location
    return eval_checkpoints_dir(log_location, override)


async def init_eval_checkpoints_dir(eval_dir: str, eval_id: str) -> None:
    """Ensure ``eval_dir`` and its manifest exist.

    Idempotent: if the manifest is already present (e.g. another sample
    in the same eval got there first), the existing one is left alone
    and its ``eval_id`` is verified to match.
    """
    await anyio.to_thread.run_sync(
        _init_eval_checkpoints_dir_blocking, eval_dir, eval_id
    )


def _init_eval_checkpoints_dir_blocking(eval_dir: str, eval_id: str) -> None:
    fs = filesystem(eval_dir)
    fs.mkdir(eval_dir, exist_ok=True)

    manifest_path = f"{eval_dir}/manifest.json"
    with _manifest_lock:
        if fs.exists(manifest_path):
            with file(manifest_path, "r") as f:
                existing = CheckpointManifest.model_validate_json(f.read())
            if existing.eval_id != eval_id:
                raise RuntimeError(
                    f"Checkpoint manifest at {manifest_path} has eval_id "
                    f"{existing.eval_id!r}, but the active eval is {eval_id!r}. "
                    "The checkpoint directory may belong to a different eval."
                )
            return

        manifest = CheckpointManifest(
            eval_id=eval_id,
            layout_version=_LAYOUT_VERSION,
            engine="restic",
            restic_password=secrets.token_urlsafe(32),
        )
        with file(manifest_path, "w") as f:
            f.write(manifest.model_dump_json(indent=2))


async def read_eval_manifest(eval_dir: str) -> CheckpointManifest:
    """Read the eval-level manifest. Caller must have ensured it exists."""
    return await anyio.to_thread.run_sync(_read_eval_manifest_blocking, eval_dir)


def _read_eval_manifest_blocking(eval_dir: str) -> CheckpointManifest:
    with file(f"{eval_dir}/manifest.json", "r") as f:
        return CheckpointManifest.model_validate_json(f.read())
