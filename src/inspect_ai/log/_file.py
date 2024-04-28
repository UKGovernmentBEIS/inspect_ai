import json
import os
import re
from pathlib import Path
from typing import Any, Callable, cast
from urllib.parse import urlparse

import json_stream  # type: ignore
from pydantic import BaseModel, Field

from inspect_ai._util.file import FileInfo, file, filesystem

from ._log import (
    EvalError,
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSpec,
    EvalStats,
    LogEvent,
    LoggingMessage,
    Recorder,
)


class EvalLogInfo(FileInfo):
    task: str
    """Task name."""

    task_id: str
    """Task id."""

    suffix: str | None
    """Log file suffix (e.g. "-scored")"""


def list_eval_logs(
    log_dir: str = os.environ.get("INSPECT_LOG_DIR", "./logs"),
    filter: Callable[[EvalLog], bool] | None = None,
    recursive: bool = True,
    extensions: list[str] = [".json", ".jsonl"],
    descending: bool = True,
    fs_options: dict[str, Any] = {},
) -> list[EvalLogInfo]:
    """List all eval logs in a directory.

    Args:
      log_dir (str): Log directory (defaults to INSPECT_LOG_DIR)
      filter (Callable[[EvalLog], bool]): Filter to limit logs returned.
         Note that the EvalLog instance passed to the filter has only
         the EvalLog header (i.e. does not have the samples or logging output).
      recursive (bool): List log files recursively (defaults to True).

      extensions (list[str]): File extension to scan for logs
      descending (bool): List in descening order.
      fs_options (dict[str, Any]): Optional. Addional arguments to pass through
          to the filesystem provider (e.g. `S3FileSystem`).

    Returns:
       List of EvalLog Info.

    """
    # get the eval logs
    fs = filesystem(log_dir, fs_options)
    if fs.exists(log_dir):
        eval_logs = log_files_from_ls(
            fs.ls(log_dir, recursive=recursive), extensions, descending
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


def write_eval_log(log: EvalLog, log_file: str) -> None:
    """Write an evaluation log.

    Args:
       log (EvalLog): Evaluation log to write.
       log_file (str): Location to write log to.

    """
    with file(log_file, "w") as f:
        f.write(eval_log_json(log))


def eval_log_json(log: EvalLog) -> str:
    return log.model_dump_json(exclude_none=True, exclude_defaults=False, indent=2)


def read_eval_log(log_file: str, header_only: bool = False) -> EvalLog:
    """Read an evaluation log.

    Args:
       log_file (str): Log file to read.
       header_only (bool): Read only the header (i.e. exclude
         the "samples" and "logging" fields). Defaults to False.

    Returns:
       EvalLog object read from file.
    """
    with file(log_file, "r") as f:
        # header-only uses json-stream
        if header_only:
            data = json_stream.load(f, persistent=True)

            def read_field(field: str) -> Any:
                if field in data.keys():
                    return json_stream.to_standard_types(data[field])
                else:
                    return None

            results = read_field("results")
            error = read_field("error")

            return EvalLog(
                version=read_field("version"),
                status=read_field("status"),
                eval=EvalSpec(**read_field("eval")),
                plan=EvalPlan(**read_field("plan")),
                results=EvalResults(**results) if results else None,
                stats=EvalStats(**read_field("stats")),
                error=EvalError(**error) if error else None,
            )

        # otherwise normal json parse
        else:
            raw_data = json.load(f)
            log = EvalLog(**raw_data)
            if log.version > 1:
                raise ValueError(f"Unable to read version {log.version} of log format.")
            return log


class FileRecorder(Recorder):
    def __init__(
        self, log_dir: str, suffix: str, fs_options: dict[str, Any] = {}
    ) -> None:
        super().__init__()
        self.log_dir = log_dir
        self.fs = filesystem(log_dir, fs_options)
        self.fs.mkdir(self.log_dir, exist_ok=True)
        self.suffix = suffix

    def latest_log_file_path(self) -> str:
        log_files = self.fs.ls(self.log_dir)
        sorted_log_files = log_files_from_ls(log_files, [self.suffix])
        if len(sorted_log_files) > 0:
            log_file = sorted_log_files[0].name
            # return as relative if the fs_scheme is a local relative path
            fs_scheme = urlparse(self.log_dir).scheme
            if not fs_scheme and not os.path.isabs(self.log_dir):
                log_dir_abs = Path(self.log_dir).parent.absolute().as_uri()
                log_file = log_file.replace(log_dir_abs, ".")
            return log_file
        else:
            raise FileNotFoundError("No evaluation logs found in in output_dir")

    def _log_file_key(self, eval: EvalSpec) -> str:
        # clean underscores, slashes, and : from the log file key (so we can reliably parse it
        # later without worrying about underscores)
        def clean(s: str) -> str:
            return s.replace("_", "-").replace("/", "-").replace(":", "-")

        return f"{clean(eval.created)}_{clean(eval.task)}_{clean(eval.task_id)}"

    def _log_file_path(self, eval: EvalSpec) -> str:
        return f"{self.log_dir}{self.fs.sep}{self._log_file_key(eval)}{self.suffix}"


def log_files_from_ls(
    ls: list[FileInfo],
    extensions: list[str] = [".json", ".jsonl"],
    descending: bool = True,
) -> list[EvalLogInfo]:
    return [
        log_file_info(file)
        for file in sorted(ls, key=lambda file: file.mtime, reverse=descending)
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


class JSONRecorder(FileRecorder):
    class JSONLogFile(BaseModel):
        file: str
        data: EvalLog
        events: int = Field(default=0)

    def __init__(self, log_dir: str, write_freq: int = 100):
        # call super
        super().__init__(log_dir, ".json")

        # flush to file every write_freq events
        self.write_freq = write_freq

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, JSONRecorder.JSONLogFile] = {}

    def log_start(self, eval: EvalSpec) -> str:
        # initialize file log for this eval
        file = self._log_file_path(eval)
        self.data[self._log_file_key(eval)] = JSONRecorder.JSONLogFile(
            file=file,
            data=EvalLog(eval=eval),
            events=0,
        )
        return file

    def log_event(
        self,
        spec: EvalSpec,
        type: LogEvent,
        data: EvalPlan | EvalSample | EvalResults | LoggingMessage,
    ) -> None:
        log = self.data[self._log_file_key(spec)]
        if type == "plan":
            log.data.plan = cast(EvalPlan, data)
        elif type == "sample":
            if log.data.samples is None:
                log.data.samples = []
            log.data.samples.append(cast(EvalSample, data))
        elif type == "logging":
            log.data.logging.append(cast(LoggingMessage, data))
        elif type == "results":
            log.data.results = cast(EvalResults, data)
        else:
            raise ValueError(f"Unknown event {type}")
        # check if we need to flush
        if log.events >= self.write_freq:
            self.write_log(log.file, log.data)
            log.events = 0
        log.events += 1

    def log_success(
        self,
        spec: EvalSpec,
        stats: EvalStats,
    ) -> EvalLog:
        log = self.data[self._log_file_key(spec)]
        log.data.status = "success"
        log.data.stats = stats
        return self._log_finish(spec, log)

    def log_failure(
        self, spec: EvalSpec, stats: EvalStats, error: EvalError
    ) -> EvalLog:
        log = self.data[self._log_file_key(spec)]
        log.data.status = "error"
        log.data.stats = stats
        log.data.error = error
        return self._log_finish(spec, log)

    def read_log(self, location: str) -> EvalLog:
        return read_eval_log(location)

    def write_log(self, location: str, log: EvalLog) -> None:
        write_eval_log(log, location)

    def read_latest_log(self) -> EvalLog:
        return self.read_log(self.latest_log_file_path())

    def _log_finish(self, spec: EvalSpec, log: JSONLogFile) -> EvalLog:
        self.write_log(log.file, log.data)
        del self.data[self._log_file_key(spec)]
        return log.data
