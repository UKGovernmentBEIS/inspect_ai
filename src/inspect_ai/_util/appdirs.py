from pathlib import Path

from platformdirs import user_cache_path, user_runtime_path

from inspect_ai._util.constants import PKG_NAME


def inspect_runtime_dir(subdir: str | None) -> Path:
    runtime_dir = user_runtime_path(PKG_NAME)
    if subdir:
        runtime_dir = runtime_dir / subdir
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def inspect_cache_dir(subdir: str | None) -> Path:
    cache_dir = user_cache_path(PKG_NAME)
    if subdir:
        cache_dir = cache_dir / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
