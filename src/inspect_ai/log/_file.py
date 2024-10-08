import os
import re
from typing import Any, Callable, Literal

from pydantic_core import to_json

from inspect_ai._util.constants import ALL_LOG_FORMATS
from inspect_ai._util.file import (
    FileInfo,
    file,
    filesystem,
)

from ._log import EvalLog
from ._recorders import recorder_type_for_format, recorder_type_for_location


class EvalLogInfo(FileInfo):
    task: str
    """Task name."""

    task_id: str
    """Task id."""

    suffix: str | None
    """Log file suffix (e.g. "-scored")"""


def list_eval_logs(
    log_dir: str = os.environ.get("INSPECT_LOG_DIR", "./logs"),
    formats: list[Literal["eval", "json"]] | None = None,
    filter: Callable[[EvalLog], bool] | None = None,
    recursive: bool = True,
    descending: bool = True,
    fs_options: dict[str, Any] = {},
) -> list[EvalLogInfo]:
    """List all eval logs in a directory.

    Args:
      log_dir (str): Log directory (defaults to INSPECT_LOG_DIR)
      formats (Literal["eval", "json"]): Formats to list (default
        to listing all formats)
      filter (Callable[[EvalLog], bool]): Filter to limit logs returned.
         Note that the EvalLog instance passed to the filter has only
         the EvalLog header (i.e. does not have the samples or logging output).
      recursive (bool): List log files recursively (defaults to True).
      descending (bool): List in descending order.
      fs_options (dict[str, Any]): Optional. Additional arguments to pass through
          to the filesystem provider (e.g. `S3FileSystem`).

    Returns:
       List of EvalLog Info.

    """
    # get the eval logs
    fs = filesystem(log_dir, fs_options)
    if fs.exists(log_dir):
        eval_logs = log_files_from_ls(
            fs.ls(log_dir, recursive=recursive), formats, descending
        )
    else:
        return []

    # apply filter if requested
    if filter:
        return [
            log
            for log in eval_logs
            if filter(read_eval_log(log.name, header_only=True))
        ]
    else:
        return eval_logs


def write_eval_log(
    log: EvalLog,
    log_file: str | FileInfo,
    format: Literal["eval", "json", "auto"] = "auto",
) -> None:
    """Write an evaluation log.

    Args:
       log (EvalLog): Evaluation log to write.
       log_file (str | FileInfo): Location to write log to.
       format (Literal["eval", "json", "auto"]): Write to format
          (defaults to 'auto' based on `log_file` extension)
    """
    log_file = log_file if isinstance(log_file, str) else log_file.name

    # get recorder type
    if format == "auto":
        recorder_type = recorder_type_for_location(log_file)
    else:
        recorder_type = recorder_type_for_format(format)
    recorder_type.write_log(log_file, log)


def write_log_dir_manifest(
    log_dir: str,
    *,
    filename: str = "logs.json",
    output_dir: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None:
    """Write a manifest for a log directory.

    A log directory manifest is a dictionary of EvalLog headers (EvalLog w/o samples)
    keyed by log file names (names are relative to the log directory)

    Args:
      log_dir (str): Log directory to write manifest for.
      filename (str): Manifest filename (defaults to "logs.json")
      output_dir (str | None): Output directory for manifest (defaults to log_dir)
      fs_options (dict[str,Any]): Optional. Additional arguments to pass through
        to the filesystem provider (e.g. `S3FileSystem`).
    """
    # resolve log dir to full path
    fs = filesystem(log_dir)
    log_dir = fs.info(log_dir).name

    # list eval logs
    logs = list_eval_logs(log_dir)

    # resolve to manifest (make filenames relative to the log dir)
    names = [manifest_eval_log_name(log, log_dir, fs.sep) for log in logs]
    headers = read_eval_log_headers(logs)
    manifest_logs = dict(zip(names, headers))

    # form target path and write
    output_dir = output_dir or log_dir
    fs = filesystem(output_dir)
    manifest = f"{output_dir}{fs.sep}{filename}"
    manifest_json = to_json(
        value=manifest_logs, indent=2, exclude_none=True, fallback=lambda _x: None
    )
    with file(manifest, mode="wb", fs_options=fs_options) as f:
        f.write(manifest_json)


def read_eval_log(
    log_file: str | FileInfo,
    header_only: bool = False,
    format: Literal["eval", "json", "auto"] = "auto",
) -> EvalLog:
    """Read an evaluation log.

    Args:
       log_file (str | FileInfo): Log file to read.
       header_only (bool): Read only the header (i.e. exclude
         the "samples" and "logging" fields). Defaults to False.
       format (Literal["eval", "json", "auto"]): Read from format
          (defaults to 'auto' based on `log_file` extension)

    Returns:
       EvalLog object read from file.
    """
    # resolve to file path
    log_file = log_file if isinstance(log_file, str) else log_file.name

    # get recorder type
    if format == "auto":
        recorder_type = recorder_type_for_location(log_file)
    else:
        recorder_type = recorder_type_for_format(format)
    return recorder_type.read_log(log_file, header_only)


def read_eval_log_headers(
    log_files: list[str] | list[FileInfo] | list[EvalLogInfo],
) -> list[EvalLog]:
    return [read_eval_log(log_file, header_only=True) for log_file in log_files]


def manifest_eval_log_name(info: EvalLogInfo, log_dir: str, sep: str) -> str:
    # ensure that log dir has a trailing seperator
    if not log_dir.endswith(sep):
        log_dir = f"{log_dir}/"

    # slice off log_dir from the front
    log = info.name.replace(log_dir, "")

    # manifests are web artifacts so always use forward slash
    return log.replace("\\", "/")


def log_files_from_ls(
    ls: list[FileInfo],
    formats: list[Literal["eval", "json"]] | None,
    descending: bool = True,
) -> list[EvalLogInfo]:
    extensions = [f".{format}" for format in (formats or ALL_LOG_FORMATS)]
    return [
        log_file_info(file)
        for file in sorted(
            ls, key=lambda file: (file.mtime if file.mtime else 0), reverse=descending
        )
        if file.type == "file" and is_log_file(file.name, extensions)
    ]


log_file_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}[:-]\d{2}[:-]\d{2}.*$"


def is_log_file(file: str, extensions: list[str]) -> bool:
    parts = file.replace("\\", "/").split("/")
    name = parts[-1]
    return re.match(log_file_pattern, name) is not None and any(
        [name.endswith(suffix) for suffix in extensions]
    )


def log_file_info(info: FileInfo) -> "EvalLogInfo":
    # extract the basename and split into parts
    # (deal with previous logs had the model in their name)
    basename = os.path.splitext(info.name)[0]
    parts = basename.split("/").pop().split("_")
    last_idx = 3 if len(parts) > 3 else 2
    task = parts[1]
    part3 = parts[last_idx].split("-")
    task_id = part3[0]
    suffix = task_id[2] if len(part3) > 1 else None
    return EvalLogInfo(
        name=info.name,
        type=info.type,
        size=info.size,
        mtime=info.mtime,
        task=task,
        task_id=task_id,
        suffix=suffix,
    )


def eval_log_json(log: EvalLog) -> str:
    # serialize to json (ignore values that are unserializable)
    # these values often result from solvers using metadata to
    # pass around 'live' objects -- this is fine to do and we
    # don't want to prevent it at the serialization level
    return to_json(
        value=log, indent=2, exclude_none=True, fallback=lambda _x: None
    ).decode()
