"""Use-case-agnostic restic utilities.

Pure restic — no knowledge of sandboxes, checkpointing, or any
particular inspect_ai concept:

- :mod:`.binary` — platform identifiers + binary acquisition (download/cache).
- :mod:`.summary` — :class:`ResticBackupSummary` model (restic's JSON schema).
- :mod:`.ops` — :func:`init_repo`, :func:`run_backup`,
  :func:`restore_repo`, :func:`restic_env`.
"""

from .ops import init_repo, restic_env, restore_repo, run_backup
from .resolver import (
    SUPPORTED_PLATFORMS,
    Platform,
    cache_path,
    resolve_restic,
)
from .summary import ResticBackupSummary

__all__ = [
    "Platform",
    "ResticBackupSummary",
    "SUPPORTED_PLATFORMS",
    "cache_path",
    "init_repo",
    "resolve_restic",
    "restic_env",
    "restore_repo",
    "run_backup",
]
