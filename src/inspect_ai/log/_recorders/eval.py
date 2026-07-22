import copy
import json
import logging
import math
import os
import shutil
import tempfile
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from functools import partial
from io import BytesIO
from logging import getLogger
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    BinaryIO,
    Generic,
    Iterator,
    NamedTuple,
    SupportsIndex,
    TypeVar,
    cast,
    overload,
)
from zipfile import ZipFile

import anyio
from pydantic import BaseModel, Field, JsonValue
from typing_extensions import override

from inspect_ai._util._async import tg_collect
from inspect_ai._util.async_bytes_reader import adapt_to_reader
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.atomic_write import atomic_write
from inspect_ai._util.constants import (
    LOG_SCHEMA_VERSION,
    get_deserializing_context,
)
from inspect_ai._util.error import EvalError, WriteConflictError
from inspect_ai._util.file import FileSystem, dirname, file, filesystem, local_path
from inspect_ai._util.json import (
    is_ijson_int_overflow_error,
    is_ijson_nan_inf_error,
    jsonable_dict,
    to_json_safe,
)
from inspect_ai._util.trace import trace_action
from inspect_ai._util.zip_common import ZipEntry
from inspect_ai._util.zipfile import zipfile_compress_kwargs

from .._condense import ATTACHMENT_PROTOCOL, condense_sample
from .._config_update import ConfigUpdate
from .._edit import LogUpdate
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
    EventsData,
    sort_samples,
)
from .._resolve import rebind_sample_timelines, resolve_sample_events_data
from .file import FileRecorder, write_local_snapshot

logger = getLogger(__name__)

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.history import SampleHistory


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
CONFIG_UPDATES_DIR = "config_updates"
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
    def default_log_buffer(self, sample_count: int, high_throughput: bool) -> int:
        if high_throughput:
            # High-throughput: flush ~20 times over the run
            return max(10, sample_count // 20)
        else:
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
            async with AsyncFilesystem() as fs:
                reader = AsyncZipReader(fs, location)
                log_start = await _read_start_async(reader)
                summaries, summary_counter = await _read_all_summaries_async(reader)
                (
                    config_updates,
                    config_update_counter,
                ) = await _read_config_updates_async(reader)
        else:
            log_start = None
            summary_counter = 0
            summaries = []
            config_updates = []
            config_update_counter = 0

        # create zip wrapper
        zip_file = location or self._log_file_path(eval)
        zip_log_file = ZipLogFile(file=zip_file)
        await zip_log_file.init(
            log_start,
            summary_counter,
            summaries,
            config_update_counter,
            config_updates,
        )

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
    async def log_sample_streaming(
        self, eval: EvalSpec, sample: EvalSample, history: "SampleHistory"
    ) -> None:
        log = self.data[self._log_file_key(eval)]
        await log.buffer_sample_streaming(sample, history)

    @override
    async def sample_summaries(self, eval: EvalSpec) -> list[EvalSampleSummary] | None:
        log = self.data.get(self._log_file_key(eval))
        if log is None:
            return None
        return await log.sample_summaries()

    @override
    async def buffered_sample(
        self, eval: EvalSpec, id: str | int, epoch: int
    ) -> EvalSample | None:
        log = self.data.get(self._log_file_key(eval))
        if log is None:
            return None
        return await log.buffered_sample(id, epoch)

    @override
    async def log_config_update(self, eval: EvalSpec, update: ConfigUpdate) -> None:
        log = self.data[self._log_file_key(eval)]
        await log.record_config_update(update)
        # push the journal entry out to the destination log now rather than
        # waiting for the sample-flush cadence — updates are rare (a handful
        # per run) and the record should survive a crash from this point on.
        # Skip when start.json hasn't been written yet (an inherited snapshot
        # recorded at logger init): a zip without start.json isn't readable
        # as an in-progress log, and log_start's own flush follows shortly.
        if log.log_start is not None:
            await log.flush(fsync=False)

    @override
    async def flush(self, eval: EvalSpec) -> None:
        # get the zip log
        log = self.data[self._log_file_key(eval)]

        # write the buffered samples
        await log.write_buffered_samples()

        # flush to underlying stream (intermediate snapshot: skip fsync)
        await log.flush(fsync=False)

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
        log_updates: list[LogUpdate] | None = None,
        config_updates: list[ConfigUpdate] | None = None,
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

        # consolidate config updates: a caller-supplied list (a full-log
        # rewrite / stream copy, whose in-memory log is authoritative and may
        # equal what log_init seeded from the existing file) wins outright —
        # merging would duplicate; otherwise the mid-run journaled ones
        all_config_updates = (
            config_updates if config_updates is not None else log.config_updates
        )

        eval_header = EvalLog(
            version=log_start.version,
            invalidated=invalidated,
            log_updates=log_updates,
            config_updates=all_config_updates or None,
            eval=log_start.eval,
            plan=log_start.plan,
            results=log_results.results,
            stats=log_results.stats,
            status=log_results.status,
            error=log_results.error,
        )
        await log.write(HEADER_JSON, eval_header)

        # flush and write the results (final write: make it crash-durable)
        await log.flush(fsync=True)
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
        exclude_fields: set[str] | None = None,
    ) -> EvalLog:
        async with AsyncFilesystem() as async_fs:
            # if the log is not stored in the local filesystem then download it
            # first, and then read it from a temp file (eliminates the possiblity
            # of hundreds of small fetches from the zip file streams)
            temp_log: str | None = None
            etag: str | None = None
            fs = filesystem(location)

            if not fs.is_local() and header_only is False:
                with tempfile.NamedTemporaryFile(delete=False) as temp:
                    temp_log = temp.name
                    if fs.is_s3():
                        # download file and get ETag so it matches the content
                        etag = await _s3_download_with_etag(
                            location, temp_log, async_fs
                        )
                    else:
                        fs.get_file(location, temp_log)

            # read log (use temp_log if we have it)
            try:
                read_location = temp_log or location
                reader = AsyncZipReader(async_fs, read_location)
                cd = await reader.entries()
                log = await _read_log(
                    reader, cd.entries, location, header_only, exclude_fields
                )

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
        reader: AsyncZipReader | None = None,
    ) -> EvalSample:
        if not reader:
            async with AsyncFilesystem() as fs:
                reader = AsyncZipReader(fs, location)
                return await cls._read_log_sample_impl(
                    reader, location, id, epoch, uuid, exclude_fields
                )
        return await cls._read_log_sample_impl(
            reader, location, id, epoch, uuid, exclude_fields
        )

    @classmethod
    async def _read_log_sample_impl(
        cls,
        reader: AsyncZipReader,
        location: str,
        id: str | int | None = None,
        epoch: int = 1,
        uuid: str | None = None,
        exclude_fields: set[str] | None = None,
    ) -> EvalSample:
        try:
            # if a uuid was specified then read the summaries and find the matching sample
            if id is None:
                if uuid is None:
                    raise ValueError("You must specify an 'id' or 'uuid' to read")
                summaries, _ = await _read_all_summaries_async(reader)
                sample = next(
                    (summary for summary in summaries if summary.uuid == uuid),
                    None,
                )
                if sample is None:
                    raise ValueError(f"Sample with uuid '{uuid}' not found in log.")
                id = sample.id
                epoch = sample.epoch

            if exclude_fields:
                data = await _read_member_json_excluding(
                    reader,
                    _sample_filename(id, epoch),
                    exclude_fields,
                )
            else:
                data = json.loads(
                    await reader.read_member_fully(_sample_filename(id, epoch))
                )
            return EvalSample.model_validate(data, context=get_deserializing_context())
        except KeyError:
            raise IndexError(
                f"Sample id {id} for epoch {epoch} not found in log {location}"
            )

    @classmethod
    @override
    async def read_log_sample_summaries(cls, location: str) -> list[EvalSampleSummary]:
        async with AsyncFilesystem() as fs:
            reader = AsyncZipReader(fs, location)
            summaries, _ = await _read_all_summaries_async(reader)
            return summaries

    @classmethod
    @override
    async def write_log(
        cls,
        location: str,
        log: EvalLog,
        if_match_etag: str | None = None,
        header_only: bool = False,
    ) -> None:
        if filesystem(location).is_s3() and if_match_etag:
            # Use S3 conditional write
            await cls._write_log_s3_conditional(
                location, log, if_match_etag, header_only=header_only
            )
        else:
            # Standard write using the recorder (so we get all of the extra streams)
            await _write_eval_log_with_recorder(
                log, dirname(location), location, header_only=header_only
            )

    @classmethod
    async def _write_log_s3_conditional(
        cls,
        location: str,
        log: EvalLog,
        etag: str,
        header_only: bool = False,
    ) -> None:
        """Perform S3 conditional write for .eval format using boto3."""
        bucket, key = _s3_bucket_and_key(location)

        if header_only:
            # Download the existing object, rewrite the zip in memory with a
            # fresh header.json. Sample entries are untouched; any sample
            # mutations on the in-memory log are discarded, matching the
            # local .eval contract.
            async with AsyncFilesystem() as async_fs:
                s3_client = await async_fs.s3_client_async()
                response = await s3_client.get_object(Bucket=bucket, Key=key)
                body = await response["Body"].read()
            log_bytes = _rewrite_eval_zip_with_new_header(body, log)
        else:
            # Full recreate goes through the recorder, which needs a
            # filesystem path; read the result back into memory for upload.
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_eval_file = os.path.join(tmpdir, "temp_log.eval")
                await _write_eval_log_with_recorder(log, tmpdir, temp_eval_file)
                with open(temp_eval_file, "rb") as f:
                    log_bytes = f.read()

        async with AsyncFilesystem() as async_fs:
            await _write_s3_conditional(
                async_fs,
                bucket,
                key,
                log_bytes,
                etag,
                location,
                logger,
            )


def _replace_eval_header_in_place(zip_path: str, log: EvalLog) -> None:
    """Replace `header.json` inside a local `.eval` zip in place.

    Opens the zip in append mode, drops the old header entry from the
    central directory, then writes the new one. The old header bytes
    become unreferenced — a small size leak that's acceptable for local
    files since we're not paying for a re-upload on every edit. Sample
    entries are untouched.

    Note: unlike the flush/finalization writes (which go through
    :func:`inspect_ai._util.atomic_write.atomic_write`), this in-place
    header edit is not atomic — an interruption here can leave the zip's
    central directory inconsistent. It's an intentional trade-off: header
    edits (viewer score edits) are infrequent and rewriting a potentially
    large `.eval` just to change the header isn't worth it. Callers that
    need atomicity should rewrite the whole file.
    """
    eval_header = _eval_log_header(log)
    with ZipFile(zip_path, "a", **zipfile_compress_kwargs) as zf:
        zf.filelist = [i for i in zf.filelist if i.filename != HEADER_JSON]
        zf.NameToInfo.pop(HEADER_JSON, None)
        zf.writestr(HEADER_JSON, to_json_safe(eval_header, indent=None))


def _rewrite_eval_zip_with_new_header(zip_bytes: bytes, log: EvalLog) -> bytes:
    """Return new zip bytes with header.json replaced; no dead bytes.

    Copies every non-header entry from the source zip and appends a fresh
    header.json at the end. Used for remote-filesystem header_only writes
    where dead bytes would otherwise accumulate across re-uploads.
    """
    eval_header = _eval_log_header(log)
    out = BytesIO()
    with (
        ZipFile(BytesIO(zip_bytes), "r") as src,
        ZipFile(out, "w", **zipfile_compress_kwargs) as dst,
    ):
        for info in src.infolist():
            if info.filename == HEADER_JSON:
                continue
            # writestr with a ZipInfo preserves the original compression
            # type / date_time / external_attr. The data still round-trips
            # through decompress + recompress, but member metadata is
            # carried over verbatim.
            dst.writestr(info, src.read(info.filename))
        dst.writestr(HEADER_JSON, to_json_safe(eval_header, indent=None))
    return out.getvalue()


def _eval_log_header(log: EvalLog) -> EvalLog:
    """Build a header-only EvalLog (no samples / reductions) for header.json."""
    return EvalLog(
        version=log.version,
        invalidated=log.invalidated,
        log_updates=log.log_updates,
        config_updates=log.config_updates,
        eval=log.eval,
        plan=log.plan,
        results=log.results,
        stats=log.stats,
        status=log.status,
        error=log.error,
    )


def _rewrite_eval_zip_via_filesystem(location: str, log: EvalLog) -> None:
    """Read a remote .eval, rewrite zip with a new header, write it back.

    Works for any fsspec-backed filesystem (S3, GCS, abfs, …). Used by the
    unconditional header_only write path — the S3 conditional path inlines
    the equivalent steps so it can route the upload through
    `_write_s3_conditional` with `If-Match`.
    """
    with file(location, "rb") as f:
        existing_bytes = f.read()
    new_bytes = _rewrite_eval_zip_with_new_header(existing_bytes, log)
    with file(location, "wb") as f:
        f.write(new_bytes)


async def _read_member_json_excluding(
    reader: AsyncZipReader,
    member: str,
    exclude_fields: set[str],
) -> dict[str, Any]:
    """Parse a zip member's JSON, skipping excluded top-level fields via ijson streaming."""
    import ijson  # type: ignore
    from ijson import IncompleteJSONError, ObjectBuilder
    from ijson.backends.python import (  # type: ignore[import-untyped]
        UnexpectedSymbol,
    )

    try:
        data: dict[str, Any] = {}
        async with await reader.open_member(member) as f:
            depth = 0
            current_key: str = ""
            builder: ObjectBuilder | None = None
            async for prefix, event, value in ijson.parse_async(
                adapt_to_reader(f), use_float=True
            ):
                # Depth must be updated before the completion check
                # so that a closing bracket that returns depth to 1
                # is recognised as completing the current value.
                if event in ("start_map", "start_array"):
                    depth += 1
                elif event in ("end_map", "end_array"):
                    depth -= 1

                if depth == 1 and event == "map_key":
                    current_key = value
                    builder = None if current_key in exclude_fields else ObjectBuilder()
                elif builder is not None:
                    builder.event(event, value)
                    # Depth 1 means we have returned to the top-level
                    # object, so the current field's value is complete.
                    if depth == 1:
                        data[current_key] = builder.value
                        builder = None
    except (
        ValueError,
        IncompleteJSONError,
        UnexpectedSymbol,
    ) as ex:
        if is_ijson_nan_inf_error(ex) or is_ijson_int_overflow_error(ex):
            data = json.loads(await reader.read_member_fully(member))
            for field in exclude_fields:
                data.pop(field, None)
        else:
            raise
    return data


async def _write_eval_log_with_recorder(
    log: EvalLog, recorder_dir: str, output_file: str, header_only: bool = False
) -> None:
    """Helper function to write EvalLog using EvalRecorder pattern."""
    if header_only:
        if filesystem(output_file).is_local():
            _replace_eval_header_in_place(local_path(output_file), log)
        else:
            _rewrite_eval_zip_via_filesystem(output_file, log)
        return

    recorder = EvalRecorder(recorder_dir)
    await recorder.log_init(log.eval, output_file, clean=True)
    await recorder.log_start(log.eval, log.plan)
    for sample in log.samples or []:
        sample = condense_sample(sample)
        await recorder.log_sample(log.eval, sample)
    await recorder.log_finish(
        log.eval,
        log.status,
        log.stats,
        log.results,
        log.reductions,
        log.error,
        invalidated=log.invalidated,
        log_updates=log.log_updates,
        config_updates=log.config_updates,
    )


def _s3_bucket_and_key(location: str) -> tuple[str, str]:
    """Extract S3 bucket and key from an S3 URL."""
    from urllib.parse import urlparse

    parsed = urlparse(location)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


async def _s3_conditional_put_object(
    async_fs: AsyncFilesystem, bucket: str, key: str, body: bytes, etag: str
) -> None:
    """Helper function to perform S3 conditional write with aioboto3."""
    s3_client = await async_fs.s3_client_async()
    # Preflight HEAD: some S3-compatible backends (notably moto) do not honor the
    # IfMatch header on put_object, so verify the current ETag matches before writing.
    current = await s3_client.head_object(Bucket=bucket, Key=key)
    current_etag = str(current["ETag"]).strip('"')
    if current_etag != etag:
        raise WriteConflictError(
            f"Log file was modified by another process. Expected ETag: {etag}"
        )
    await s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        IfMatch=f'"{etag}"',  # S3 requires quotes around ETag
    )


async def _s3_download_with_etag(
    location: str, local_path: str, async_fs: AsyncFilesystem
) -> str:
    """
    Download S3 file and get its ETag in a single operation.

    Returns:
        ETag of the downloaded file (guaranteed to match the downloaded content)
    """
    bucket, key = _s3_bucket_and_key(location)

    s3_client = await async_fs.s3_client_async()
    response = await s3_client.get_object(Bucket=bucket, Key=key)

    content = await response["Body"].read()
    with open(local_path, "wb") as f:
        f.write(content)

    etag: str = response["ETag"]
    return etag.strip('"')  # S3 returns ETag with quotes


async def s3_head_etag(location: str) -> str:
    """Return an S3 object's current ETag via a HEAD request.

    Cheaper than `read_eval_log_async(..., header_only=True)` when the
    caller only needs the ETag — no central-directory read, no zip
    parsing, no body bytes. Used by the viewer's edit endpoint to
    surface the post-write ETag without re-fetching the header.
    """
    bucket, key = _s3_bucket_and_key(location)
    async with AsyncFilesystem() as async_fs:
        s3_client = await async_fs.s3_client_async()
        response = await s3_client.head_object(Bucket=bucket, Key=key)
        return str(response["ETag"]).strip('"')


async def _write_s3_conditional(
    async_fs: AsyncFilesystem,
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
            await _s3_conditional_put_object(async_fs, bucket, key, body, etag)
        except ClientError as e:
            if e.response["Error"]["Code"] == "PreconditionFailed":
                raise WriteConflictError(
                    f"Log file was modified by another process. Expected ETag: {etag}"
                )
            raise


def _copy_temp_to_local(temp_file: BinaryIO, dest: str, fsync: bool) -> None:
    """Copy the zip temp file to its local destination via atomic write.

    Blocking (full-file copy plus, when ``fsync`` is set, physical
    writeback of the whole log) — callers on the event loop must run
    this in a worker thread via ``anyio.to_thread.run_sync``. The rewind
    lives here rather than at the call site so seek + read happen as one
    unit inside the thread.
    """
    temp_file.seek(0)
    with atomic_write(dest, fsync=fsync) as out:
        shutil.copyfileobj(temp_file, out, length=1024 * 1024)


class _BufferedSample(NamedTuple):
    """A buffered sample paired with its summary, computed once at buffer time.

    Building a summary is expensive for large samples — ``EvalSample.summary()``
    runs the ``thin_data`` validator (``textwrap.shorten`` / JSON size probes)
    over the full-size input, metadata, and scores. ``sample_summaries()`` is
    polled by the control channel, and recomputing summaries there made each
    listing request cost minutes of event-loop CPU on an eval buffering many
    transcript-heavy samples (e.g. a retry's reused completed samples).
    """

    sample: EvalSample
    summary: EvalSampleSummary


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
        self._samples: list[_BufferedSample] = []
        self._streaming_samples: dict[tuple[str | int, int], EvalSample] = {}
        self._summary_counter = 0
        self._summaries: list[EvalSampleSummary] = []
        self._config_update_counter = 0
        self._config_updates: list[ConfigUpdate] = []
        self._log_start: LogStart | None = None

    async def init(
        self,
        log_start: LogStart | None,
        summary_counter: int,
        summaries: list[EvalSampleSummary],
        config_update_counter: int = 0,
        config_updates: list[ConfigUpdate] | None = None,
    ) -> None:
        async with self._lock:
            self._open()
            self._summary_counter = summary_counter
            self._summaries = summaries
            self._config_update_counter = config_update_counter
            self._config_updates = config_updates or []
            self._log_start = log_start

    @property
    def log_start(self) -> LogStart | None:
        return self._log_start

    @property
    def config_updates(self) -> list[ConfigUpdate]:
        return self._config_updates

    async def record_config_update(self, update: ConfigUpdate) -> None:
        """Journal a mid-run config change (one file per update).

        Follows the summaries journal pattern (`_journal/config_updates/{n}.json`):
        there is no header.json mid-run and zip members are immutable, so
        appending journal files is the format's native mid-run write. The
        accumulated list is consolidated into the header at `log_finish`.
        """
        async with self._lock:
            self._config_update_counter += 1
            self._zip_writestr(
                _journal_config_update_path(
                    _journal_config_update_file(self._config_update_counter)
                ),
                update,
            )
            self._config_updates.append(update)

    async def start(self, start: LogStart) -> None:
        async with self._lock:
            self._log_start = start
            self._zip_writestr(_journal_path(START_JSON), start)

    async def buffer_sample(self, sample: EvalSample) -> None:
        buffered = _BufferedSample(sample=sample, summary=sample.summary())
        async with self._lock:
            self._samples.append(buffered)

    async def buffer_sample_streaming(
        self, sample: EvalSample, history: "SampleHistory"
    ) -> None:
        async with self._lock:
            events = list(history.iter_events())
            events_data = history.events_data
            attachments = _sample_history_attachments(
                sample, history, events, events_data
            )
            sample_data: dict[str, Any] = jsonable_dict(
                sample.model_dump(
                    mode="python",
                    exclude_none=True,
                    exclude={"events", "events_data", "attachments"},
                    fallback=lambda _x: None,
                )
            )
            sample_data.update(
                {
                    "events": events,
                    "attachments": attachments,
                    "events_data": events_data,
                }
            )

            self._zip_writestr(_sample_filename(sample.id, sample.epoch), sample_data)

            # Retain the event-less sample so the control channel can read its
            # error detail before the next flush makes it on-disk-readable
            # (events stay in the buffer database — see ``buffered_sample``).
            # Cleared in ``flush`` once the sample lands on disk.
            self._streaming_samples[(sample.id, sample.epoch)] = sample

            self._summary_counter += 1
            summary = sample.summary()
            summary_file = _journal_summary_file(self._summary_counter)
            summary_path = _journal_summary_path(summary_file)
            self._zip_writestr(summary_path, [summary])
            self._summaries = [
                s
                for s in self._summaries
                if (s.id, s.epoch) != (summary.id, summary.epoch)
            ]
            self._summaries.append(summary)

    async def write_buffered_samples(self) -> None:
        async with self._lock:
            # Write the buffered samples
            summaries: list[EvalSampleSummary] = []
            for buffered in self._samples:
                sample = buffered.sample
                # Write the sample
                self._zip_writestr(_sample_filename(sample.id, sample.epoch), sample)

                # Capture the summary
                summaries.append(buffered.summary)

            self._samples.clear()

            # write intermediary summaries and add to master list
            if len(summaries) > 0:
                self._summary_counter += 1
                summary_file = _journal_summary_file(self._summary_counter)
                summary_path = _journal_summary_path(summary_file)
                self._zip_writestr(summary_path, summaries)
                # replace any existing summaries for the same (id, epoch)
                # (e.g. when re-logging completed samples after log_init
                # with clean=False during eval_retry / score --overwrite)
                new_keys = {(s.id, s.epoch) for s in summaries}
                self._summaries = [
                    s for s in self._summaries if (s.id, s.epoch) not in new_keys
                ]
                self._summaries.extend(summaries)

    async def sample_summaries(self) -> list[EvalSampleSummary]:
        """All sample summaries recorded so far (gap-free, ahead of disk).

        Unions ``_summaries`` (already journalled) with the not-yet-flushed
        ``_samples`` so a just-completed sample isn't missed between flushes.
        Pure list building — the buffered summaries were computed at buffer
        time (see :class:`_BufferedSample`), so this stays cheap no matter how
        large the buffered samples are or how often the control channel polls.
        """
        async with self._lock:
            return [*self._summaries, *(b.summary for b in self._samples)]

    async def buffered_sample(self, id: str | int, epoch: int) -> EvalSample | None:
        """A not-yet-flushed full sample by ``(id, epoch)``, or None.

        Gap-free counterpart to :meth:`sample_summaries`, covering both
        completion paths during the window before a sample is flushed to disk:

        - ``_samples`` — buffered whole samples (with events) awaiting a flush
          (the reused-on-retry path).
        - ``_streaming_samples`` — the streaming path's event-less samples
          (their events live in the buffer database, so this carries error
          detail / scores but not events).

        Returns ``None`` once flushed (the on-disk log takes over) or for a
        recorder that doesn't buffer; callers fall back to the on-disk log.
        """
        async with self._lock:
            for buffered in self._samples:
                if buffered.sample.id == id and buffered.sample.epoch == epoch:
                    return buffered.sample
            return self._streaming_samples.get((id, epoch))

    async def write(self, filename: str, data: Any) -> None:
        async with self._lock:
            self._zip_writestr(filename, data)

    async def flush(self, *, fsync: bool = True) -> None:
        """Write the buffered zip out to the destination log file.

        Args:
            fsync: True for a durable final write; False for an intermediate
                snapshot, which skips fsync and tolerates file-in-use (see
                ``write_local_snapshot``). Local paths only.
        """
        async with self._lock:
            # close the zip file so it is flushed
            if self._zip:
                self._zip.close()

            # Stream temp file to output using the appropriate backend
            # (atomic local write, native S3 multipart upload, or chunked
            # copy via fsspec).
            written = True
            with trace_action(logger, "Log Write", self._file):
                try:
                    if self._fs.is_local():
                        # Safe under self._lock: nothing else touches
                        # _temp_file until we return, and the helper waits
                        # for the thread on cancellation, so the finally
                        # below never reopens the zip on _temp_file while
                        # the thread is still reading it.
                        written = await write_local_snapshot(
                            self._file,
                            fsync,
                            partial(
                                _copy_temp_to_local,
                                self._temp_file,
                                local_path(self._file),
                                fsync,
                            ),
                        )
                    else:
                        self._temp_file.seek(0)
                        async with AsyncFilesystem() as async_fs:
                            await async_fs.write_file_streaming(
                                self._file, self._temp_file
                            )
                finally:
                    # re-open zip file w/ self.temp_file pointer at end
                    self._open()

            # Everything written so far is now in the uploaded file's central
            # directory and readable from disk, so the streaming-path samples no
            # longer need their in-memory copy (the buffered ``_samples`` are
            # cleared by ``write_buffered_samples``, which the flush callers run
            # first). A skipped write must NOT clear: ``buffered_sample`` falls
            # back to the on-disk log once cleared, which doesn't yet contain
            # these samples.
            if written:
                self._streaming_samples.clear()

    async def close(self, header_only: bool) -> EvalLog:
        async with self._lock:
            try:
                self._temp_file.seek(0)
                # Always read header only from temp file (fast path)
                eval_log = _read_log_from_bytes(
                    self._temp_file, self._file, header_only=True
                )
                if not header_only:
                    # Attach lazy lists that load samples/reductions on first access.
                    # The lazy load inspects zip contents and only populates what exists.
                    lazy_data = _LazyLogData(self._file)
                    samples_lazy: LazyList[EvalSample] = LazyList(lazy_data)
                    lazy_data.samples_list = samples_lazy
                    eval_log.samples = samples_lazy  # type: ignore[assignment]

                    # Only attach lazy reductions if reductions were actually written
                    has_reductions = (
                        self._zip is not None
                        and REDUCTIONS_JSON in self._zip.namelist()
                    )
                    if has_reductions:
                        reductions_lazy: LazyList[EvalSampleReductions] = LazyList(
                            lazy_data
                        )
                        lazy_data.reductions_list = reductions_lazy
                        eval_log.reductions = reductions_lazy  # type: ignore[assignment]
                return eval_log
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
            to_json_safe(data, indent=None),
        )

    @contextmanager
    def _zip_open_write(self, filename: str) -> Generator[IO[bytes], None, None]:
        """Open a ZIP entry for streaming writes.

        Returns a writable binary stream. The caller writes raw bytes
        (typically JSON) directly. The entry is finalized when the
        context manager exits.
        """
        assert self._zip
        with self._zip.open(filename, "w", force_zip64=True) as stream:
            yield stream


def _sample_history_attachments(
    sample: EvalSample,
    history: "SampleHistory",
    events: Sequence[JsonValue],
    events_data: EventsData,
) -> dict[str, str]:
    attachments = dict(sample.attachments)
    for hash in _attachment_hashes(events):
        content = history.attachment(hash)
        if content is not None:
            attachments[hash] = content
    for hash in _attachment_hashes(events_data):
        content = history.attachment(hash)
        if content is not None:
            attachments[hash] = content
    return attachments


def _attachment_hashes(value: object) -> Iterator[str]:
    if isinstance(value, str):
        if value.startswith(ATTACHMENT_PROTOCOL):
            yield value.replace(ATTACHMENT_PROTOCOL, "", 1)
    elif isinstance(value, BaseModel):
        yield from _attachment_hashes(value.model_dump(mode="python"))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _attachment_hashes(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _attachment_hashes(item)


async def _read_log(
    reader: AsyncZipReader,
    entries: list[ZipEntry],
    location: str,
    header_only: bool = False,
    exclude_fields: set[str] | None = None,
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
                if exclude_fields:
                    data = await _read_member_json_excluding(
                        reader, entry.filename, exclude_fields
                    )
                else:
                    # pass the ZipEntry we already hold so read_member_fully
                    # doesn't have to look it up again by name
                    data = await _read_member_json(reader, entry)
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
            eval_log.samples = [
                rebind_sample_timelines(resolve_sample_events_data(s))
                for s in samples_list
            ]
        return eval_log


async def _read_member_json(reader: AsyncZipReader, member: str | ZipEntry) -> Any:
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
        # an in-progress/crashed log has no consolidated header — read any
        # journaled config updates so the header still reports mid-run retunes
        config_updates: list[ConfigUpdate] = []
        for name in _sorted_config_update_entries(entry_names):
            update_data = await _read_member_json(reader, name)
            config_updates.append(
                ConfigUpdate.model_validate(
                    update_data, context=get_deserializing_context()
                )
            )
        return EvalLog(
            version=start.version,
            eval=start.eval,
            plan=start.plan,
            config_updates=config_updates or None,
            location=location,
        )


async def _read_start_async(reader: AsyncZipReader) -> LogStart | None:
    cd = await reader.entries()
    start_path = _journal_path(START_JSON)
    if any(e.filename == start_path for e in cd.entries):
        return cast(LogStart, await _read_member_json(reader, start_path))
    else:
        return None


async def _read_summary_counter(reader: AsyncZipReader) -> int:
    cd = await reader.entries()
    current_count = 0
    summary_prefix = _journal_summary_path()
    for entry in cd.entries:
        if entry.filename.startswith(summary_prefix) and entry.filename.endswith(
            ".json"
        ):
            this_count = int(entry.filename.split("/")[-1].split(".")[0])
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


async def _read_all_summaries_async(
    reader: AsyncZipReader,
) -> tuple[list[EvalSampleSummary], int]:
    cd = await reader.entries()
    entry_names = {e.filename for e in cd.entries}
    count = await _read_summary_counter(reader)
    if SUMMARIES_JSON in entry_names:
        return _parse_summaries(
            await _read_member_json(reader, SUMMARIES_JSON), SUMMARIES_JSON
        ), count
    else:
        # An in-progress log has no consolidated summaries.json; it stores one journal
        # summary file per sample. In this case, we read them concurrently (bounded).
        semaphore = anyio.Semaphore(25)

        async def read_summary_file(i: int) -> list[EvalSampleSummary]:
            summary_file = _journal_summary_file(i)
            async with semaphore:
                data = await _read_member_json(
                    reader, _journal_summary_path(summary_file)
                )
            return _parse_summaries(data, summary_file)

        per_file = await tg_collect(
            [partial(read_summary_file, i) for i in range(1, count + 1)]
        )
        summaries: list[EvalSampleSummary] = [
            s for file_summaries in per_file for s in file_summaries
        ]
        return summaries, count


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
        # see the equivalent journal read in _read_header_async
        config_updates: list[ConfigUpdate] = []
        for name in _sorted_config_update_entries(set(zip.namelist())):
            with zip.open(name, "r") as f:
                config_updates.append(
                    ConfigUpdate.model_validate(
                        json.load(f), context=get_deserializing_context()
                    )
                )
        return EvalLog(
            version=start.version,
            eval=start.eval,
            plan=start.plan,
            config_updates=config_updates or None,
            location=location,
        )


def _sample_filename(id: str | int, epoch: int) -> str:
    return f"{SAMPLES_DIR}/{id}_epoch_{epoch}.json"


def _journal_path(file: str) -> str:
    return JOURNAL_DIR + "/" + file


def _journal_summary_path(file: str | None = None) -> str:
    if file is None:
        return _journal_path(SUMMARY_DIR)
    else:
        return f"{_journal_path(SUMMARY_DIR)}/{file}"


def _journal_summary_file(index: int) -> str:
    return f"{index}.json"


def _journal_config_update_path(file: str | None = None) -> str:
    if file is None:
        return _journal_path(CONFIG_UPDATES_DIR)
    else:
        return f"{_journal_path(CONFIG_UPDATES_DIR)}/{file}"


def _journal_config_update_file(index: int) -> str:
    return f"{index}.json"


def _sorted_config_update_entries(entry_names: set[str]) -> list[str]:
    """Journal config-update entries in write order (by their integer index)."""
    prefix = _journal_config_update_path() + "/"
    entries = [
        name
        for name in entry_names
        if name.startswith(prefix) and name.endswith(".json")
    ]
    return sorted(entries, key=lambda name: int(name.split("/")[-1].split(".")[0]))


async def _read_config_updates_async(
    reader: AsyncZipReader,
) -> tuple[list[ConfigUpdate], int]:
    """Journaled config updates (and the max journal index) from an existing log.

    Used by `log_init` when re-initializing over an existing log (e.g.
    `score --overwrite`) so mid-run retunes recorded by the original run
    aren't dropped by the rebuild. Journal members persist in finished logs
    (zip appends never remove them), so reading the journal covers finished
    and in-progress logs alike; a log produced by a full rewrite has no
    journal members and its updates live only in `header.json`, so that is
    the fallback.
    """
    cd = await reader.entries()
    entry_names = {e.filename for e in cd.entries}
    entries = _sorted_config_update_entries(entry_names)
    if entries:
        updates = []
        for name in entries:
            data = await _read_member_json(reader, name)
            updates.append(
                ConfigUpdate.model_validate(data, context=get_deserializing_context())
            )
        counter = int(entries[-1].split("/")[-1].split(".")[0])
        return updates, counter
    elif HEADER_JSON in entry_names:
        data = await _read_member_json(reader, HEADER_JSON)
        raw_updates = data.get("config_updates") or []
        return [
            ConfigUpdate.model_validate(u, context=get_deserializing_context())
            for u in raw_updates
        ], 0
    else:
        return [], 0


T = TypeVar("T")


class _LazyLogData:
    """Shared state for coordinated lazy loading of samples and reductions."""

    def __init__(self, location: str) -> None:
        self.location = location
        self.loaded = False
        self.samples_list: LazyList[EvalSample] | None = None
        self.reductions_list: LazyList[EvalSampleReductions] | None = None

    def load(self) -> None:
        if self.loaded:
            return
        from .._file import read_eval_log

        log = read_eval_log(self.location, header_only=False)
        if self.samples_list is not None:
            list.extend(self.samples_list, log.samples or [])
        if self.reductions_list is not None:
            list.extend(self.reductions_list, log.reductions or [])
        self.loaded = True


class LazyList(list[T], Generic[T]):
    """A list subclass that defers loading until first access.

    Used by ZipLogFile.close() to avoid deserializing all samples into memory
    when the caller doesn't actually need them (which is the common case after
    eval() returns).
    """

    def __init__(self, lazy_data: _LazyLogData) -> None:
        super().__init__()
        self._lazy_data: _LazyLogData | None = lazy_data

    def _ensure_loaded(self) -> None:
        if self._lazy_data is not None and not self._lazy_data.loaded:
            self._lazy_data.load()
            self._lazy_data = None

    def __len__(self) -> int:
        self._ensure_loaded()
        return super().__len__()

    def __iter__(self) -> Iterator[T]:
        self._ensure_loaded()
        return super().__iter__()

    @overload
    def __getitem__(self, index: SupportsIndex) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> list[T]: ...
    def __getitem__(self, index: SupportsIndex | slice) -> T | list[T]:
        self._ensure_loaded()
        return super().__getitem__(index)

    def __contains__(self, item: object) -> bool:
        self._ensure_loaded()
        return super().__contains__(item)

    def __reversed__(self) -> Iterator[T]:
        self._ensure_loaded()
        return super().__reversed__()

    def __bool__(self) -> bool:
        self._ensure_loaded()
        return len(self) > 0

    def __deepcopy__(self, memo: dict[int, Any]) -> list[T]:
        self._ensure_loaded()
        return copy.deepcopy(list(self), memo)

    def __eq__(self, other: object) -> bool:
        self._ensure_loaded()
        if isinstance(other, LazyList):
            other._ensure_loaded()
        return super().__eq__(other)

    def __add__(self, other: list[Any]) -> list[Any]:
        self._ensure_loaded()
        if isinstance(other, LazyList):
            other._ensure_loaded()
        return super().__add__(other)

    def __radd__(self, other: list[Any]) -> list[Any]:
        self._ensure_loaded()
        return other.__add__(list(self))

    def __copy__(self) -> list[T]:
        self._ensure_loaded()
        return list(self)

    def __repr__(self) -> str:
        self._ensure_loaded()
        return super().__repr__()
