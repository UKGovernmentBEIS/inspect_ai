"""Sample staging dir + per-sample subdir paths.

The sample staging dir is the host-local twin of the **sample
checkpoints dir** that exists only when the resolved **sample
checkpoints dir** is remote. Its layout mirrors a local sample
checkpoints dir (``restic/host/``,
``restic/sandboxes/<name>/``, ``context/``, ``ckpt-*.json``), plus
`.egress-manifest.txt` for host egress bookkeeping. When the
destination is local, no staging dir is created and restic writes
directly into the sample checkpoints dir.

The "sample root" concept — used by `_hydrate` and `_fire` — is
"wherever restic and checkpoint files are first materialized": the
staging dir when remote, the sample checkpoints dir when local.
"""

from __future__ import annotations

import anyio

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.asyncfiles import is_s3_filename

from .eval_checkpoints_dir import log_basename


def is_remote_destination(checkpoints_path: str) -> bool:
    """Whether the resolved sample checkpoints dir requires a staging dir."""
    return is_s3_filename(checkpoints_path)


def sample_staging_dir(log_location: str, sample_id: int | str, epoch: int) -> str:
    """Return the per-sample staging dir path (no FS side effects)."""
    return f"{_eval_staging_dir(log_location)}/{sample_id}__{epoch}"


async def ensure_sample_staging_dir(
    log_location: str, sample_id: int | str, epoch: int
) -> str:
    """Create (idempotent) and return the sample staging dir path.

    Always host-local (under ``inspect_cache_dir``), so a single
    ``anyio.Path.mkdir(parents=True, exist_ok=True)`` is enough — no
    S3 dispatch needed here.
    """
    sample_dir = sample_staging_dir(log_location, sample_id, epoch)
    await anyio.Path(sample_dir).mkdir(parents=True, exist_ok=True)
    return sample_dir


def restic_dir(sample_root: str) -> str:
    """Path to the per-sample restic subdir.

    Contains ``restic-config.json`` plus the ``host/`` and
    ``sandboxes/<name>/`` restic repos.
    """
    return f"{sample_root}/restic"


def host_repo_dir(sample_root: str) -> str:
    """Path to the per-sample host restic repo."""
    return f"{sample_root}/restic/host"


def sandbox_repo_dir(sample_root: str, name: str) -> str:
    """Path to the per-sample restic repo for sandbox ``name``."""
    return f"{sample_root}/restic/sandboxes/{name}"


def restic_config_path(sample_root: str) -> str:
    """Path to the per-sample restic config file (password store)."""
    return f"{sample_root}/restic/restic-config.json"


def context_dir(sample_root: str) -> str:
    """Path to the per-sample context subdir (restic backup source)."""
    return f"{sample_root}/context"


def _eval_staging_dir(log_location: str) -> str:
    return str(inspect_cache_dir("checkpoints") / log_basename(log_location))


async def ensure_context_dir(sample_root: str) -> str:
    """Create (idempotent) and return the context subdir path."""
    p = context_dir(sample_root)
    await anyio.Path(p).mkdir(parents=True, exist_ok=True)
    return p
