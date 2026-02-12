import json
import logging
import math
import os
import tempfile
from logging import getLogger
from typing import IO, Any, BinaryIO, Iterable, cast
from zipfile import ZipFile

import anyio
from pydantic import BaseModel, Field
from typing_extensions import override

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION, get_deserializing_context
from inspect_ai._util.error import EvalError, WriteConflictError
from inspect_ai._util.file import FileSystem, dirname, file, filesystem
from inspect_ai._util.json import is_ijson_nan_inf_error, to_json_safe
from inspect_ai._util.trace import trace_action
from inspect_ai._util.zip_common import ZipEntry
from inspect_ai._util.zipfile import zipfile_compress_kwargs

from .._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalSpec,
    EvalStats,
    EvalStatus,
    sort_samples,
)
from .file import FileRecorder

logger = getLogger(__name__)


class LogStart(BaseModel):
    version: int
    eval: EvalSpec
    plan: EvalPlan


class LogResults(BaseModel):
    status: EvalStatus
    stats: EvalStats
    results: EvalResults | None = Field(default=None)
    error: EvalError | None = Field(default=None)


JOURNAL_DIR = "_journal"
SUMMARY_DIR = "summaries"
SAMPLES_DIR = "samples"

START_JSON = "start.json"
RESULTS_JSON = "results.json"
REDUCTIONS_JSON = "reductions.json"
SUMMARIES_JSON = "summaries.json"
HEADER_JSON = "header.json"


class EvalRecorder(FileRecorder):
    @override
    @classmethod
    def handles_location(cls, location: str) -> bool:
        return location.endswith(".eval")

    @override
    @classmethod
    def handles_bytes(cls, first_bytes: bytes) -> bool:
        return first_bytes == b"PK\x03\x04"  # ZIP local file header

    @override
    def default_log_buffer(self, sample_count: int) -> int:
        # .eval files are 5-8x smaller than .json files so we
        # are much less worried about flushing frequently
        # scale flushes in alignment with sample_count so small runs
        # flush more often (sample by sample) and large runs less often
        return max(1, min(math.floor(sample_count / 3), 10))

    def __init__(self, log_dir: str, fs_options: dict[str, Any] | None = None):
        super().__init__(log_dir, ".eval", fs_options)

        # each eval has a unique key (created from run_id and task name/version)
        # which we use to track the output path, accumulated data, and event counter
        self.data: dict[str, ZipLogFile] = {}

    @override
    async def log_init(
        self, eval: EvalSpec, location: str | None = None, *, clean: bool = False
    ) -> str:
        # if the file exists then read summaries
        if not clean and location is not None and self.fs.exists(location):
            with file(location, "rb") as f:
                with ZipFile(f, "r") as zip:
                    log_start = _read_start(zip)
                    summary_counter = _read_summary_counter(zip.namelist())
                    summaries = _read_all_summaries(zip, summary_counter)
        else:
            log_start = None
            summary_counter = 0
            summaries = []

        # create zip wrapper
        zip_file = location or self._log_file_path(eval)
        zip_log_file = ZipLogFile(file=zip_file)
        await zip_log_file.init(log_start, summary_counter, summaries)

        # track zip
        self.data[self._log_file_key(eval)] = zip_log_file

        # return file path
        return zip_file

    @override
    async def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        log = self.data[self._log_file_key(eval)]
        start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval, plan=plan)
        await log.start(start)

    @override
    async def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None:
        log = self.data[self._log_file_key(eval)]
        await log.buffer_sample(sample)

    @override
    async def flush(self, eval: EvalSpec) -> None:
        # get the zip log
        log = self.data[self._log_file_key(eval)]

        # write the buffered samples
        await log.write_buffered_samples()

        # flush to underlying stream
        await log.flush()

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
        # get the key and log
        key = self._log_file_key(eval)
        log = self.data[key]

        # write the buffered samples
        await log.write_buffered_samples()

        # write consolidated summaries
        await log.write(SUMMARIES_JSON, log._summaries)

        # write reductions
        if reductions is not None:
            await log.write(REDUCTIONS_JSON, reductions)

        # Get the results
        log_results = LogResults(
            status=status, stats=stats, results=results, error=error
        )

        # add the results to the original eval log from start.json
        log_start = log.log_start
        if log_start is None:
            raise RuntimeError("Log not properly initialised")

        eval_header = EvalLog(
            version=log_start.version,
            invalidated=invalidated,
            eval=log_start.eval,
            plan=log_start.plan,
            results=log_results.results,
            stats=log_results.stats,
            status=log_results.status,
            error=log_results.error,
        )
        await log.write(HEADER_JSON, eval_header)

        # flush and write the results
        await log.flush()
        result = await log.close(header_only)

        # stop tracking this eval
        del self.data[key]

        return result

    @classmethod
    @override
    async def read_log(
        cls,
        location: str,
        header_only: bool = False,
        async_fs: AsyncFilesystem | None = None,
    ) -> EvalLog:
        if async_fs is not None:
            return await cls._read_log_impl(location, header_only, async_fs)
        else:
            async with AsyncFilesystem() as owned_fs:
                return await cls._read_log_impl(location, header_only, owned_fs)

    @classmethod
    async def _read_log_impl(
        cls,
        location: str,
        header_only: bool,
        async_fs: AsyncFilesystem,
    ) -> EvalLog:
        # if the log is not stored in the local filesystem then download it first,
        # and then read it from a temp file (eliminates the possiblity of hundreds
        # of small fetches from the zip file streams)
        temp_log: str | None = None
        etag: str | None = None
        fs = filesystem(location)

        if not fs.is_local() and header_only is False:
            with tempfile.NamedTemporaryFile(delete=False) as temp:
                temp_log = temp.name
                if fs.is_s3():
                    # download file and get ETag so it matches the content
                    etag = await _s3_download_with_etag(location, temp_log, fs)
                else:
                    fs.get_file(location, temp_log)

        # read log (use temp_log if we have it)
        try:
            read_location = temp_log or location
            reader = AsyncZipReader(async_fs, read_location)
            cd = await reader.entries()
            log = await _read_log(reader, cd.entries, location, header_only)

            if etag is not None:
                log.etag = etag
            elif fs.is_s3() and header_only:
                # ETag is captured from the S3 response used to read the
                # central directory, so no extra request is needed.
                log.etag = reader.etag

            return log
        finally:
            if temp_log:
                os.unlink(temp_log)

    @override
    @classmethod
    async def read_log_bytes(
        cls, log_bytes: IO[bytes], header_only: bool = False
    ) -> EvalLog:
        return _read_log_from_bytes(log_bytes, location="", header_only=header_only)

    @override
    @classmethod
    async def read_log_sample(
        cls,
        location: str,
        id: str | int | None = None,
        epoch: int = 1,
        uuid: str | None = None,
        exclude_fields: set[str] | None = None,
    ) -> EvalSample:
        with file(location, "rb") as z:
            with ZipFile(z, mode="r") as zip:
                try:
                    # if a uuid was specified then read the summaries and find the matching sample
                    if id is None:
                        if uuid is None:
                            raise ValueError(
                                "You must specify an 'id' or 'uuid' to read"
                            )
                        summaries = _read_sample_summaries(zip)
                        sample = next(
                            (summary for summary in summaries if summary.uuid == uuid),
                            None,
                        )
                        if sample is None:
                            raise ValueError(
                                f"Sample with uuid '{uuid}' not found in log."
                            )
                        id = sample.id
                        epoch = sample.epoch

                    with zip.open(_sample_filename(id, epoch), "r") as f:
                        if exclude_fields:
                            # Use streaming JSON parser to skip large fields
                            # This significantly reduces memory usage for large samples
                            import ijson  # type: ignore
                            from ijson import IncompleteJSONError
                            from ijson.backends.python import (  # type: ignore[import-untyped]
                                UnexpectedSymbol,
                            )

                            try:
                                data: dict[str, Any] = {}
                                for key, value in ijson.kvitems(f, "", use_float=True):
                                    if key not in exclude_fields:
                                        data[key] = value
                            except (
                                ValueError,
                                IncompleteJSONError,
                                UnexpectedSymbol,
                            ) as ex:
                                # ijson doesn't support NaN/Inf which are valid in
                                # Python's JSON. Fall back to standard json.load
                                # and manually remove excluded fields.
                                if is_ijson_nan_inf_error(ex):
                                    f.seek(0)
                                    data = json.load(f)
                                    for field in exclude_fields:
                                        data.pop(field, None)
                                else:
                                    raise
                        else:
                            data = json.load(f)
                        return EvalSample.model_validate(
                            data, context=get_deserializing_context()
                        )
                except KeyError:
                    raise IndexError(
                        f"Sample id {id} for epoch {epoch} not found in log {location}"
                    )

    @classmethod
    @override
    async def read_log_sample_summaries(
        cls, location: str, async_fs: AsyncFilesystem | None = None
    ) -> list[EvalSampleSummary]:
        if async_fs is not None:
            return await cls._read_log_sample_summaries_impl(location, async_fs)
        else:
            async with AsyncFilesystem() as owned_fs:
                return await cls._read_log_sample_summaries_impl(location, owned_fs)

    @classmethod
    async def _read_log_sample_summaries_impl(
        cls, location: str, async_fs: AsyncFilesystem
    ) -> list[EvalSampleSummary]:
        reader = AsyncZipReader(async_fs, location)
        cd = await reader.entries()
        entry_names = [e.filename for e in cd.entries]
        summary_counter = _read_summary_counter(entry_names)
        return await _read_all_summaries_async(reader, summary_counter)

    @classmethod
    @override
    async def write_log(
        cls, location: str, log: EvalLog, if_match_etag: str | None = None
    ) -> None:
        fs = filesystem(location)
        if fs.is_s3() and if_match_etag:
            # Use S3 conditional write
            await cls._write_log_s3_conditional(location, log, if_match_etag, fs)
        else:
            # Standard write using the recorder (so we get all of the extra streams)
            await _write_eval_log_with_recorder(log, dirname(location), location)

    @classmethod
    async def _write_log_s3_conditional(
        cls, location: str, log: EvalLog, etag: str, fs: FileSystem
    ) -> None:
        """Perform S3 conditional write for .eval format using boto3."""
        import tempfile

        bucket, key = _s3_bucket_and_key(location)

        # create the eval log in a temporary directory first
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            # create a temporary eval file name
            temp_eval_file = os.path.join(tmpdir, "temp_log.eval")

            # write using the normal recorder to get proper .eval format
            await _write_eval_log_with_recorder(log, tmpdir, temp_eval_file)

            # read the created file in bytes
            with open(temp_eval_file, "rb") as f:
                log_bytes = f.read()

        await _write_s3_conditional(fs, bucket, key, log_bytes, etag, location, logger)


async def _write_eval_log_with_recorder(
    log: EvalLog, recorder_dir: str, output_file: str
) -> None:
    """Helper function to write EvalLog using EvalRecorder pattern."""
    recorder = EvalRecorder(recorder_dir)
    await recorder.log_init(log.eval, output_file, clean=True)
    await recorder.log_start(log.eval, log.plan)
    for sample in log.samples or []:
        await recorder.log_sample(log.eval, sample)
    await recorder.log_finish(
        log.eval,
        log.status,
        log.stats,
        log.results,
        log.reductions,
        log.error,
        invalidated=log.invalidated,
    )


def _s3_bucket_and_key(location: str) -> tuple[str, str]:
    """Extract S3 bucket and key from an S3 URL."""
    from urllib.parse import urlparse

    parsed = urlparse(location)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


async def _s3_conditional_put_object(
    fs: FileSystem, bucket: str, key: str, body: bytes, etag: str
) -> None:
    """Helper function to perform S3 conditional write with aioboto3."""
    import aioboto3

    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=fs.fs.client_kwargs.get("endpoint_url"),
        region_name=fs.fs.client_kwargs.get("region_name"),
    ) as s3_client:
        await s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            IfMatch=f'"{etag}"',  # S3 requires quotes around ETag
        )


async def _s3_download_with_etag(
    location: str, local_path: str, fs: FileSystem
) -> str | None:
    """
    Download S3 file and get its ETag in a single operation.

    Returns:
        ETag of the downloaded file (guaranteed to match the downloaded content)
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
        with open(local_path, "wb") as f:
            f.write(content)

        etag: str = response["ETag"]
        return etag.strip('"')  # S3 returns ETag with quotes


async def _write_s3_conditional(
    fs: FileSystem,
    bucket: str,
    key: str,
    body: bytes,
    etag: str,
    location: str,
    logger: logging.Logger,
) -> None:
    """Write to S3 with conditional check and error handling."""
    from botocore.exceptions import ClientError

    from inspect_ai._util.trace import trace_action

    with trace_action(logger, "Log Conditional Write", location):
        try:
            await _s3_conditional_put_object(fs, bucket, key, body, etag)
        except ClientError as e:
            if e.response["Error"]["Code"] == "PreconditionFailed":
                raise WriteConflictError(
                    f"Log file was modified by another process. Expected ETag: {etag}"
                )
            raise


def read_sample_summaries(zip: ZipFile) -> list[EvalSampleSummary]:
    summary_counter = _read_summary_counter(zip.namelist())
    summaries = _read_all_summaries(zip, summary_counter)
    return summaries


class ZipLogFile:
    _zip: ZipFile | None
    _temp_file: BinaryIO
    _fs: FileSystem

    def __init__(self, file: str) -> None:
        self._file = file
        self._zip = None
        self._fs = filesystem(file)
        self._lock = anyio.Lock()
        self._temp_file = tempfile.TemporaryFile()
        self._samples: list[EvalSample] = []
        self._summary_counter = 0
        self._summaries: list[EvalSampleSummary] = []
        self._log_start: LogStart | None = None

    async def init(
        self,
        log_start: LogStart | None,
        summary_counter: int,
        summaries: list[EvalSampleSummary],
    ) -> None:
        async with self._lock:
            self._open()
            self._summary_counter = summary_counter
            self._summaries = summaries
            self._log_start = log_start

    @property
    def log_start(self) -> LogStart | None:
        return self._log_start

    async def start(self, start: LogStart) -> None:
        async with self._lock:
            self._log_start = start
            self._zip_writestr(_journal_path(START_JSON), start)

    async def buffer_sample(self, sample: EvalSample) -> None:
        async with self._lock:
            self._samples.append(sample)

    async def write_buffered_samples(self) -> None:
        async with self._lock:
            # Write the buffered samples
            summaries: list[EvalSampleSummary] = []
            for sample in self._samples:
                # Write the sample
                self._zip_writestr(_sample_filename(sample.id, sample.epoch), sample)

                # Capture the summary
                summaries.append(sample.summary())

            self._samples.clear()

            # write intermediary summaries and add to master list
            if len(summaries) > 0:
                self._summary_counter += 1
                summary_file = _journal_summary_file(self._summary_counter)
                summary_path = _journal_summary_path(summary_file)
                self._zip_writestr(summary_path, summaries)
                self._summaries.extend(summaries)

    async def write(self, filename: str, data: Any) -> None:
        async with self._lock:
            self._zip_writestr(filename, data)

    async def flush(self) -> None:
        async with self._lock:
            # close the zip file so it is flushed
            if self._zip:
                self._zip.close()

            # read the temp_file (leaves pointer at end for subsequent appends)
            self._temp_file.seek(0)
            log_bytes = self._temp_file.read()

            with trace_action(logger, "Log Write", self._file):
                try:
                    with file(self._file, "wb") as f:
                        f.write(log_bytes)
                finally:
                    # re-open zip file w/ self.temp_file pointer at end
                    self._open()

    async def close(self, header_only: bool) -> EvalLog:
        async with self._lock:
            # read the log from the temp file then close it
            try:
                self._temp_file.seek(0)
                return _read_log_from_bytes(
                    self._temp_file, self._file, header_only=header_only
                )
            finally:
                self._temp_file.close()
                if self._zip:
                    self._zip.close()

    # cleanup zip file if we didn't in normal course
    def __del__(self) -> None:
        if self._zip:
            self._zip.close()

    def _open(self) -> None:
        self._zip = ZipFile(
            self._temp_file,
            mode="a",
            **zipfile_compress_kwargs,
        )

    # raw unsynchronized version of write
    def _zip_writestr(self, filename: str, data: Any) -> None:
        assert self._zip
        self._zip.writestr(
            filename,
            to_json_safe(data),
        )


async def _read_log(
    reader: AsyncZipReader,
    entries: list[ZipEntry],
    location: str,
    header_only: bool = False,
) -> EvalLog:
    entry_names = {e.filename for e in entries}

    eval_log = await _read_header_async(reader, entry_names, location)

    if REDUCTIONS_JSON in entry_names:
        data = await _read_member_json(reader, REDUCTIONS_JSON)
        reductions = [
            EvalSampleReductions.model_validate(
                reduction, context=get_deserializing_context()
            )
            for reduction in data
        ]
        if eval_log.results is not None:
            eval_log.reductions = reductions

    if not header_only:
        samples: list[EvalSample] = []
        for entry in entries:
            if entry.filename.startswith(f"{SAMPLES_DIR}/") and entry.filename.endswith(
                ".json"
            ):
                data = await _read_member_json(reader, entry.filename)
                samples.append(
                    EvalSample.model_validate(
                        data, context=get_deserializing_context()
                    ),
                )
        sort_samples(samples)
        eval_log.samples = samples

    return eval_log


def _read_log_from_bytes(
    log: IO[bytes], location: str, header_only: bool = False
) -> EvalLog:
    with ZipFile(log, mode="r") as zip:
        eval_log = _read_header(zip, location)
        if REDUCTIONS_JSON in zip.namelist():
            with zip.open(REDUCTIONS_JSON, "r") as f:
                reductions = [
                    EvalSampleReductions.model_validate(
                        reduction, context=get_deserializing_context()
                    )
                    for reduction in json.load(f)
                ]
                if eval_log.results is not None:
                    eval_log.reductions = reductions

        samples_list: list[EvalSample] | None = None
        if not header_only:
            samples_list = []
            for name in zip.namelist():
                if name.startswith(f"{SAMPLES_DIR}/") and name.endswith(".json"):
                    with zip.open(name, "r") as f:
                        samples_list.append(
                            EvalSample.model_validate(
                                json.load(f), context=get_deserializing_context()
                            ),
                        )
            sort_samples(samples_list)
            eval_log.samples = samples_list
        return eval_log


async def _read_member_json(reader: AsyncZipReader, member: str) -> Any:
    return json.loads(await reader.read_member_fully(member))


async def _read_header_async(
    reader: AsyncZipReader, entry_names: set[str], location: str
) -> EvalLog:
    if HEADER_JSON in entry_names:
        data = await _read_member_json(reader, HEADER_JSON)
        log = EvalLog.model_validate(data, context=get_deserializing_context())
        log.location = location
        return log
    else:
        data = await _read_member_json(reader, _journal_path(START_JSON))
        start = LogStart.model_validate(data, context=get_deserializing_context())
        return EvalLog(
            version=start.version,
            eval=start.eval,
            plan=start.plan,
            location=location,
        )


def _read_start(zip: ZipFile) -> LogStart | None:
    start_path = _journal_path(START_JSON)
    if start_path in zip.namelist():
        return cast(LogStart, _read_json(zip, start_path))
    else:
        return None


def _read_sample_summaries(zip: ZipFile) -> list[EvalSampleSummary]:
    summary_counter = _read_summary_counter(zip.namelist())
    summaries = _read_all_summaries(zip, summary_counter)
    return summaries


def _read_summary_counter(names: Iterable[str]) -> int:
    current_count = 0
    summary_prefix = _journal_summary_path()
    for name in names:
        if name.startswith(summary_prefix) and name.endswith(".json"):
            this_count = int(name.split("/")[-1].split(".")[0])
            current_count = max(this_count, current_count)
    return current_count


def _parse_summaries(data: Any, source: str) -> list[EvalSampleSummary]:
    if isinstance(data, list):
        return [
            EvalSampleSummary.model_validate(value, context=get_deserializing_context())
            for value in data
        ]
    else:
        raise ValueError(f"Expected a list of summaries when reading {source}")


def _read_all_summaries(zip: ZipFile, count: int) -> list[EvalSampleSummary]:
    if SUMMARIES_JSON in zip.namelist():
        return _parse_summaries(_read_json(zip, SUMMARIES_JSON), SUMMARIES_JSON)
    else:
        summaries: list[EvalSampleSummary] = []
        for i in range(1, count):
            summary_file = _journal_summary_file(i)
            summary_path = _journal_summary_path(summary_file)
            summaries.extend(
                _parse_summaries(_read_json(zip, summary_path), summary_file)
            )
        return summaries


async def _read_all_summaries_async(
    reader: AsyncZipReader, count: int
) -> list[EvalSampleSummary]:
    cd = await reader.entries()
    entry_names = {e.filename for e in cd.entries}
    if SUMMARIES_JSON in entry_names:
        return _parse_summaries(
            await _read_member_json(reader, SUMMARIES_JSON), SUMMARIES_JSON
        )
    else:
        summaries: list[EvalSampleSummary] = []
        for i in range(1, count + 1):
            summary_file = _journal_summary_file(i)
            summary_path = _journal_summary_path(summary_file)
            summaries.extend(
                _parse_summaries(
                    await _read_member_json(reader, summary_path), summary_file
                )
            )
        return summaries


def _read_header(zip: ZipFile, location: str) -> EvalLog:
    # first see if the header is here
    if HEADER_JSON in zip.namelist():
        with zip.open(HEADER_JSON, "r") as f:
            log = EvalLog.model_validate(
                json.load(f), context=get_deserializing_context()
            )
            log.location = location
            return log
    else:
        with zip.open(_journal_path(START_JSON), "r") as f:
            start = LogStart.model_validate(
                json.load(f), context=get_deserializing_context()
            )
        return EvalLog(
            version=start.version, eval=start.eval, plan=start.plan, location=location
        )


def _sample_filename(id: str | int, epoch: int) -> str:
    return f"{SAMPLES_DIR}/{id}_epoch_{epoch}.json"


def _read_json(zip: ZipFile, filename: str) -> Any:
    with zip.open(filename) as f:
        return json.load(f)


def _journal_path(file: str) -> str:
    return JOURNAL_DIR + "/" + file


def _journal_summary_path(file: str | None = None) -> str:
    if file is None:
        return _journal_path(SUMMARY_DIR)
    else:
        return f"{_journal_path(SUMMARY_DIR)}/{file}"


def _journal_summary_file(index: int) -> str:
    return f"{index}.json"
