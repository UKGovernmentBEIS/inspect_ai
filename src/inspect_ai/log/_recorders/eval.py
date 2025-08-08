import json
import os
import tempfile
from logging import getLogger
from typing import Any, BinaryIO, Literal, cast
from zipfile import ZIP_DEFLATED, ZipFile

import anyio
from pydantic import BaseModel, Field
from pydantic_core import to_json
from typing_extensions import override

from inspect_ai._util.constants import DESERIALIZING_CONTEXT, LOG_SCHEMA_VERSION
from inspect_ai._util.error import ConcurrentModificationError, EvalError
from inspect_ai._util.file import FileSystem, dirname, file, filesystem
from inspect_ai._util.json import jsonable_python
from inspect_ai._util.trace import trace_action

from .._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalSpec,
    EvalStats,
    sort_samples,
)
from .file import FileRecorder

logger = getLogger(__name__)


class LogStart(BaseModel):
    version: int
    eval: EvalSpec
    plan: EvalPlan


class LogResults(BaseModel):
    status: Literal["started", "success", "cancelled", "error"]
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
    def default_log_buffer(self) -> int:
        # .eval files are 5-8x smaller than .json files so we
        # are much less worried about flushing frequently
        return 10

    def __init__(self, log_dir: str, fs_options: dict[str, Any] = {}):
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
                    summary_counter = _read_summary_counter(zip)
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
        status: Literal["started", "success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        reductions: list[EvalSampleReductions] | None,
        error: EvalError | None = None,
        header_only: bool = False,
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
            eval=log_start.eval,
            plan=log_start.plan,
            results=log_results.results,
            stats=log_results.stats,
            status=log_results.status,
            error=log_results.error,
        )
        await log.write(HEADER_JSON, eval_header)

        # stop tracking this eval
        del self.data[key]

        # flush and write the results
        await log.flush()
        return await log.close(header_only)

    @classmethod
    @override
    async def read_log(
        cls, location: str, header_only: bool = False, include_etag: bool = False
    ) -> EvalLog | tuple[EvalLog, str | None]:
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

        # if the log is not stored in the local filesystem then download it first,
        # and then read it from a temp file (eliminates the possiblity of hundreds
        # of small fetches from the zip file streams)
        temp_log: str | None = None
        fs = filesystem(location)
        if not fs.is_local() and header_only is False:
            with tempfile.NamedTemporaryFile(delete=False) as temp:
                temp_log = temp.name
                fs.get_file(location, temp_log)

        # read log (use temp_log if we have it)
        try:
            with file(temp_log or location, "rb") as z:
                log = _read_log(z, location, header_only)
                if include_etag:
                    return log, etag
                else:
                    return log
        finally:
            if temp_log:
                os.unlink(temp_log)

    @override
    @classmethod
    async def read_log_sample(
        cls,
        location: str,
        id: str | int | None = None,
        epoch: int = 1,
        uuid: str | None = None,
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
                        return EvalSample.model_validate(
                            json.load(f), context=DESERIALIZING_CONTEXT
                        )
                except KeyError:
                    raise IndexError(
                        f"Sample id {id} for epoch {epoch} not found in log {location}"
                    )

    @classmethod
    @override
    async def read_log_sample_summaries(cls, location: str) -> list[EvalSampleSummary]:
        with file(location, "rb") as z:
            with ZipFile(z, mode="r") as zip:
                summary_counter = _read_summary_counter(zip)
                summaries = _read_all_summaries(zip, summary_counter)
                return summaries

    @classmethod
    @override
    async def write_log(
        cls, location: str, log: EvalLog, if_match_etag: str | None = None
    ) -> None:
        # Check if we should use S3 conditional write
        fs = filesystem(location)
        if fs.is_s3() and if_match_etag:
            # Use S3 conditional write
            await cls._write_log_s3_conditional(location, log, if_match_etag, fs)
        else:
            # Standard write using the recorder (so we get all of the extra streams)
            recorder = EvalRecorder(dirname(location))
            await recorder.log_init(log.eval, location, clean=True)
            await recorder.log_start(log.eval, log.plan)
            for sample in log.samples or []:
                await recorder.log_sample(log.eval, sample)
            await recorder.log_finish(
                log.eval, log.status, log.stats, log.results, log.reductions, log.error
            )

    @classmethod
    async def _write_log_s3_conditional(
        cls, location: str, log: EvalLog, etag: str, fs: Any
    ) -> None:
        """Perform S3 conditional write for .eval format using boto3."""
        import tempfile
        from urllib.parse import urlparse

        from botocore.exceptions import ClientError

        # Parse S3 URL
        parsed = urlparse(location)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        # Create the eval log in a temporary directory first
        import os

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a temporary eval file name
            temp_eval_file = os.path.join(temp_dir, "temp_log.eval")

            # Write using the normal recorder to get proper .eval format
            temp_recorder = EvalRecorder(temp_dir)
            await temp_recorder.log_init(log.eval, temp_eval_file, clean=True)
            await temp_recorder.log_start(log.eval, log.plan)
            for sample in log.samples or []:
                await temp_recorder.log_sample(log.eval, sample)
            await temp_recorder.log_finish(
                log.eval, log.status, log.stats, log.results, log.reductions, log.error
            )

            # Read the created file as bytes
            with open(temp_eval_file, "rb") as f:
                log_bytes = f.read()

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


def read_sample_summaries(zip: ZipFile) -> list[EvalSampleSummary]:
    summary_counter = _read_summary_counter(zip)
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
                return _read_log(self._temp_file, self._file, header_only=header_only)
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
            compression=ZIP_DEFLATED,
            compresslevel=5,
        )

    # raw unsynchronized version of write
    def _zip_writestr(self, filename: str, data: Any) -> None:
        assert self._zip
        self._zip.writestr(
            filename,
            to_json(
                value=jsonable_python(data),
                indent=2,
                exclude_none=True,
                fallback=lambda _x: None,
            ),
        )


def _read_log(log: BinaryIO, location: str, header_only: bool = False) -> EvalLog:
    with ZipFile(log, mode="r") as zip:
        evalLog = _read_header(zip, location)
        if REDUCTIONS_JSON in zip.namelist():
            with zip.open(REDUCTIONS_JSON, "r") as f:
                reductions = [
                    EvalSampleReductions.model_validate(
                        reduction, context=DESERIALIZING_CONTEXT
                    )
                    for reduction in json.load(f)
                ]
                if evalLog.results is not None:
                    evalLog.reductions = reductions

        samples: list[EvalSample] | None = None
        if not header_only:
            samples = []
            for name in zip.namelist():
                if name.startswith(f"{SAMPLES_DIR}/") and name.endswith(".json"):
                    with zip.open(name, "r") as f:
                        samples.append(
                            EvalSample.model_validate(
                                json.load(f), context=DESERIALIZING_CONTEXT
                            ),
                        )
            sort_samples(samples)
            evalLog.samples = samples
        return evalLog


def _read_start(zip: ZipFile) -> LogStart | None:
    start_path = _journal_path(START_JSON)
    if start_path in zip.namelist():
        return cast(LogStart, _read_json(zip, start_path))
    else:
        return None


def _read_sample_summaries(zip: ZipFile) -> list[EvalSampleSummary]:
    summary_counter = _read_summary_counter(zip)
    summaries = _read_all_summaries(zip, summary_counter)
    return summaries


def _read_summary_counter(zip: ZipFile) -> int:
    current_count = 0
    for name in zip.namelist():
        if name.startswith(_journal_summary_path()) and name.endswith(".json"):
            this_count = int(name.split("/")[-1].split(".")[0])
            current_count = max(this_count, current_count)
    return current_count


def _read_all_summaries(zip: ZipFile, count: int) -> list[EvalSampleSummary]:
    if SUMMARIES_JSON in zip.namelist():
        summaries_raw = _read_json(zip, SUMMARIES_JSON)
        if isinstance(summaries_raw, list):
            return [
                EvalSampleSummary.model_validate(value, context=DESERIALIZING_CONTEXT)
                for value in summaries_raw
            ]
        else:
            raise ValueError(
                f"Expected a list of summaries when reading {SUMMARIES_JSON}"
            )
    else:
        summaries: list[EvalSampleSummary] = []
        for i in range(1, count):
            summary_file = _journal_summary_file(i)
            summary_path = _journal_summary_path(summary_file)
            summary = _read_json(zip, summary_path)
            if isinstance(summary, list):
                summaries.extend(
                    [
                        EvalSampleSummary.model_validate(
                            value, context=DESERIALIZING_CONTEXT
                        )
                        for value in summary
                    ]
                )
            else:
                raise ValueError(
                    f"Expected a list of summaries when reading {summary_file}"
                )
        return summaries


def _read_header(zip: ZipFile, location: str) -> EvalLog:
    # first see if the header is here
    if HEADER_JSON in zip.namelist():
        with zip.open(HEADER_JSON, "r") as f:
            log = EvalLog.model_validate(json.load(f), context=DESERIALIZING_CONTEXT)
            log.location = location
            return log
    else:
        with zip.open(_journal_path(START_JSON), "r") as f:
            start = LogStart.model_validate(json.load(f), context=DESERIALIZING_CONTEXT)
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
