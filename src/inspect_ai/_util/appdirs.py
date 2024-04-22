from pathlib import Path

from platformdirs import user_runtime_dir

from inspect_ai._util.constants import PKG_NAME


def inspect_runtime_dir(subdir: str | None) -> Path:
    runtime_dir = Path(user_runtime_dir(PKG_NAME))
    if subdir:
        runtime_dir = runtime_dir / subdir
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir
