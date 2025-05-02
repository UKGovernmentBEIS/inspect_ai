from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence, TypeAlias, overload

from pydantic import JsonValue

from inspect_ai._display import display
from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.file import filesystem
from inspect_ai._util.json import jsonable_python
from inspect_ai._util.path import native_path, pretty_path
from inspect_ai._util.version import verify_required_version
from inspect_ai.analysis._df.record import import_record
from inspect_ai.analysis._df.util import eval_id
from inspect_ai.log._file import read_eval_log

from .spec_eval import EvalDefault
from .types import ColumnErrors, Columns, ColumnType

if TYPE_CHECKING:
    import pandas as pd

LogPaths: TypeAlias = PathLike[str] | str | Sequence[PathLike[str] | str]


# score_match_accuracy
# score_match_stderr

#    "score_*_*":

# .value(lambda x: ",".join(x))


@overload
def evals_df(
    logs: LogPaths,
    columns: Columns = EvalDefault,
    recursive: bool = True,
    dry_run: Literal[False] = False,
) -> "pd.DataFrame": ...


@overload
def evals_df(
    logs: LogPaths,
    columns: Columns = EvalDefault,
    recursive: bool = True,
    dry_run: Literal[True] = True,
) -> ColumnErrors: ...


def evals_df(
    logs: LogPaths,
    columns: Columns = EvalDefault,
    recursive: bool = True,
    dry_run: bool = False,
) -> "pd.DataFrame" | ColumnErrors:
    """Read a dataframe containing evals.

    Args:
       logs: One or more paths to log files or log directories.
       columns: Specification for what columns to read from the log file.
       recursive: Include recursive contents of directories (defaults to `True`)
       dry_run: Attempt to read data frame and report errors that occur. Defaults to `False`.

    Returns:
       For `strict`, a Pandas `DataFrame` with information for the specified logs.
       For `strict=False`, a tuple of Pandas `DataFrame` and a dictionary of errors
       encountered (by log file) during import.
    """
    _verify_prerequisites()
    import pyarrow as pa

    # resolve logs
    log_paths = _resolve_logs(logs, recursive=recursive)

    # accumulate errors for strict=False
    all_errors = ColumnErrors()

    # read logs
    records: list[dict[str, ColumnType]] = []
    with display().progress(total=len(log_paths)) as p:
        for log_path in log_paths:
            log = read_eval_log(log_path, header_only=True)
            log_data: dict[str, JsonValue] = jsonable_python(log) | {
                "id": eval_id(log.eval.run_id, log.eval.task_id),
                "log": native_path(log.location),
            }
            if dry_run:
                errors = import_record(log_data, columns, dry_run=True)
                all_errors[pretty_path(log_path)] = errors
            else:
                record = import_record(log_data, columns, dry_run=False)
                records.append(record)
            p.update()

    # return table (+errors if strict=False)
    if dry_run:
        return all_errors
    else:
        return pa.Table.from_pylist(records).to_pandas()


def samples_df(
    logs: LogPaths, summaries: bool = True, recursive: bool = True
) -> pd.DataFrame:
    _verify_prerequisites()
    import pandas as pd

    # use *.samples as branch point to look in summaries

    # resolve logs
    logs = _resolve_logs(logs, recursive=recursive)

    return pd.DataFrame()


def events_df(logs: LogPaths, recursive: bool = True) -> pd.DataFrame:
    _verify_prerequisites()
    import pandas as pd

    return pd.DataFrame()


def _resolve_logs(logs: LogPaths, recursive: bool) -> list[str]:
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
