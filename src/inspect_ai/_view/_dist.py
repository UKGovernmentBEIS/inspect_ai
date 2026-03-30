"""Resolve the frontend dist directory, downloading LFS objects if needed."""

from pathlib import Path

from inspect_ai._display import display
from inspect_ai._lfs import LFSError, resolve_lfs_directory_verbose
from inspect_ai._util.appdirs import inspect_cache_dir

_DIST_DIR = Path(__file__).parent / "dist"
_REPO_URL = "https://github.com/UKGovernmentBEIS/inspect_ai.git"


def resolve_dist_directory() -> Path:
    """Resolve the frontend dist directory, downloading LFS objects if needed.

    Returns:
        Path to a directory containing real (non-pointer) dist files.

    Raises:
        RuntimeError: If LFS resolution fails.
    """
    try:
        result = resolve_lfs_directory_verbose(
            _DIST_DIR,
            cache_dir=inspect_cache_dir("dist"),
            repo_url=_REPO_URL,
        )
        if result != _DIST_DIR:
            display().print(f"Serving static data from {result}")
        return result
    except LFSError as e:
        raise RuntimeError(
            f"{e}\n"
            "To fix this, either:\n"
            "  1. Install Git LFS: brew install git-lfs && git lfs install && git lfs pull\n"
            "  2. Build locally: cd src/inspect_ai/_view/ts-mono && pnpm build"
        ) from e
