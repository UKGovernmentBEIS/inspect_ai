import os
import re
from typing import Any, Callable, Literal, cast, get_args

import ijson  # type: ignore
from ijson import IncompleteJSONError
from pydantic import BaseModel
from pydantic_core import from_json, to_json
from typing_extensions import override

from inspect_ai._util.constants import ALL_LOG_FORMATS
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import (
    FileInfo,
    absolute_file_path,
    file,
    filesystem,
)

from ._log import EvalLog, EvalPlan, EvalResults, EvalSample, EvalSpec, EvalStats
from ._recorder import Recorder

LOG_SCHEMA_VERSION = 2


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
    # resolve extensions
    extensions = [f".{format}" for format in (formats or ALL_LOG_FORMATS)]

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


class FileRecorder(Recorder):
    def __init__(
        self, log_dir: str, suffix: str, fs_options: dict[str, Any] = {}
    ) -> None:
        self.log_dir = log_dir
        self.fs = filesystem(log_dir, fs_options)
        self.fs.mkdir(self.log_dir, exist_ok=True)
        self.suffix = suffix

    def is_local(self) -> bool:
        return self.fs.is_local()

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
    formats: list[str] = ALL_LOG_FORMATS,
    descending: bool = True,
) -> list[EvalLogInfo]:
    extensions = [f".{format}" for format in formats]
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


class JSONRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".json")

    class JSONLogFile(BaseModel):
        file: str
        data: EvalLog

    def __init__(self, log_dir: str, suffix: str = ".json"):
        # call super
        super().__init__(log_dir, suffix)

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, JSONRecorder.JSONLogFile] = {}

    def log_init(self, eval: EvalSpec) -> str:
        # initialize file log for this eval
        # compute an absolute path if it's a relative ref
        # (so that the writes go to the correct place even
        # if the working directory is switched for a task)
        file = absolute_file_path(self._log_file_path(eval))

        # compute an absolute path if it's a relative ref
        # (so that the writes go to the correct place even
        # if the working directory is switched for a task)
        self.data[self._log_file_key(eval)] = JSONRecorder.JSONLogFile(
            file=file, data=EvalLog(eval=eval)
        )

        # attempt to
        return file

    @override
    def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        log = self.data[self._log_file_key(eval)]
        log.data.plan = plan

    @override
    def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None:
        log = self.data[self._log_file_key(eval)]
        if log.data.samples is None:
            log.data.samples = []
        log.data.samples.append(sample)

    @override
    def log_finish(
        self,
        spec: EvalSpec,
        status: Literal["started", "success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        error: EvalError | None = None,
    ) -> EvalLog:
        log = self.data[self._log_file_key(spec)]
        log.data.status = status
        log.data.stats = stats
        log.data.results = results
        if error:
            log.data.error = error
        self.write_log(log.file, log.data)

        # stop tracking this data
        del self.data[self._log_file_key(spec)]

        # return the log
        return log.data

    @override
    def flush(self, eval: EvalSpec) -> None:
        log = self.data[self._log_file_key(eval)]
        self.write_log(log.file, log.data)

    @override
    @classmethod
    def read_log(cls, location: str, header_only: bool = False) -> EvalLog:
        if header_only:
            try:
                return _read_header_streaming(location)
            # The Python JSON serializer supports NaN and Inf, however
            # this isn't technically part of the JSON spec. The json-stream
            # library shares this limitation, so if we fail with an
            # invalid character then we move on and and parse w/ pydantic
            # (which does support NaN and Inf by default)
            except (ValueError, IncompleteJSONError) as ex:
                if (
                    str(ex).find("Invalid JSON character") != -1
                    or str(ex).find("invalid char in json text") != -1
                ):
                    pass
                else:
                    raise ValueError(f"Unable to read log file: {location}") from ex

        # parse full log (also used as a fallback for header_only encountering NaN or Inf)
        with file(location, "r") as f:
            # parse w/ pydantic
            raw_data = from_json(f.read())
            log = EvalLog(**raw_data)

            # fail for unknown version
            _validate_version(log.version)

            # set the version to the schema version we'll be returning
            log.version = LOG_SCHEMA_VERSION

            # prune if header_only
            if header_only:
                # exclude samples
                log.samples = None

                # prune sample reductions
                if log.results is not None:
                    log.results.sample_reductions = None

            # return log
            return log

    @override
    @classmethod
    def write_log(cls, location: str, log: EvalLog) -> None:
        # sort samples before writing as they can come in out of order
        # (convert into string zfilled so order is preserved)
        if log.samples:
            log.samples.sort(
                key=lambda sample: (
                    sample.epoch,
                    (
                        sample.id
                        if isinstance(sample.id, str)
                        else str(sample.id).zfill(20)
                    ),
                )
            )

        with file(location, "w") as f:
            f.write(eval_log_json(log))


class EvalRecorder(JSONRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".eval")

    @override
    def __init__(self, log_dir: str):
        super().__init__(log_dir, ".eval")


def _validate_version(ver: int) -> None:
    if ver > LOG_SCHEMA_VERSION:
        raise ValueError(f"Unable to read version {ver} of log format.")


def _read_header_streaming(log_file: str) -> EvalLog:
    with file(log_file, "r") as f:
        # Do low-level parsing to get the version number and also
        # detect the presence of results or error sections
        version: int | None = None
        has_results = False
        has_error = False

        for prefix, event, value in ijson.parse(f):
            if (prefix, event) == ("version", "number"):
                version = value
            elif (prefix, event) == ("results", "start_map"):
                has_results = True
            elif (prefix, event) == ("error", "start_map"):
                has_error = True
            elif prefix == "samples":
                # Break as soon as we hit samples as that can be very large
                break

        if version is None:
            raise ValueError("Unable to read version of log format.")

        _validate_version(version)
        version = LOG_SCHEMA_VERSION

        # Rewind the file to the beginning to re-parse the contents of fields
        f.seek(0)

        # Parse the log file, stopping before parsing samples
        for k, v in ijson.kvitems(f, ""):
            if k == "status":
                assert v in get_args(
                    Literal["started", "success", "cancelled", "error"]
                )
                status: Literal["started", "success", "cancelled", "error"] = v
            if k == "eval":
                eval = EvalSpec(**v)
            elif k == "plan":
                plan = EvalPlan(**v)
            elif k == "results":
                results = EvalResults(**v)
            elif k == "stats":
                stats = EvalStats(**v)
                if not has_error:
                    # Exit before parsing samples
                    break
            elif k == "error":
                error = EvalError(**v)
                break

    return EvalLog(
        eval=eval,
        plan=plan,
        results=results if has_results else None,
        stats=stats,
        status=status,
        version=version,
        error=error if has_error else None,
    )


def eval_log_json(log: EvalLog) -> str:
    # serialize to json (ignore values that are unserializable)
    # these values often result from solvers using metadata to
    # pass around 'live' objects -- this is fine to do and we
    # don't want to prevent it at the serialization level
    return to_json(
        value=log, indent=2, exclude_none=True, fallback=lambda _x: None
    ).decode()


_recorders: dict[str, type[Recorder]] = {"eval": EvalRecorder, "json": JSONRecorder}


def create_recorder_for_format(
    format: Literal["eval", "json"], *args: Any, **kwargs: Any
) -> Recorder:
    recorder = recorder_type_for_format(format)
    return recorder(*args, **kwargs)


def recorder_type_for_format(format: Literal["eval", "json"]) -> type[Recorder]:
    recorder = _recorders.get(format, None)
    if recorder:
        return recorder
    else:
        raise ValueError(f"No recorder for format: {format}")


def create_recorder_for_log_dir(log_dir: str) -> Recorder:
    recorder = recorder_type_for_location(log_dir)
    return cast(Callable[[str], Recorder], recorder)(log_dir)


def recorder_type_for_location(location: str) -> type[Recorder]:
    for recorder in _recorders.values():
        if recorder.handles_location(location):
            return recorder

    raise ValueError(f"No recorder for location: {location}")
