import copy
import json
import logging
import math
import os
import shutil
import tempfile
import warnings
from collections.abc import Generator, Iterable, Sequence
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
from anyio import EndOfStream
from pydantic import BaseModel, Field, JsonValue
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from typing_extensions import override

from inspect_ai._util._async import current_async_backend, tg_collect
from inspect_ai._util.async_bytes_reader import adapt_to_reader
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem, is_s3_filename
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
            destination_exists = True
            async with AsyncFilesystem() as fs:
                reader = AsyncZipReader(fs, location)
                log_start = await _read_start_async(reader)
                summaries, summary_counter = await _read_all_summaries_async(reader)
                (
                    config_updates,
                    config_update_counter,
                ) = await _read_config_updates_async(reader)
        else:
            destination_exists = False
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
            destination_exists=destination_exists,
        )

        # track zip
        self.data[self._log_file_key(eval)] = zip_log_file

        # return file path
        return zip_file

    @override
    async def log_seed(
        self,
        eval: EvalSpec,
        prior: "str | Sequence[EvalSample]",
        keep: set[tuple[str | int, int]] | None,
    ) -> None:
        # a byte copy is only valid same-format: a `.json` prior (a retry with
        # an explicit `log_format="eval"`) or in-memory samples take the
        # generic re-log path
        if isinstance(prior, str) and self.handles_location(prior):
            log = self.data[self._log_file_key(eval)]
            await log.seed_from_prior_log(prior, keep)
        else:
            await super().log_seed(eval, prior, keep)

    @override
    def destination_written(self, eval: EvalSpec) -> bool:
        log = self.data.get(self._log_file_key(eval))
        if log is None:
            raise RuntimeError(
                f"No log in progress for eval {eval.eval_id} "
                "(finished, discarded, or never initialised)"
            )
        return log.destination_written

    @override
    async def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None:
        log = self.data[self._log_file_key(eval)]
        start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval, plan=plan)
        await log.start(start)

    @override
    async def log_sample(
        self, eval: EvalSpec, sample: EvalSample, *, write_through: bool = False
    ) -> None:
        log = self.data[self._log_file_key(eval)]
        if write_through:
            await log.buffer_sample_write_through(sample)
        else:
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
        # Skip while the destination hasn't been written at all: an inherited
        # snapshot recorded at logger init (a zip without start.json isn't
        # readable as an in-progress log, and log_start's own flush follows
        # shortly, carrying the journal entry with it).
        if log.destination_written:
            await log.flush(fsync=False)

    @override
    async def log_discard(
        self, eval: EvalSpec, *, keep_destination: bool = False
    ) -> None:
        log = self.data.pop(self._log_file_key(eval), None)
        if log is not None:
            await log.discard(keep_destination=keep_destination)

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

        if status == "success":
            await log.compact()

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
                    raise IndexError(
                        f"Sample with uuid '{uuid}' not found in log {location}"
                    )
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
    ) -> str | None:
        fs = filesystem(location)
        if fs.is_s3() and (if_match_etag is not None or header_only):
            return await cls._write_log_s3(
                location, log, if_match_etag, header_only=header_only
            )

        # Standard write using the recorder (so we get all of the extra streams)
        return await _write_eval_log_with_recorder(
            log, dirname(location), location, header_only=header_only
        )

    @classmethod
    async def _write_log_s3(
        cls,
        location: str,
        log: EvalLog,
        etag: str | None,
        header_only: bool = False,
    ) -> str:
        """Write an .eval log to S3 and return the upload response ETag."""
        bucket, key = _s3_bucket_and_key(location)

        async with AsyncFilesystem() as async_fs:
            if header_only:
                # Download the existing object, rewrite the zip in memory with a
                # fresh header.json. Sample entries are untouched; any sample
                # mutations on the in-memory log are discarded, matching the
                # local .eval contract.
                body = await async_fs.read_file(location)
                log_bytes = _rewrite_eval_zip_with_new_header(body, log)
            else:
                # Full recreate goes through the recorder, which needs a
                # filesystem path; read the result back into memory for upload.
                with tempfile.TemporaryDirectory() as tmpdir:
                    temp_eval_file = os.path.join(tmpdir, "temp_log.eval")
                    await _write_eval_log_with_recorder(log, tmpdir, temp_eval_file)
                    with open(temp_eval_file, "rb") as f:
                        log_bytes = f.read()

            if etag is not None:
                return await _write_s3(
                    async_fs,
                    bucket,
                    key,
                    log_bytes,
                    etag,
                    location,
                    logger,
                )
            with trace_action(logger, "Log Write", location):
                write_etag = await async_fs.write_file(location, log_bytes)
            if write_etag is None:
                raise RuntimeError("S3 upload completed without returning an ETag")
            return write_etag


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
        _copy_live_members(src, dst, exclude=frozenset({HEADER_JSON}))
        dst.writestr(HEADER_JSON, to_json_safe(eval_header, indent=None))
    return out.getvalue()


def _copy_live_members(
    src: ZipFile, dst: ZipFile, exclude: frozenset[str] = frozenset()
) -> None:
    """Copy each name's last member from ``src`` to ``dst``, streaming.

    Dedupes by member name, last entry winning — a requeued or re-run
    sample's fresh record supersedes the prior one as a duplicate zip member
    (see ``_zip_writestr``), and read-by-name resolves to the last entry;
    copying every info would write those superseded bytes twice. Opening
    the destination entry with the source ``ZipInfo`` preserves the
    original compression type / date_time / external_attr; the data still
    round-trips through decompress + recompress, streamed in chunks so a
    large member never sits in memory whole. Blocking — run in a worker
    thread when called from the event loop.
    """
    infos = {info.filename: info for info in src.infolist()}
    for info in infos.values():
        if info.filename in exclude:
            continue
        with (
            src.open(info, "r") as reader,
            dst.open(info, "w", force_zip64=True) as writer,
        ):
            shutil.copyfileobj(reader, writer, length=1024 * 1024)


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

    Used for non-S3 fsspec-backed filesystems such as GCS and abfs. S3
    header-only writes instead use `_write_log_s3` so they can return the
    exact upload ETag and apply `If-Match` when requested.
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
    # get_ijson_backend() falls back to the pure-Python backend under trio
    # (yajl2_c's parse_async is asyncio-only).
    from inspect_ai._util.json import get_ijson_backend

    ijson = get_ijson_backend()
    from ijson import IncompleteJSONError, ObjectBuilder  # type: ignore[import-untyped]
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
) -> str | None:
    """Helper function to write EvalLog using EvalRecorder pattern."""
    if header_only:
        if filesystem(output_file).is_local():
            _replace_eval_header_in_place(local_path(output_file), log)
        else:
            _rewrite_eval_zip_via_filesystem(output_file, log)
        return None

    recorder = EvalRecorder(recorder_dir)
    await recorder.log_init(log.eval, output_file, clean=True)
    await recorder.log_start(log.eval, log.plan)
    for sample in log.samples or []:
        sample = condense_sample(sample)
        await recorder.log_sample(log.eval, sample)
    result = await recorder.log_finish(
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
    return result.etag


def _s3_bucket_and_key(location: str) -> tuple[str, str]:
    """Extract S3 bucket and key from an S3 URL."""
    from urllib.parse import urlparse

    parsed = urlparse(location)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


async def _s3_put_object(
    async_fs: AsyncFilesystem,
    bucket: str,
    key: str,
    body: bytes,
    etag: str | None,
) -> str:
    """Write to S3 and return the ETag from that exact PutObject response."""
    s3_client = await async_fs.s3_client_async()
    put_args: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": body}
    if etag is not None:
        # Some S3-compatible backends (notably moto) do not honor IfMatch on
        # put_object, so verify the current ETag before the conditional write.
        current = await s3_client.head_object(Bucket=bucket, Key=key)
        current_etag = str(current["ETag"]).strip('"')
        if current_etag != etag:
            raise WriteConflictError(
                f"Log file was modified by another process. Expected ETag: {etag}"
            )
        put_args["IfMatch"] = f'"{etag}"'

    response = await s3_client.put_object(**put_args)
    return str(response["ETag"]).strip('"')


async def _write_s3(
    async_fs: AsyncFilesystem,
    bucket: str,
    key: str,
    body: bytes,
    etag: str | None,
    location: str,
    logger: logging.Logger,
) -> str:
    """Write to S3 with conditional-conflict translation when requested."""
    from botocore.exceptions import ClientError

    from inspect_ai._util.trace import trace_action

    action = "Log Conditional Write" if etag is not None else "Log Write"
    with trace_action(logger, action, location):
        try:
            return await _s3_put_object(async_fs, bucket, key, body, etag)
        except ClientError as e:
            if etag is not None and e.response["Error"]["Code"] == "PreconditionFailed":
                raise WriteConflictError(
                    f"Log file was modified by another process. Expected ETag: {etag}"
                )
            raise


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


# Compaction rewrites (decompress + recompress) every live member of the log,
# so it only pays off once dead bytes are a real share of the file.
COMPACT_DEAD_BYTES_FRACTION = 0.1

# A prior-log copy failing on a storage blip should not burn a retry attempt:
# the copy is retried this many times with exponential jittered backoff
# starting from this many seconds.
SEED_COPY_ATTEMPTS = 3
SEED_COPY_BACKOFF_SECONDS = 1.0
_SEED_COPY_CHUNK_SIZE = 1024 * 1024


async def _copy_prior_log(prior_log: str, dest: BinaryIO) -> None:
    """Copy a prior log's bytes into ``dest`` (empty, positioned at 0).

    Local files copy in a worker thread. S3 files pump
    ``AsyncFilesystem.read_file_bytes`` — a byte stream under asyncio, the
    whole object read in a worker thread under trio — into ``dest`` (an
    anonymous temp file, so it has no path a filesystem download could
    target). Any other remote filesystem (``gs://``, ``az://``, ...) has no
    async client and, per the fsspec rule in AGENTS.md, cannot be read in a
    worker thread either, so it is read synchronously on the event loop one
    chunk at a time with a checkpoint between chunks: each stall is bounded
    by one chunk's fetch rather than the whole download. Transient failures
    are retried with backoff (the same ``AsyncRetrying`` idiom as the S3
    put retry in ``asyncfiles``); a missing prior log raises
    ``FileNotFoundError`` immediately.
    """
    fs = filesystem(prior_log)

    def is_transient_failure(exception: BaseException) -> bool:
        # a positive predicate: tenacity's attempt manager catches
        # BaseException, so a negative one would also match a cancellation
        # mid-copy, swallowing it for one step (a spurious "retrying"
        # warning and temp-file reset) before the next sleep re-raised it
        return isinstance(exception, Exception) and not isinstance(
            exception, FileNotFoundError
        )

    def reset_before_retry(state: RetryCallState) -> None:
        dest.seek(0)
        dest.truncate()
        outcome = state.outcome
        logger.warning(
            f"Copying prior log {prior_log} failed (attempt {state.attempt_number} "
            f"of {SEED_COPY_ATTEMPTS}), retrying: "
            f"{outcome.exception() if outcome is not None else 'unknown error'}"
        )

    async for attempt in AsyncRetrying(
        retry=retry_if_exception(is_transient_failure),
        wait=wait_exponential_jitter(
            initial=SEED_COPY_BACKOFF_SECONDS, jitter=SEED_COPY_BACKOFF_SECONDS
        ),
        stop=stop_after_attempt(SEED_COPY_ATTEMPTS),
        sleep=anyio.sleep,
        before_sleep=reset_before_retry,
        reraise=True,
    ):
        with attempt:
            if fs.is_local():
                await anyio.to_thread.run_sync(
                    _copy_local_file, local_path(prior_log), dest
                )
            else:
                await _copy_remote_file(prior_log, dest)


def _copy_local_file(path: str, dest: BinaryIO) -> None:
    with open(path, "rb") as src:
        shutil.copyfileobj(src, dest, length=_SEED_COPY_CHUNK_SIZE)


async def _copy_remote_file(location: str, dest: BinaryIO) -> None:
    # a buffered write of one chunk into an anonymous temp file lands in the
    # page cache far faster than a thread hop would, so both branches write
    # inline
    if is_s3_filename(location):
        async with AsyncFilesystem() as async_fs:
            stream = await async_fs.read_file_bytes(location, 0, None)
            try:
                while True:
                    try:
                        chunk = await stream.receive(_SEED_COPY_CHUNK_SIZE)
                    except EndOfStream:
                        break
                    dest.write(chunk)
            finally:
                await stream.aclose()
    else:
        with file(location, "rb") as src:
            while chunk := src.read(_SEED_COPY_CHUNK_SIZE):
                dest.write(chunk)
                await anyio.lowlevel.checkpoint()


def _read_prior_summaries(prior: BinaryIO) -> list[EvalSampleSummary]:
    """Read a copied prior log's summaries, validating it is a zip.

    Opened read-only: unlike append mode, which treats anything that is not
    a zip as an empty archive to append to, this raises ``BadZipFile`` for a
    corrupt or truncated copy rather than seeding nothing. Blocking — run in
    a worker thread.
    """
    prior.seek(0)
    with ZipFile(prior, "r") as zip:
        return _read_all_summaries(zip)


def _read_all_summaries(zip: ZipFile) -> list[EvalSampleSummary]:
    """Sync counterpart of ``_read_all_summaries_async`` over an open ``ZipFile``.

    Prefers the consolidated ``summaries.json``; an in-progress log has only
    the journal, read in index order so a superseded row precedes its
    re-run's. Used by the prior-log seed, whose zip is an anonymous temp
    file the path-based async reader cannot target.
    """
    names = set(zip.namelist())
    if SUMMARIES_JSON in names:
        with zip.open(SUMMARIES_JSON, "r") as f:
            return _dedupe_summaries(_parse_summaries(json.load(f), SUMMARIES_JSON))
    summaries: list[EvalSampleSummary] = []
    for name in _sorted_journal_entries(names, _journal_summary_path()):
        with zip.open(name, "r") as f:
            summaries.extend(_parse_summaries(json.load(f), name))
    return _dedupe_summaries(summaries)


def _parse_sample_bytes(data: bytes) -> EvalSample:
    """Parse a sample member read from the zip, resolved as a log read is.

    The same read-time resolution ``read_eval_log_sample`` applies
    (``events_data`` references bound back into the events, timelines
    rebound), so a sample served from the recorder's local copy and one read
    from the destination log look alike. Blocking (JSON parse + validation
    of a whole transcript) — run in a worker thread.
    """
    sample = EvalSample.model_validate(
        json.loads(data), context=get_deserializing_context()
    )
    return rebind_sample_timelines(resolve_sample_events_data(sample))


def _compact_zip(src_file: BinaryIO) -> BinaryIO:
    """Copy the live members of a closed zip temp file into a fresh temp file.

    Live means the last member under each name (the readers' rule); pruned
    and superseded members are left behind. Blocking (decompress +
    recompress of every member) — run in a worker thread.
    """
    src_file.seek(0)
    out: BinaryIO = tempfile.TemporaryFile()
    try:
        with (
            ZipFile(src_file, "r") as src,
            ZipFile(out, "w", **zipfile_compress_kwargs) as dst,
        ):
            _copy_live_members(src, dst)
    except BaseException:
        out.close()
        raise
    return out


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
        self._destination_written = False
        # whether the destination existed before this log (init seeded from
        # it) — such a file is never ours to remove on discard. Distinct from
        # a prior-log seed (`seed_from_prior_log`): that fills the temp zip
        # from *another* file for a fresh destination, which discard must
        # still remove.
        self._destination_seeded = False
        # sample members that `buffered_sample` serves from the local temp zip
        # (a prior-log seed's copied records and write-through re-logs) rather
        # than deferring to the destination log
        self._local_sample_names: set[str] = set()
        self._etag: str | None = None

    async def init(
        self,
        log_start: LogStart | None,
        summary_counter: int,
        summaries: list[EvalSampleSummary],
        config_update_counter: int = 0,
        config_updates: list[ConfigUpdate] | None = None,
        destination_exists: bool = False,
    ) -> None:
        async with self._lock:
            self._open()
            self._summary_counter = summary_counter
            self._summaries = summaries
            self._config_update_counter = config_update_counter
            self._config_updates = config_updates or []
            self._log_start = log_start
            self._destination_written = destination_exists
            self._destination_seeded = destination_exists

    @property
    def log_start(self) -> LogStart | None:
        return self._log_start

    @property
    def destination_written(self) -> bool:
        """Whether the destination log file has been written at least once.

        True after a successful :meth:`flush`, or from the start when
        ``init`` was seeded from an existing file (re-logging into an
        existing log, e.g. ``score --overwrite``). Gates eager per-update
        flushes in ``log_config_update``: while False the destination is
        absent (``log_start``'s flush creates it), so nothing should force
        it into existence early.
        """
        return self._destination_written

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
            # supersede any not-yet-flushed prior record for the same
            # (id, epoch) — e.g. a requeued sample's re-run going terminal
            # before the prior attempt's flush. Keeping both would journal
            # duplicate summaries, serve the stale record from
            # ``buffered_sample``, and (when the prior arrived via the
            # streaming path, whose member is already zip-written) leave a
            # stale event-less fallback in ``_streaming_samples``.
            key = (sample.id, sample.epoch)
            self._samples = [
                s for s in self._samples if (s.sample.id, s.sample.epoch) != key
            ]
            self._streaming_samples.pop(key, None)
            self._samples.append(buffered)

    async def buffer_sample_write_through(self, sample: EvalSample) -> None:
        """Write a completed sample straight into the temp-file zip.

        The bulk re-log counterpart to :meth:`buffer_sample` (used to seed a
        retry attempt with a prior log's samples when they cannot be copied
        as bytes — an in-memory prior log, or one in a different format): the
        full sample — events included — goes into the temp zip immediately,
        so it lands on local disk instead of staying resident in ``_samples``
        until the next flush (anything in the temp zip reaches the
        destination on any later flush, which copies the whole file). The
        member is registered for :meth:`buffered_sample`, which serves it
        whole from the local zip, and the summary is journalled immediately
        with the same replace-by-``(id, epoch)`` dedupe. Nothing is appended
        to ``_samples``.
        """
        async with self._lock:
            name = _sample_filename(sample.id, sample.epoch)
            self._zip_writestr(name, sample)
            self._local_sample_names.add(name)
            self._journal_summary(sample)

    def _journal_summary(self, sample: EvalSample) -> None:
        """Journal the sample's summary and merge it into ``_summaries``.

        Replaces any existing summary for the same ``(id, epoch)`` (e.g. when
        re-logging completed samples after log_init with clean=False during
        eval_retry / score --overwrite). Caller must hold ``self._lock``.
        """
        self._summary_counter += 1
        summary = sample.summary()
        summary_file = _journal_summary_file(self._summary_counter)
        summary_path = _journal_summary_path(summary_file)
        self._zip_writestr(summary_path, [summary])
        self._summaries = [
            s for s in self._summaries if (s.id, s.epoch) != (summary.id, summary.epoch)
        ]
        self._summaries.append(summary)

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

            # evict a buffered prior record for the same (id, epoch): its
            # member would otherwise be flush-written *after* the streaming
            # write above, and the readers' name-based last-entry-wins rule
            # would resolve the log to the stale prior
            self._samples = [
                s
                for s in self._samples
                if (s.sample.id, s.sample.epoch) != (sample.id, sample.epoch)
            ]

            # Retain the event-less sample so the control channel can read its
            # error detail before the next flush makes it on-disk-readable
            # (events stay in the buffer database — see ``buffered_sample``).
            # Cleared in ``flush`` once the sample lands on disk.
            self._streaming_samples[(sample.id, sample.epoch)] = sample

            self._journal_summary(sample)

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

                # each write serializes + compresses synchronously on the
                # event loop, so yield between samples to bound the stall to
                # one sample rather than the whole batch (in-flight samples
                # and the control-channel server run in the gaps). The lock
                # stays held, so `_samples` can't change under the iteration.
                await anyio.lowlevel.checkpoint()

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
        A buffered sample supersedes a journalled row for the same
        ``(id, epoch)`` (a requeued sample's re-run ahead of its flush), so
        consumers see one row per key with the freshest outcome.

        Pure dict building — the buffered summaries were computed at buffer
        time (see :class:`_BufferedSample`), so this stays cheap no matter how
        large the buffered samples are or how often the control channel polls.
        """
        async with self._lock:
            by_key = {(s.id, s.epoch): s for s in self._summaries}
            for b in self._samples:
                by_key[(b.summary.id, b.summary.epoch)] = b.summary
            return list(by_key.values())

    async def buffered_sample(self, id: str | int, epoch: int) -> EvalSample | None:
        """A not-yet-flushed full sample by ``(id, epoch)``, or None.

        Gap-free counterpart to :meth:`sample_summaries`, covering both
        completion paths during the window before a sample is flushed to disk:

        - ``_samples`` — buffered whole samples (with events) awaiting a flush
          (the default :meth:`buffer_sample` path).
        - the local temp zip, for members a prior-log seed copied in or a
          write-through re-logged (``_local_sample_names``): the freshest
          complete record under that name (a re-run's superseding member
          wins, as for every zip reader), read and decompressed in a worker
          thread while the lock is held — the same contention a flush
          imposes — then parsed and resolved like a log read outside it.
        - ``_streaming_samples`` — event-less samples from the streaming path
          (their events live in the buffer database, so this carries error
          detail / scores but not events).

        Returns ``None`` once flushed (the on-disk log takes over) or for a
        recorder that doesn't buffer; callers fall back to the on-disk log.
        """
        async with self._lock:
            for buffered in self._samples:
                if buffered.sample.id == id and buffered.sample.epoch == epoch:
                    return buffered.sample
            name = _sample_filename(id, epoch)
            if (
                name in self._local_sample_names
                and self._zip is not None
                and name in self._zip.NameToInfo
            ):
                data = await anyio.to_thread.run_sync(self._zip.read, name)
            else:
                return self._streaming_samples.get((id, epoch))
        return await anyio.to_thread.run_sync(_parse_sample_bytes, data)

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
            etag: str | None = None
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
                            etag = await async_fs.write_file_streaming(
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
            # these samples. A skipped write likewise leaves
            # ``_destination_written`` alone — nothing reached the destination,
            # so the next successful flush is what sets it.
            if written:
                self._streaming_samples.clear()
                self._destination_written = True
                self._etag = etag

    async def discard(self, *, keep_destination: bool = False) -> None:
        """Release this never-finished log's resources without writing.

        Removes the destination file when this log wrote it (the header
        flushed by ``log_start``, e.g. an abandoned retry attempt) — a stray
        ``started`` log would otherwise win the end-of-run retry-cleanup
        sweep by mtime over the errored prior attempt's log. A pre-existing
        destination the log was initialized over is left in place; a log
        seeded from a *prior attempt's* file (``seed_from_prior_log``) owns
        its own destination and is removed like any other. With
        ``keep_destination`` the file stays whatever wrote it: an attempt
        whose final write failed leaves a ``started`` log holding every
        sample flushed so far, which the next attempt seeds from.
        """
        async with self._lock:
            try:
                if self._zip:
                    self._zip.close()
                    self._zip = None
            finally:
                self._temp_file.close()
            if (
                self._destination_written
                and not self._destination_seeded
                and not keep_destination
            ):
                # TODO: sync fsspec rm blocks the event loop on remote log
                # dirs; route through AsyncFilesystem if it ever grows an rm
                # helper (to_thread over remote fsspec can deadlock — see
                # AGENTS.md). Rare path, and failures are contained by
                # TaskLogger.discard.
                try:
                    self._fs.rm(self._file)
                except FileNotFoundError:
                    pass

    async def close(self, header_only: bool) -> EvalLog:
        async with self._lock:
            try:
                self._temp_file.seek(0)
                # Under trio, read the full log eagerly from the temp file
                # bytes: LazyList materialization goes through the sync
                # read_eval_log(), which raises in a trio async context.
                if not header_only and current_async_backend() == "trio":
                    eval_log = _read_log_from_bytes(
                        self._temp_file, self._file, header_only=False
                    )
                    eval_log.etag = self._etag
                    return eval_log
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
                eval_log.etag = self._etag
                return eval_log
            finally:
                self._temp_file.close()
                if self._zip:
                    self._zip.close()

    async def seed_from_prior_log(
        self, prior_log: str, keep: set[tuple[str | int, int]] | None
    ) -> None:
        """Fill the temp zip from a prior attempt's log before this log starts.

        Copies the prior ``.eval`` as a file (one streamed download for a
        remote log), so every prior sample record is in this log byte for
        byte before any of the attempt's own work runs — the invariant that
        makes any finish of the attempt write a complete log (see
        ``design/retry-seeded-attempt-log.md``). Then prunes the prior's
        metadata members and the sample members outside ``keep`` from the
        central directory (dead bytes, reclaimed by :meth:`compact` at a
        successful finish), rewrites the summaries journal to list exactly
        the kept samples (one member, built in a worker thread), and
        re-journals any config updates recorded since :meth:`init`.

        ``keep`` restricts the seed to the attempt's planned ``(id, epoch)``
        keys; ``None`` keeps every prior sample (a dynamically fed task has no
        upfront plan). Matching is by generated member name, as the sample
        readers match.

        Must run before :meth:`start`. The copy lands in a *fresh* temp file
        outside ``_lock`` (a multi-GB download must not stall the other lock
        users), which then replaces the one ``init`` opened: that handle is
        an append-mode ``ZipFile`` over an empty file, and closing it writes
        an end-of-central-directory record at offset 0 (a dropped handle
        does the same from ``__del__``), so it is closed explicitly over the
        old file before the swap — the copied bytes are never written over.
        The copy is validated as a zip before it is adopted (append mode
        would treat a corrupt copy as an empty archive and seed nothing).
        A failure leaves the log exactly as it was and re-raises for the
        caller to decide; a missing prior log raises ``FileNotFoundError``
        without retrying.
        """
        if (
            self._log_start is not None
            or self._destination_written
            or self._destination_seeded
        ):
            raise RuntimeError("An eval log can only be seeded before it starts")
        seeded: BinaryIO = tempfile.TemporaryFile()
        try:
            await _copy_prior_log(prior_log, seeded)
            summaries = await anyio.to_thread.run_sync(_read_prior_summaries, seeded)
        except BaseException:
            seeded.close()
            raise

        async with self._lock:
            if self._log_start is not None:
                seeded.close()
                raise RuntimeError("An eval log can only be seeded before it starts")
            assert self._zip is not None
            self._zip.close()
            self._zip = None
            self._temp_file.close()
            self._temp_file = seeded
            self._open()
            assert self._zip is not None

            if keep is not None:
                keep_names = {_sample_filename(id, epoch) for id, epoch in keep}
                summaries = [
                    s
                    for s in summaries
                    if _sample_filename(s.id, s.epoch) in keep_names
                ]
            kept_names = {_sample_filename(s.id, s.epoch) for s in summaries}
            self._prune_prior_members(kept_names)

            # the prior's journal is pruned above (its batched files would list
            # pruned keys to in-progress readers), so the kept summaries become
            # this log's journal; the counter restarts since readers take the
            # maximum index present
            self._summaries = summaries
            self._summary_counter = 0
            if summaries:
                self._summary_counter = 1
                journal = _journal_summary_path(_journal_summary_file(1))
                zip_file = self._zip

                def write_journal() -> None:
                    # `_zip_writestr` is not used: it quiets zipfile's
                    # duplicate-name warning via the process-wide warnings
                    # filters, which a worker thread must not touch. The name
                    # is fresh here (the prior's journal was pruned above)
                    zip_file.writestr(journal, to_json_safe(summaries, indent=None))

                # one member for the whole kept list (tens of MB of JSON for a
                # large prior), so serialize and deflate in a worker thread
                # with `_lock` held, as `buffered_sample` and `compact` do
                await anyio.to_thread.run_sync(write_journal)
            self._rejournal_config_updates()
            self._local_sample_names.update(kept_names)

    def _prune_prior_members(self, kept_sample_names: set[str]) -> None:
        """Drop the prior log's superseded members from the central directory.

        Removes its finished-log metadata (``header.json``, ``summaries.json``,
        ``reductions.json``, ``start.json``, journaled config updates and
        summaries) — an in-progress read of this log would otherwise return
        the prior attempt's header and eval_id — and every sample member not
        in ``kept_sample_names``. Bytes stay in the file unreferenced (the
        idiom ``_replace_eval_header_in_place`` uses) until :meth:`compact`
        measures and reclaims them. Caller holds ``_lock``.
        """
        assert self._zip is not None
        metadata = {
            HEADER_JSON,
            SUMMARIES_JSON,
            REDUCTIONS_JSON,
            _journal_path(START_JSON),
        }
        config_prefix = _journal_config_update_path() + "/"
        summary_prefix = _journal_summary_path() + "/"

        def drop(name: str) -> bool:
            if name in metadata:
                return True
            if name.startswith(config_prefix) or name.startswith(summary_prefix):
                return True
            return name.startswith(f"{SAMPLES_DIR}/") and name not in kept_sample_names

        pruned = [info for info in self._zip.filelist if drop(info.filename)]
        self._zip.filelist = [
            info for info in self._zip.filelist if not drop(info.filename)
        ]
        for info in pruned:
            self._zip.NameToInfo.pop(info.filename, None)

    def _rejournal_config_updates(self) -> None:
        """Re-append the config updates recorded so far as journal members 1..n.

        A prior-log seed replaces the temp zip, leaving behind any
        ``_journal/config_updates/*`` written between ``init`` and the seed
        (inherited process-scoped retunes); this puts them back. Caller holds
        ``_lock``.
        """
        self._config_update_counter = 0
        for update in self._config_updates:
            self._config_update_counter += 1
            self._zip_writestr(
                _journal_config_update_path(
                    _journal_config_update_file(self._config_update_counter)
                ),
                update,
            )

    async def compact(self) -> None:
        """Rewrite the temp zip without dead bytes when they are worth reclaiming.

        Dead bytes are every byte of the member area no live member accounts
        for: members pruned by a prior-log seed, members superseded by a
        later write under the same name (a re-run of a seeded or requeued
        sample), and the same left behind in the prior log by *its* seed and
        re-runs, which its non-success finish never compacted and the byte
        copy carried along (see :meth:`_should_compact`). Rewriting
        decompresses and recompresses every live member, so it runs only
        when the dead bytes exceed ``COMPACT_DEAD_BYTES_FRACTION`` of the
        file — a fresh eval never qualifies — and only at a successful
        finish, the log's last write. Local CPU in a worker thread; a
        failure warns and leaves the uncompacted (still correct) zip in
        place.
        """
        async with self._lock:
            assert self._zip is not None
            if not self._should_compact():
                return
            self._zip.close()
            self._zip = None
            try:
                compacted = await anyio.to_thread.run_sync(
                    _compact_zip, self._temp_file
                )
            except Exception as ex:
                logger.warning(f"Unable to compact eval log {self._file}: {ex}")
            else:
                self._temp_file.close()
                self._temp_file = compacted
            finally:
                self._open()

    def _should_compact(self) -> bool:
        """Whether dead bytes are at least ``COMPACT_DEAD_BYTES_FRACTION`` of the member area.

        Measured from the file rather than tracked per prune or supersede,
        so dead bytes inherited from the prior log count too: the member
        area runs from offset 0 to ``start_dir`` (where the central directory
        is written at close), and whatever the live members' local headers
        and compressed data don't cover is dead. A local header is
        reconstructed as ``FileHeader(zip64=True)``: exact for the members
        ``_zip_open_write`` streams with ``force_zip64``, and 20 bytes over
        for ``writestr`` members, so dead bytes are if anything
        under-counted (a fresh eval measures none).
        """
        assert self._zip is not None
        member_area = self._zip.start_dir
        live = sum(
            len(info.FileHeader(zip64=True)) + info.compress_size
            for info in self._zip.NameToInfo.values()
        )
        dead = member_area - live
        if dead <= 0:
            return False
        return dead >= member_area * COMPACT_DEAD_BYTES_FRACTION

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
        # a repeated member name is deliberate superseding (a requeued
        # sample's fresh record, or re-logging with clean=False): readers
        # resolve names to the last entry, so quiet zipfile's duplicate-name
        # UserWarning rather than surfacing it per re-log
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Duplicate name:", category=UserWarning
            )
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
        # a re-logged sample (e.g. a requeued sample superseding its prior
        # terminal record) appends a second member under the same name;
        # name-based zip access resolves to the last entry, so match that
        # here rather than yielding duplicate samples
        unique_entries = {e.filename: e for e in entries}
        for entry in unique_entries.values():
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
            # namelist() repeats a re-logged member (e.g. a requeued
            # sample); zip.open(name) resolves to the last entry, so read
            # each unique name once rather than yielding duplicate samples
            for name in dict.fromkeys(zip.namelist()):
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


def _dedupe_summaries(
    summaries: Iterable[EvalSampleSummary],
) -> list[EvalSampleSummary]:
    """Keep the last row per ``(id, epoch)``.

    The same last-entry-wins rule the zip sample readers apply: a requeued
    sample's re-run is recorded after its superseded prior attempt, so the
    later row is the current one.
    """
    by_key: dict[tuple[int | str, int], EvalSampleSummary] = {}
    for summary in summaries:
        by_key[(summary.id, summary.epoch)] = summary
    return list(by_key.values())


async def _read_all_summaries_async(
    reader: AsyncZipReader,
) -> tuple[list[EvalSampleSummary], int]:
    cd = await reader.entries()
    entry_names = {e.filename for e in cd.entries}
    count = await _read_summary_counter(reader)
    if SUMMARIES_JSON in entry_names:
        # deduped defensively: the writer's in-memory list is keyed unique,
        # but a log written before superseding-on-buffer existed can carry
        # both a requeued sample's rows
        return _dedupe_summaries(
            _parse_summaries(
                await _read_member_json(reader, SUMMARIES_JSON), SUMMARIES_JSON
            )
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
        # tg_collect preserves the 1..count journal-file order, so the
        # superseded prior attempt's row precedes its re-run's
        return _dedupe_summaries(
            summary for file_summaries in per_file for summary in file_summaries
        ), count


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
    return _sorted_journal_entries(entry_names, _journal_config_update_path())


def _sorted_journal_entries(entry_names: set[str], journal_dir: str) -> list[str]:
    """The ``{n}.json`` members under a journal directory, in index order."""
    prefix = journal_dir + "/"
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
