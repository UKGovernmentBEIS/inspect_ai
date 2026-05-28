"""Eval checkpoints dir path computation.

For an eval log at ``<log>.eval`` with no override, the eval
checkpoints dir lives at ``<log-base>.checkpoints/`` (sibling to the
log; ``.eval`` stripped from the basename). With a ``checkpoints_location``
override on :class:`CheckpointConfig`, the dir lands at
``<override>/<log-base>.checkpoints/`` (the override is the *evals
checkpoints dir*; the per-eval subdir name is unchanged).

Pure path computation — no filesystem side effects.
"""

from __future__ import annotations

from inspect_ai._util.file import basename, dirname

from ..config import CheckpointConfig

_LOG_SUFFIX = ".eval"


def log_basename(log_location: str) -> str:
    """Return the log's basename with any trailing ``.eval`` stripped.

    Used to derive the per-eval ``<log-base>.checkpoints/`` directory
    name (durable, alongside the log) and the matching per-eval working
    dir under ``inspect_cache_dir("checkpoints")/`` (ephemeral, host
    cache). Single owner of the ``.eval`` suffix convention.
    """
    base = basename(log_location)
    if base.endswith(_LOG_SUFFIX):
        base = base[: -len(_LOG_SUFFIX)]
    return base


def eval_checkpoints_dir(log_location: str, override_root: str | None) -> str:
    """Compute the eval checkpoints dir path.

    Strips a trailing ``.eval`` from the log basename and appends
    ``.checkpoints``. Parent is ``override_root`` (the *evals
    checkpoints dir*) if provided, else the log's directory. Any
    trailing slash on the parent is stripped so the join never
    produces an empty path segment (which S3 honors literally as an
    extra "directory").
    """
    parent = (override_root if override_root else dirname(log_location)).rstrip("/")
    return f"{parent}/{log_basename(log_location)}.checkpoints"


def eval_checkpoints_dir_from_config(
    log_location: str,
    task: CheckpointConfig | None,
    eval_: CheckpointConfig | None,
) -> str | None:
    """Resolve the eval checkpoints dir from task + eval config layers.

    Returns ``None`` if neither layer supplies a config — meaning the
    eval was run without checkpointing. Otherwise computes the dir,
    honoring an explicit ``checkpoints_location`` override (eval layer
    wins over task; sample layer cannot set this field).
    """
    if task is None and eval_ is None:
        return None
    override: str | None = None
    for layer in (task, eval_):
        if layer is not None and layer.checkpoints_location is not None:
            override = layer.checkpoints_location
    return eval_checkpoints_dir(log_location, override)
