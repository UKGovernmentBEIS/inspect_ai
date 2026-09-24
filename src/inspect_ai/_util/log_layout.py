"""Eval log naming and companion-directory paths.

An eval log at ``<dir>/<name>.eval`` has companion directories beside it
whose names derive from ``<name>``: ``<name>.checkpoints/`` (sandbox
checkpoints) and ``<name>.shards/`` (per-worker shard logs). This module is
the single owner of the ``.eval`` / ``-recovered`` suffix rule those
derivations share, and of the ``{created}_{task}_{id}`` log name itself, so
that both the log recorders and the checkpoint package can use them.

Pure path computation — no filesystem side effects.
"""

import os

from inspect_ai._util.constants import MODEL_NONE
from inspect_ai._util.file import basename, clean_filename_component, dirname
from inspect_ai._util.task import task_display_name

_LOG_SUFFIX = ".eval"
_RECOVERED_SUFFIX = "-recovered"
_SHARDS_SUFFIX = ".shards"


def eval_log_name(*, task: str, task_id: str, created: str, model: str) -> str:
    """Return the eval log file name, without directory or suffix.

    The name is ``<created>_`` followed by ``INSPECT_EVAL_LOG_FILE_PATTERN``
    (default ``{task}_{id}``), with ``{task}``, ``{id}`` and ``{model}``
    substituted. Each component is passed through
    :func:`clean_filename_component`, and ``{model}`` is empty for the
    ``none`` model.

    Args:
        task: Task registry name (as in ``EvalSpec.task``); any package
            prefix is removed.
        task_id: Task id.
        created: Creation time as an ISO 8601 string (as in
            ``EvalSpec.created``).
        model: Model name (as in ``EvalSpec.model``).
    """
    log_file_pattern = os.getenv("INSPECT_EVAL_LOG_FILE_PATTERN", "{task}_{id}")
    log_file_name = f"{clean_filename_component(created)}_" + log_file_pattern
    log_file_name = log_file_name.replace(
        "{task}", clean_filename_component(task_display_name(task))
    )
    log_file_name = log_file_name.replace("{id}", clean_filename_component(task_id))
    model = clean_filename_component(model) if model != MODEL_NONE else ""
    log_file_name = log_file_name.replace("{model}", model)
    return log_file_name


def log_basename(log_location: str) -> str:
    """Return the log's basename with recovery and log suffixes stripped.

    Used to derive the companion directory names beside the log
    (``<log-base>.checkpoints/``, ``<log-base>.shards/``) and the matching
    per-eval checkpoint working dir under ``inspect_cache_dir("checkpoints")/``
    (ephemeral, host cache).
    """
    base = basename(log_location)
    if base.endswith(_LOG_SUFFIX):
        base = base[: -len(_LOG_SUFFIX)]
    if base.endswith(_RECOVERED_SUFFIX):
        base = base[: -len(_RECOVERED_SUFFIX)]
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


def eval_shards_dir(log_location: str) -> str:
    """Compute the shards dir path for a merged eval log.

    ``<dir>/<name>.eval`` (or ``<dir>/<name>-recovered.eval``) maps to
    ``<dir>/<name>.shards``, by the same suffix rule as
    :func:`eval_checkpoints_dir`. The inverse is
    :func:`eval_log_for_shards_dir`.
    """
    return _with_basename(log_location, f"{log_basename(log_location)}{_SHARDS_SUFFIX}")


def eval_log_for_shards_dir(shards_dir: str) -> str:
    """Compute the merged eval log path for a shards dir.

    ``<dir>/<name>.shards`` (with or without a trailing slash) maps to
    ``<dir>/<name>.eval``. The inverse of :func:`eval_shards_dir`, except
    that a ``-recovered`` log and its original share one shards dir, which
    maps back to the original.

    Raises:
        ValueError: If the directory name does not end in ``.shards``.
    """
    base = basename(shards_dir)
    if not base.endswith(_SHARDS_SUFFIX) or base == _SHARDS_SUFFIX:
        raise ValueError(
            f"Not a shards directory (expected '<name>{_SHARDS_SUFFIX}'): {shards_dir}"
        )
    return _with_basename(shards_dir, f"{base[: -len(_SHARDS_SUFFIX)]}{_LOG_SUFFIX}")


def _with_basename(location: str, name: str) -> str:
    """Replace the last path component of ``location`` with ``name``.

    Everything before that component is kept verbatim, so a bare relative
    name stays relative and a ``file:///`` or ``s3://bucket/`` prefix keeps
    its separators. Trailing forward or back slashes are dropped, as
    :func:`basename` treats both as separators.
    """
    location = location.rstrip("/\\")
    return location[: len(location) - len(basename(location))] + name
