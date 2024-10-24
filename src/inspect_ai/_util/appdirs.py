import textwrap
from pathlib import Path

from platformdirs import user_cache_path, user_runtime_path

from inspect_ai._util.constants import PKG_NAME


def _xdg_error(dir_type: str, dir: Path) -> str:
    return textwrap.dedent(f"""{dir_type} directory {dir} is not writeable.
        This may be because you are running Inspect without a normal login session.
        On Linux, try setting XDG_RUNTIME_DIR to somewhere writeable.
        See also https://github.com/UKGovernmentBEIS/inspect_ai/issues/51.""")


def inspect_runtime_dir(subdir: str | None) -> Path:
    runtime_dir = user_runtime_path(PKG_NAME)
    if subdir:
        runtime_dir = runtime_dir / subdir
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise Exception(_xdg_error("Runtime", runtime_dir)) from e
    return runtime_dir


def inspect_cache_dir(subdir: str | None) -> Path:
    cache_dir = user_cache_path(PKG_NAME)
    if subdir:
        cache_dir = cache_dir / subdir
    # catch this failure, suggest setting XDG_CACHE_HOME
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise Exception(_xdg_error("Cache", cache_dir)) from e
    return cache_dir
