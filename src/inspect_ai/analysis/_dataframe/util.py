from os import PathLike
from pathlib import Path
from typing import Sequence, TypeAlias

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.file import FileInfo, filesystem
from inspect_ai._util.version import verify_required_version
from inspect_ai.analysis._dataframe.columns import ColumnType
from inspect_ai.log._file import log_files_from_ls

LogPaths: TypeAlias = PathLike[str] | str | Sequence[PathLike[str] | str]


def verify_prerequisites() -> None:
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

    if len(required_packages) > 0:
        raise pip_dependency_error("inspect_ai.analysis", required_packages)

    # enforce version constraints
    verify_required_version("inspect_ai.analysis", "pandas", "2.0.0")
    verify_required_version("inspect_ai.analysis", "pyarrow", "10.0.1")


def resolve_logs(logs: LogPaths, recursive: bool, reverse: bool) -> list[str]:
    # normalize to list of str
    logs = [logs] if isinstance(logs, str | PathLike) else logs
    logs = [Path(log).as_posix() if isinstance(log, PathLike) else log for log in logs]

    # expand directories
    log_paths: list[FileInfo] = []
    for log in logs:
        if isinstance(log, PathLike):
            log = Path(log).as_posix()
        fs = filesystem(log)
        info = fs.info(log)
        if info.type == "directory":
            log_paths.extend(
                [
                    fi
                    for fi in fs.ls(info.name, recursive=recursive)
                    if fi.type == "file"
                ]
            )
        else:
            log_paths.append(info)

    log_files = log_files_from_ls(log_paths, descending=reverse)
    return [log_file.name for log_file in log_files]


def normalize_records(
    records: list[dict[str, ColumnType]],
) -> list[dict[str, ColumnType]]:
    all_keys = _get_all_keys(records)
    normalized_records = []
    for record in records:
        normalized_record = {key: record.get(key, None) for key in all_keys}
        normalized_records.append(normalized_record)
    return normalized_records


def _get_all_keys(records: list[dict[str, ColumnType]]) -> set[str]:
    all_keys: set[str] = set()
    for record in records:
        all_keys.update(record.keys())
    return all_keys
