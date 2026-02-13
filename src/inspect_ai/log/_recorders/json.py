from logging import getLogger
from typing import IO, Any, get_args

import ijson  # type: ignore
from ijson import IncompleteJSONError
from ijson.backends.python import UnexpectedSymbol  # type: ignore
from pydantic import BaseModel
from pydantic_core import from_json
from typing_extensions import override

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION, get_deserializing_context
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import FileSystem, absolute_file_path, file, filesystem
from inspect_ai._util.json import is_ijson_nan_inf_error
from inspect_ai._util.trace import trace_action

from .._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSpec,
    EvalStats,
    EvalStatus,
    sort_samples,
)
from .eval import _s3_bucket_and_key, _write_s3_conditional
from .file import FileRecorder

logger = getLogger(__name__)


class JSONRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".json")

    @override
    @classmethod
    def handles_bytes(cls, first_bytes: bytes) -> bool:
        return first_bytes[:1] == b"{"

    @override
    def default_log_buffer(self, sample_count: int, high_throughput: bool) -> int:
        if high_throughput:
            # High-throughput: flush ~10 times over the run
            return max(10, sample_count // 10)
        else:
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
        self,
        log_dir: str,
        suffix: str = ".json",
        fs_options: dict[str, Any] | None = None,
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
        eval: EvalSpec,
        status: EvalStatus,
        stats: EvalStats,
        results: EvalResults | None,
        reductions: list[EvalSampleReductions] | None,
        error: EvalError | None = None,
        header_only: bool = False,
        invalidated: bool = False,
    ) -> EvalLog:
        log = self.data[self._log_file_key(eval)]
        log.data.status = status
        log.data.stats = stats
        log.data.results = results
        log.data.invalidated = invalidated
        if error:
            log.data.error = error
        if reductions:
            log.data.reductions = reductions
        await self.write_log(log.file, log.data)
        log.data.location = log.file

        # stop tracking this data
        del self.data[self._log_file_key(eval)]

        # return the log
        return log.data

    @override
    async def flush(self, eval: EvalSpec) -> None:
        log = self.data[self._log_file_key(eval)]
        await self.write_log(log.file, log.data)

    @override
    @classmethod
    async def read_log(
        cls,
        location: str,
        header_only: bool = False,
        async_fs: AsyncFilesystem | None = None,
    ) -> EvalLog:
        fs = filesystem(location)

        if header_only:
            # Fast path: header only
            try:
                log = _read_header_streaming(location)
                if fs.is_s3():
                    file_info = fs.info(location)
                    log.etag = file_info.etag
                return log
            # The Python JSON serializer supports NaN and Inf, however
            # this isn't technically part of the JSON spec. The json-stream
            # library shares this limitation, so if we fail with an
            # invalid character (or Unexpected symbol) then we move on and and parse w/ pydantic
            # (which does support NaN and Inf by default)
            except (ValueError, IncompleteJSONError, UnexpectedSymbol) as ex:
                if is_ijson_nan_inf_error(ex):
                    pass
                else:
                    raise ValueError(f"Unable to read log file: {location}") from ex

        # full reads (and fallback to streaming reads if they encounter invalid json characters)
        if fs.is_s3():
            # read content and get ETag such that they always match
            content, etag = await _s3_read_with_etag(location, fs)
            raw_data = from_json(content)
        else:
            with file(location, "r") as f:
                raw_data = from_json(f.read())
            etag = None

        log = _parse_json_log(raw_data, header_only)
        log.location = location
        if etag:
            log.etag = etag

        return log

    @override
    @classmethod
    async def read_log_bytes(
        cls, log_bytes: IO[bytes], header_only: bool = False
    ) -> EvalLog:
        return _parse_json_log(from_json(log_bytes.read()), header_only)

    @override
    @classmethod
    async def write_log(
        cls, location: str, log: EvalLog, if_match_etag: str | None = None
    ) -> None:
        from inspect_ai.log._file import eval_log_json

        # sort samples before writing as they can come in out of order
        if log.samples:
            sort_samples(log.samples)

        fs = filesystem(location)
        if fs.is_s3() and if_match_etag:
            # Use S3 conditional write
            await cls._write_log_s3_conditional(location, log, if_match_etag, fs)
        else:
            # Standard write
            # get log as bytes
            log_bytes = eval_log_json(log)

            with trace_action(logger, "Log Write", location):
                with file(location, "wb") as f:
                    f.write(log_bytes)

    @classmethod
    async def _write_log_s3_conditional(
        cls, location: str, log: EvalLog, etag: str, fs: FileSystem
    ) -> None:
        """Perform S3 conditional write using aioboto3."""
        from inspect_ai.log._file import eval_log_json

        bucket, key = _s3_bucket_and_key(location)

        # get log as bytes
        log_bytes = eval_log_json(log)

        await _write_s3_conditional(fs, bucket, key, log_bytes, etag, location, logger)


def _validate_version(ver: int) -> None:
    if ver > LOG_SCHEMA_VERSION:
        raise ValueError(f"Unable to read version {ver} of log format.")


def _parse_json_log(raw_data: Any, header_only: bool) -> EvalLog:
    """Parse raw JSON data into an EvalLog, validating version and pruning if header_only."""
    log = EvalLog.model_validate(raw_data, context=get_deserializing_context())

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

    return log


async def _s3_read_with_etag(location: str, fs: FileSystem) -> tuple[str, str]:
    """
    Read S3 file content and get ETag in a single operation.

    Returns:
        (content, etag) - etag is guaranteed to match content
    """
    import aioboto3

    bucket, key = _s3_bucket_and_key(location)

    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=fs.fs.client_kwargs.get("endpoint_url"),
        region_name=fs.fs.client_kwargs.get("region_name"),
    ) as s3_client:
        response = await s3_client.get_object(Bucket=bucket, Key=key)
        content = await response["Body"].read()
        content = content.decode("utf-8")
        etag = response["ETag"].strip('"')  # S3 returns ETag with quotes

    return content, etag


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
        invalidated = False
        status: EvalStatus | None = None
        eval: EvalSpec | None = None
        plan: EvalPlan | None = None
        results: EvalResults | None = None
        stats: EvalStats | None = None
        error: EvalError | None = None
        for k, v in ijson.kvitems(f, ""):
            if k == "status":
                assert v in get_args(EvalStatus)
                status = v
            elif k == "invalidated":
                invalidated = v
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
        invalidated=invalidated,
        version=version,
        error=error if has_error else None,
        location=log_file,
    )
