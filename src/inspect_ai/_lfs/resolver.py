"""Directory resolution with LFS transparent fallback.

Determines whether a directory contains real files or LFS pointer files,
and returns a directory path with real content in either case.
"""

import logging
from pathlib import Path

from ._cache import download_lfs_objects
from ._pointer import is_lfs_pointer
from .exceptions import LFSResolverError


def resolve_lfs_directory(
    source_dir: Path,
    cache_dir: Path,
    repo_url: str,
) -> Path:
    """Resolve a directory that may contain LFS pointer files.

    Recursively checks source_dir for LFS pointers. If none are found, returns
    source_dir as-is. Otherwise downloads real content from the LFS server into
    cache_dir and returns cache_dir.

    The cache is incremental: only files whose OID changed or are missing are
    downloaded, and files removed from source_dir are pruned from cache_dir.

    Args:
        source_dir: Directory to check recursively for LFS pointer files.
        cache_dir: Cache directory for downloaded LFS content.
        repo_url: HTTPS URL of the git repository (for LFS downloads).

    Returns:
        Path to a directory tree containing real file content.

    Raises:
        LFSResolverError: If source_dir is missing or LFS download fails.
    """
    if not source_dir.is_dir():
        raise LFSResolverError(f"Directory not found: {source_dir}")

    if not _has_lfs_pointers(source_dir):
        return source_dir

    try:
        download_lfs_objects(source_dir, cache_dir, repo_url=repo_url)
    except Exception as e:
        raise LFSResolverError(f"Failed to download LFS objects: {e}") from e

    return cache_dir


def resolve_lfs_directory_verbose(
    source_dir: Path,
    cache_dir: Path,
    repo_url: str,
) -> Path:
    """Like resolve_lfs_directory but with INFO-level progress logging to stderr."""
    lfs_logger = logging.getLogger("inspect_ai._lfs")
    prev_level = lfs_logger.level
    lfs_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    lfs_logger.addHandler(handler)
    try:
        return resolve_lfs_directory(source_dir, cache_dir, repo_url)
    finally:
        lfs_logger.setLevel(prev_level)
        lfs_logger.removeHandler(handler)


def _has_lfs_pointers(directory: Path) -> bool:
    """Check if any file in the directory is an LFS pointer."""
    return any(is_lfs_pointer(f) for f in directory.rglob("*") if f.is_file())
