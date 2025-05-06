from __future__ import annotations

import re
from os import PathLike
from pathlib import Path
from re import Pattern
from typing import TYPE_CHECKING, Sequence, TypeAlias

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.file import FileInfo, filesystem
from inspect_ai._util.version import verify_required_version
from inspect_ai.log._file import log_files_from_ls

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa

from .columns import ColumnType

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
    all_keys: set[str] = set()
    for record in records:
        all_keys.update(record.keys())
    normalized_records = []
    for record in records:
        normalized_record = {key: record.get(key, None) for key in all_keys}
        normalized_records.append(normalized_record)
    return normalized_records


def resolve_columns(
    col_pattern: str, suffix: str, columns: list[str], processed_columns: list[str]
) -> list[str]:
    resolved_columns: list[str] = []

    if "*" not in col_pattern:
        # Regular column - check with suffix
        col_with_suffix = f"{col_pattern}{suffix}"
        if col_with_suffix in columns and col_with_suffix not in processed_columns:
            resolved_columns.append(col_with_suffix)
        # Then without suffix
        elif col_pattern in columns and col_pattern not in processed_columns:
            resolved_columns.append(col_pattern)
    else:
        # Wildcard pattern - check both with and without suffix
        suffix_pattern = col_pattern + suffix
        matching_with_suffix = match_col_pattern(
            suffix_pattern, columns, processed_columns
        )
        matching_without_suffix = match_col_pattern(
            col_pattern, columns, processed_columns
        )

        # Add all matches
        matched_columns = sorted(set(matching_with_suffix + matching_without_suffix))
        resolved_columns.extend(matched_columns)

    return resolved_columns


def match_col_pattern(
    pattern: str, columns: list[str], processed_columns: list[str]
) -> list[str]:
    regex = _col_pattern_to_regex(pattern)
    return [c for c in columns if regex.match(c) and c not in processed_columns]


def _col_pattern_to_regex(pattern: str) -> Pattern[str]:
    parts = []
    for part in re.split(r"(\*)", pattern):
        if part == "*":
            parts.append(".*")
        else:
            parts.append(re.escape(part))
    return re.compile("^" + "".join(parts) + "$")


def add_unreferenced_columns(
    columns: list[str], referenced_columns: list[str]
) -> list[str]:
    unreferenced_columns = sorted([c for c in columns if c not in referenced_columns])
    return referenced_columns + unreferenced_columns


def records_to_pandas(records: list[dict[str, ColumnType]]) -> "pd.DataFrame":
    import pyarrow as pa

    records = normalize_records(records)
    table = pa.Table.from_pylist(records).to_pandas(types_mapper=arrow_types_mapper)
    return table


def arrow_types_mapper(
    arrow_type: "pa.DataType",
) -> "pd.api.extensions.ExtensionDtype" | None:
    import pandas as pd
    import pyarrow as pa

    # convert str => str
    if pa.types.is_string(arrow_type):
        return pd.StringDtype()
    # default conversion for other types
    else:
        return None
