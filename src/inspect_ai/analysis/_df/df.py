from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Sequence, TypeAlias

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.file import filesystem
from inspect_ai._util.version import verify_required_version

if TYPE_CHECKING:
    import pandas as pd

LogPaths: TypeAlias = PathLike[str] | str | Sequence[PathLike[str] | str]


def evals_df(logs: LogPaths, recursive: bool = True) -> "pd.DataFrame":
    _verify_prerequisites()
    import pyarrow as pa

    # resolve logs
    logs = resolve_logs(logs, recursive=recursive)

    return pa.Table.from_pydict({"log": logs}).to_pandas()


def samples_df(logs: LogPaths, recursive: bool = True) -> pd.DataFrame:
    _verify_prerequisites()
    import pandas as pd

    # resolve logs
    logs = resolve_logs(logs, recursive=recursive)

    return pd.DataFrame()


def events_df(logs: LogPaths, recursive: bool = True) -> pd.DataFrame:
    _verify_prerequisites()
    import pandas as pd

    return pd.DataFrame()


def resolve_logs(logs: LogPaths, recursive: bool) -> list[str]:
    # normalize to list of str
    logs = [logs] if isinstance(logs, str | PathLike[str]) else logs
    logs = [Path(log).as_posix() if isinstance(log, PathLike) else log for log in logs]

    # expand directories
    log_paths: list[str] = []
    for log in logs:
        if isinstance(log, PathLike):
            log = Path(log).as_posix()
        fs = filesystem(log)
        info = fs.info(log)
        if info.type == "directory":
            log_paths.extend(
                [
                    fi.name
                    for fi in fs.ls(info.name, recursive=recursive)
                    if fi.type == "file"
                ]
            )
        else:
            log_paths.append(log)

    return log_paths


def _verify_prerequisites() -> None:
    # ensure we have all of the optional packages we need
    required_packages: list[str] = []
    try:
        import pandas  # noqa: F401
    except ImportError:
        required_packages.append("pandas")

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        required_packages.append("pyarrow")

    try:
        import jsonpath_ng  # type: ignore  # noqa: F401
    except ImportError:
        required_packages.append("jsonpath-ng")

    if len(required_packages) > 0:
        raise pip_dependency_error("inspect_ai.analysis", required_packages)

    # enforce version constraints
    verify_required_version("inspect_ai.analysis", "pandas", "2.0.0")
    verify_required_version("inspect_ai.analysis", "pyarrow", "10.0.1")
    verify_required_version("inspect_ai.analysis", "jsonpath-ng", "1.7.0")
