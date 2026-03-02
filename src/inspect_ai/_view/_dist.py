"""Resolve the frontend dist directory, downloading LFS objects if needed."""

import logging
from pathlib import Path

from inspect_ai._lfs import LFSError, resolve_lfs_directory
from inspect_ai._util.appdirs import inspect_cache_dir

_DIST_DIR = Path(__file__).parent / "www" / "dist"
_REPO_URL = "https://github.com/UKGovernmentBEIS/inspect_ai.git"
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def resolve_dist_directory() -> Path:
    """Resolve the frontend dist directory, downloading LFS objects if needed.

    If the dist directory contains LFS pointer stubs (common when cloning
    without Git LFS installed), transparently downloads the real assets
    from the LFS server and caches them locally.
    """
    lfs_logger = logging.getLogger("inspect_ai._lfs")
    prev_level = lfs_logger.level
    lfs_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    lfs_logger.addHandler(handler)
    try:
        return resolve_lfs_directory(
            _DIST_DIR,
            cache_dir=inspect_cache_dir("dist"),
            repo_url=_REPO_URL,
        )
    except LFSError as e:
        raise RuntimeError(
            f"{e}\n"
            "To fix this, either:\n"
            "  1. Install Git LFS: brew install git-lfs && git lfs install && git lfs pull\n"
            "  2. Build locally: cd src/inspect_ai/_view/www && pnpm build"
        ) from e
    finally:
        lfs_logger.removeHandler(handler)
        lfs_logger.setLevel(prev_level)
