from logging import getLogger
from typing import Any, Literal, get_args

import ijson  # type: ignore
from ijson import IncompleteJSONError
from ijson.backends.python import UnexpectedSymbol  # type: ignore
from pydantic import BaseModel
from pydantic_core import from_json
from typing_extensions import override

from inspect_ai._util.constants import DESERIALIZING_CONTEXT, LOG_SCHEMA_VERSION
from inspect_ai._util.error import ConcurrentModificationError, EvalError
from inspect_ai._util.file import absolute_file_path, file, filesystem
from inspect_ai._util.trace import trace_action

from .._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSpec,
    EvalStats,
    sort_samples,
)
from .file import FileRecorder

logger = getLogger(__name__)


class JSONRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".json")

    @override
    def default_log_buffer(self) -> int:
        # we write the entire file in one shot and the files can
        # get fairly large (> 100MB) so we are a bit more sparing
        # for remote filesystem writes
        if self.is_local():
            return 10
        else:
            return 100

    class JSONLogFile(BaseModel):
        file: str
        data: EvalLog

    def __init__(
        self, log_dir: str, suffix: str = ".json", fs_options: dict[str, Any] = {}
    ):
        # call super
        super().__init__(log_dir, suffix, fs_options)

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, JSONRecorder.JSONLogFile] = {}

    @override
    async def log_init(self, eval: EvalSpec, location: str | None = None) -> str:
        # initialize file log for this eval
        # compute an absolute path if it's a relative ref
        # (so that the writes go to the correct place even
        # if the working directory is switched for a task)
        file = location or absolute_file_path(self._log_file_path(eval))

        # compute an absolute path if it's a relative ref
        # (so that the writes go to the correct place even
        # if the working directory is switched for a task)
        self.data[self._log_file_key(eval)] = JSONRecorder.JSONLogFile(
            file=file, data=EvalLog(eval=eval)
        )

        # attempt to
        return file

    @override
    async def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        log = self.data[self._log_file_key(eval)]
        log.data.plan = plan

    @override
    async def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None:
        log = self.data[self._log_file_key(eval)]
        if log.data.samples is None:
            log.data.samples = []
        log.data.samples.append(sample)

    @override
    async def log_finish(
        self,
        spec: EvalSpec,
        status: Literal["started", "success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        reductions: list[EvalSampleReductions] | None,
        error: EvalError | None = None,
        header_only: bool = False,
    ) -> EvalLog:
        log = self.data[self._log_file_key(spec)]
        log.data.status = status
        log.data.stats = stats
        log.data.results = results
        if error:
            log.data.error = error
        if reductions:
            log.data.reductions = reductions
        await self.write_log(log.file, log.data)
        log.data.location = log.file

        # stop tracking this data
        del self.data[self._log_file_key(spec)]

        # return the log
        return log.data

    @override
    async def flush(self, eval: EvalSpec) -> None:
        log = self.data[self._log_file_key(eval)]
        await self.write_log(log.file, log.data)

    @override
    @classmethod
    async def read_log(
        cls, location: str, header_only: bool = False, include_etag: bool = False
    ) -> EvalLog | tuple[EvalLog, str | None]:
        if header_only and not include_etag:
            # Fast path: header only, no ETag needed
            try:
                return _read_header_streaming(location)
            # The Python JSON serializer supports NaN and Inf, however
            # this isn't technically part of the JSON spec. The json-stream
            # library shares this limitation, so if we fail with an
            # invalid character (or Unexpected symbol) then we move on and and parse w/ pydantic
            # (which does support NaN and Inf by default)
            except (ValueError, IncompleteJSONError, UnexpectedSymbol) as ex:
                if (
                    str(ex).find("Invalid JSON character") != -1
                    or str(ex).find("invalid char in json text") != -1
                    or str(ex).find("Unexpected symbol") != -1
                ):
                    pass
                else:
                    raise ValueError(f"Unable to read log file: {location}") from ex

        # Get ETag if requested and on S3
        etag = None
        if include_etag:
            fs = filesystem(location)
            if fs.is_s3():
                try:
                    file_info = fs.info(location)
                    etag = file_info.etag
                except Exception:
                    # If we can't get file info, proceed without ETag
                    pass

        # full reads (and fallback to streaing reads if they encounter invalid json characters)
        with file(location, "r") as f:
            # parse w/ pydantic
            raw_data = from_json(f.read())
            log = EvalLog.model_validate(raw_data, context=DESERIALIZING_CONTEXT)
            log.location = location

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
                    log.reductions = None

            # return log or log with etag
            if include_etag:
                return log, etag
            else:
                return log

    @override
    @classmethod
    async def write_log(
        cls, location: str, log: EvalLog, if_match_etag: str | None = None
    ) -> None:
        from inspect_ai.log._file import eval_log_json

        # Check if we should use S3 conditional write
        fs = filesystem(location)
        if fs.is_s3() and if_match_etag:
            # Use S3 conditional write
            await cls._write_log_s3_conditional(location, log, if_match_etag, fs)
        else:
            # Standard write
            # sort samples before writing as they can come in out of order
            if log.samples:
                sort_samples(log.samples)

            # get log as bytes
            log_bytes = eval_log_json(log)

            with trace_action(logger, "Log Write", location):
                with file(location, "wb") as f:
                    f.write(log_bytes)

    @classmethod
    async def _write_log_s3_conditional(
        cls, location: str, log: EvalLog, etag: str, fs: Any
    ) -> None:
        """Perform S3 conditional write using aioboto3."""
        from urllib.parse import urlparse

        from botocore.exceptions import ClientError

        from inspect_ai.log._file import eval_log_json

        # Parse S3 URL
        parsed = urlparse(location)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        # sort samples before writing as they can come in out of order
        if log.samples:
            sort_samples(log.samples)

        # get log as bytes
        log_bytes = eval_log_json(log)

        with trace_action(logger, "Log Conditional Write", location):
            try:
                # Create async S3 client with same configuration as filesystem
                import aioboto3

                session = aioboto3.Session()
                async with session.client(
                    "s3",
                    endpoint_url=fs.fs.client_kwargs.get("endpoint_url"),
                    aws_access_key_id=fs.fs.key,
                    aws_secret_access_key=fs.fs.secret,
                    region_name=fs.fs.client_kwargs.get("region_name"),
                ) as s3_client:
                    # Perform conditional write
                    await s3_client.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=log_bytes,
                        IfMatch=f'"{etag}"',  # S3 requires quotes around ETag
                    )
            except ClientError as e:
                if e.response["Error"]["Code"] == "PreconditionFailed":
                    raise ConcurrentModificationError(
                        f"Log file was modified by another process. Expected ETag: {etag}",
                        etag_expected=etag,
                    )
                raise


def _validate_version(ver: int) -> None:
    if ver > LOG_SCHEMA_VERSION:
        raise ValueError(f"Unable to read version {ver} of log format.")


def _read_header_streaming(log_file: str) -> EvalLog:
    with file(log_file, "rb") as f:
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
        status: Literal["started", "success", "cancelled", "error"] | None = None
        eval: EvalSpec | None = None
        plan: EvalPlan | None = None
        results: EvalResults | None = None
        stats: EvalStats | None = None
        error: EvalError | None = None
        for k, v in ijson.kvitems(f, ""):
            if k == "status":
                assert v in get_args(
                    Literal["started", "success", "cancelled", "error"]
                )
                status = v
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

    assert status, "Must encounter a 'status'"
    assert eval, "Must encounter a 'eval'"
    assert plan, "Must encounter a 'plan'"
    assert stats, "Must encounter a 'stats'"

    return EvalLog(
        eval=eval,
        plan=plan,
        results=results if has_results else None,
        stats=stats,
        status=status,
        version=version,
        error=error if has_error else None,
        location=log_file,
    )
