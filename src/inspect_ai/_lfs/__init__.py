"""LFS transparent fallback for directories containing pointer files."""

from .exceptions import LFSError
from .resolver import resolve_lfs_directory

__all__ = ["LFSError", "resolve_lfs_directory"]
