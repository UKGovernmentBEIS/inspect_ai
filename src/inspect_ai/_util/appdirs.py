from pathlib import Path

from platformdirs import user_cache_path, user_data_path

from inspect_ai._util.constants import PKG_NAME


def inspect_data_dir(subdir: str | None) -> Path:
    return package_data_dir(PKG_NAME, subdir)


def package_data_dir(package_name: str, subdir: str | None) -> Path:
    data_dir = user_data_path(package_name)
    if subdir:
        data_dir = data_dir / subdir
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def inspect_cache_dir(subdir: str | None) -> Path:
    cache_dir = user_cache_path(PKG_NAME)
    if subdir:
        cache_dir = cache_dir / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
