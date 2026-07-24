import asyncio
import contextlib
import inspect
import os
import urllib.parse
from collections.abc import AsyncIterable
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from logging import getLogger
from typing import Any, AsyncIterator, Literal, NamedTuple, Tuple, cast

import anyio.to_thread
import fsspec  # type: ignore
from aiobotocore.response import StreamingBody
from anyio import EndOfStream
from botocore.exceptions import ClientError
from fsspec.asyn import AsyncFileSystem  # type: ignore
from fsspec.core import split_protocol  # type: ignore
from pydantic import BaseModel
from s3fs import S3FileSystem  # type: ignore
from s3fs.core import _error_wrapper, version_id_kw  # type: ignore

from inspect_ai._eval.evalset import EvalSet
from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import _READ_FULLY_CHUNK_SIZE, AsyncFilesystem
from inspect_ai._util.azure import is_azure_auth_error
from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.file import default_fs_options, dirname, filesystem, size_in_mb
from inspect_ai._view.azure import (
    azure_warning_hint,
    normalize_azure_listing_name,
    should_suppress_azure_error,
)
from inspect_ai.log._edit import LogUpdate, edit_eval_log
from inspect_ai.log._file import (
    EvalLogInfo,
    eval_log_json,
    is_log_file,
    log_file_info_async,
    log_files_from_ls_async,
    read_eval_log_async,
    write_eval_log_async,
)
from inspect_ai.log._log import EvalLog
from inspect_ai.log._recorders.buffer.buffer import sample_buffer
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.buffer.types import PendingSampleUrls, SegmentRef
from inspect_ai.log._recorders.eval import s3_head_etag

logger = getLogger(__name__)


def normalize_uri(uri: str) -> str:
    """Normalize incoming URIs to a consistent format."""
    # Decode any URL-encoded characters
    parsed = urllib.parse.urlparse(urllib.parse.unquote(uri))

    if parsed.scheme != "file":
        # If this isn't a file uri, just unquote it
        return urllib.parse.unquote(uri)

    else:
        # If this is a file uri, see whether we should process triple slashes
        # down to double slashes
        path = parsed.path

        # Detect and normalize Windows-style file URIs
        if path.startswith("/") and len(path) > 3 and path[2] == ":":
            # Strip leading `/` before drive letter
            path = path[1:]

        return f"file://{path}"


class AppConfig(BaseModel):
    """Application configuration returned by GET /app-config."""

    inspect_version: str
    scout_version: str | None = None


def get_app_config() -> AppConfig:
    """Return app config, including installed inspect and scout versions.

    `inspect_scout` is an optional dependency, so `scout_version` is None when
    it isn't installed.
    """
    try:
        scout_version: str | None = version("inspect_scout")
    except PackageNotFoundError:
        scout_version = None
    return AppConfig(
        inspect_version=version(PKG_NAME),
        scout_version=scout_version,
    )


class LogDirResponse(BaseModel):
    log_dir: str


class LogHandle(BaseModel):
    name: str
    mtime: float | None = None
    task: str | None = None
    task_id: str | None = None


class LogFilesResponse(BaseModel):
    response_type: Literal["incremental", "full"]
    files: list[LogHandle]


class LogListingResponse(BaseModel):
    log_dir: str
    """The log dir in request/display form (relative or `~`-aliased for local paths)."""

    log_dir_uri: str | None = None
    """The log dir in the canonical URI namespace of the file names (see `log_dir_uri`)."""

    files: list[LogHandle]


def get_log_dir(log_dir: str) -> LogDirResponse:
    return LogDirResponse(log_dir=aliased_path(log_dir))


async def read_eval_set_info_async(
    eval_set_dir: str, afs: AsyncFilesystem
) -> EvalSet | None:
    """Read the `eval-set.json` manifest for `eval_set_dir` via the async filesystem.

    Async counterpart to `read_eval_set_info`. Reads the manifest through
    `AsyncFilesystem` (riding the shared client) rather than bouncing sync fsspec
    through a threadpool — see the fsspec/`to_thread` warning in AGENTS.md.
    Returns None when the manifest is absent, or (matching `read_eval_set_info`)
    when the check/read fails with an Azure auth error.
    """
    sep = filesystem(eval_set_dir).sep
    manifest = f"{eval_set_dir.rstrip('/').rstrip(sep)}{sep}eval-set.json"
    try:
        if not await afs.exists(manifest):
            return None
        return EvalSet.model_validate_json(await afs.read_file(manifest))
    except Exception as ex:
        if is_azure_auth_error(ex):
            return None
        raise


async def get_log_files(
    request_log_dir: str,
    recursive: bool,
    fs_options: dict[str, Any],
    mtime: float,
    file_count: int,
) -> LogFilesResponse:
    # list logs
    logs = await list_eval_logs_async(
        log_dir=request_log_dir, recursive=recursive, fs_options=fs_options
    )

    if len(logs) != file_count:
        # Has the number of files changed? could be a delete
        # so send a complete list
        return log_files_response(
            logs, response_type="full", base_log_dir=request_log_dir
        )
    else:
        # send only the changed files (captures edits)
        logs = [log for log in logs if (log.mtime is None or log.mtime > mtime)]
        return log_files_response(
            logs, response_type="incremental", base_log_dir=request_log_dir
        )


def parse_log_token(log_token: str) -> Tuple[float, int]:
    # validate basic format
    if log_token.find("-") == -1:
        raise RuntimeError(f"Invalid log token: {log_token}")

    # strip weak etag markers if present
    if log_token.startswith('W/"') and log_token.endswith('"'):
        log_token = log_token[3:-1]

    parts = log_token.split("-", 1)
    return float(parts[0]), int(parts[1])


def log_files_response(
    logs: list[EvalLogInfo],
    response_type: Literal["incremental", "full"],
    base_log_dir: str | None = None,
) -> LogFilesResponse:
    return LogFilesResponse(
        response_type=response_type,
        files=[
            LogHandle(
                name=_normalize_listing_name(base_log_dir, log.name),
                mtime=log.mtime,
                task=log.task,
                task_id=log.task_id,
            )
            for log in logs
        ],
    )


class LogPayload(NamedTuple):
    """An eval log's serialized JSON bytes plus its optional ETag.

    The ETag is populated only when the underlying recorder surfaces one
    (today that means S3-hosted logs). Callers should forward it as an
    HTTP `ETag` response header when present.
    """

    contents: bytes
    etag: str | None


async def get_log_file(file: str, header_only_param: str | None) -> LogPayload:
    """Read a log file and return its JSON bytes plus the optional ETag."""
    # resolve header_only
    header_only_mb = int(header_only_param) if header_only_param is not None else None
    header_only = resolve_header_only(file, header_only_mb)

    log: EvalLog | None = None
    if header_only:
        try:
            log = await read_eval_log_async(file, header_only=True)
        except ValueError as ex:
            logger.info(
                f"Unable to read headers from log file {file}: {ex}. "
                + "The file may include a NaN or Inf value. Falling back to reading entire file."
            )

    if log is None:  # normal read
        log = await read_eval_log_async(file, header_only=False)

    return LogPayload(contents=eval_log_json(log), etag=log.etag)


class LogInProgressError(ValueError):
    """Raised when an edit is attempted on a log whose recorder is still running.

    `EvalLog.status == "started"` means the recorder owns the file and is
    actively appending samples; viewer-driven edits would race that
    write loop. Callers should map this to HTTP 409 (Conflict) so the
    client can distinguish it from validation errors (400) and ETag
    conflicts (412).
    """


async def apply_log_edits(
    file: str,
    update: LogUpdate,
    if_match_etag: str | None = None,
) -> LogPayload:
    """Apply tag/metadata edits to a log and persist them.

    Reads the header, applies `update.edits` via `edit_eval_log`, and writes
    the new header back without touching sample data. Returns the updated
    header serialized as JSON and the new ETag (S3 only — None elsewhere),
    so the caller can both refresh its cached view and chain a follow-up
    conditional edit in a single round-trip.

    Args:
        file: Path or URI of the log to edit.
        update: Edits + provenance to apply.
        if_match_etag: When set on an S3 path, the write is conditional on
            the current S3 ETag matching this value. Raises
            `WriteConflictError` on mismatch. Ignored for non-S3 paths.

    Raises:
        LogInProgressError: If the log's status is "started" (the recorder
            is still running). The caller should surface this as a 409.
    """
    log = await read_eval_log_async(file, header_only=True)
    # Refuse to write while the recorder is still appending — any header
    # we write would race the recorder's own header flush at end-of-eval.
    if log.status == "started":
        raise LogInProgressError(
            "Cannot edit a log while it is in progress. "
            "Wait for the eval to finish (status != 'started'), then try again."
        )
    log = edit_eval_log(log, update.edits, update.provenance)
    await write_eval_log_async(
        log, location=file, if_match_etag=if_match_etag, header_only=True
    )
    # Capture the post-write ETag on S3 via a HEAD — far cheaper than
    # re-parsing the zip header, since we only need the ETag header on
    # the response, not the body. Skipped on local filesystems where
    # there's no ETag concept.
    new_etag: str | None = None
    if filesystem(file).is_s3():
        new_etag = await s3_head_etag(file)
    return LogPayload(contents=eval_log_json(log), etag=new_etag)


async def get_log_size(log_file: str) -> int:
    size, _etag = await _stat_log(log_file)
    return size


async def _stat_log(log_file: str) -> tuple[int, str | None]:
    """One ``fs.info`` call → ``(size, etag)``.

    ETag is populated for S3 paths (where ``_file_info`` lifts it from the
    head_object response) and ``None`` elsewhere. Sharing the call lets
    `get_log_info` surface both fields without a second round-trip.
    """
    fs = filesystem(log_file)
    if fs.is_async():
        info = fs._file_info(await async_connection(log_file)._info(log_file))
    else:
        info = fs.info(log_file)
    return info.size, info.etag


class LogInfo(BaseModel):
    size: int
    direct_url: str | None = None
    # S3 ETag of the log file at the time of this lookup. Used by the
    # viewer client to prime an `If-Match` header on the first edit so
    # concurrent-modification protection covers the initial save, not
    # just chained saves within a session.
    etag: str | None = None


async def get_direct_url(path: str) -> str | None:
    """Return a presigned URL for `path` if it's on S3, else None.

    Swallows exceptions from the presigning path (returns None and logs a
    warning); callers must assume any S3 path can still land `None` here.
    """
    fs = filesystem(path)
    if not fs.is_s3():
        return None
    try:
        connection = async_connection(path)
        # _url is the async variant of url() (fsspec convention)
        url: str = await connection._url(path, expires=3600)
        return url
    except Exception:
        logger.warning(
            f"Failed to generate presigned URL for {path}",
            exc_info=True,
        )
        return None


async def build_pending_sample_urls(
    file: str,
    id: str,
    epoch: int,
    after_event_id: int | None,
    after_attachment_id: int | None,
    after_message_pool_id: int | None,
    after_call_pool_id: int | None,
    max_segments: int | None,
    tail: bool = False,
) -> PendingSampleUrls | None:
    """Build the `/pending-sample-data-urls` response, or None for 404.

    Returns None when the buffer is not filestore-backed (in-process database
    buffer for a running eval, not yet synced), the manifest is missing, or
    the requested sample is not in the manifest. Callers map None to 404.
    """
    buffer = sample_buffer(file)
    if not isinstance(buffer, SampleBufferFilestore):
        return None

    pending = buffer.get_pending_segments(
        id,
        epoch,
        after_event_id=after_event_id,
        after_attachment_id=after_attachment_id,
        after_message_pool_id=after_message_pool_id,
        after_call_pool_id=after_call_pool_id,
        max_segments=max_segments,
        tail=tail,
    )
    if pending is None:
        return None

    direct_urls = await tg_collect(
        [partial(get_direct_url, seg.path) for seg in pending.segments]
    )
    refs = [
        SegmentRef(id=seg.id, member_name=seg.member_name, direct_url=url)
        for seg, url in zip(pending.segments, direct_urls)
    ]

    return PendingSampleUrls(
        segments=refs,
        complete=pending.complete,
        has_more=pending.has_more,
    )


async def get_log_info(
    log_file: str,
    generate_direct_url: bool = False,
) -> LogInfo:
    """Return file size, optional direct URL, and S3 ETag for the log file.

    Args:
        log_file: Path to the log file.
        generate_direct_url: If True and the file is on S3, include a
            presigned URL in the response.
    """
    size, etag = await _stat_log(log_file)
    direct_url = await get_direct_url(log_file) if generate_direct_url else None
    return LogInfo(size=size, direct_url=direct_url, etag=etag)


async def delete_log(log_file: str) -> None:
    fs = filesystem(log_file)
    fs.rm(log_file)


async def get_log_bytes(
    log_file: str, start: int | None = None, end: int | None = None
) -> bytes:
    # fetch bytes
    adjusted_end = end + 1 if end is not None else None
    fs = filesystem(log_file)
    if fs.is_async():
        res: bytes = await async_connection(log_file)._cat_file(
            log_file, start=start, end=adjusted_end
        )
    elif fs.is_local():
        # Read off the event loop via asyncfiles' anyio-backed reader so the
        # read doesn't pin the loop. An open-ended read runs to EOF rather
        # than to a stat'ed size, which would truncate files that grow
        # between stat and read (in-progress evals are rewritten in place).
        res = await AsyncFilesystem().read_file_bytes_fully(
            log_file, start or 0, adjusted_end
        )
    else:
        res = fs.read_bytes(log_file, start, adjusted_end)

    return res


async def stream_log_bytes(
    log_file: str,
    start: int | None = None,
    end: int | None = None,
    log_file_size: int | None = None,
    stream_threshold_bytes: int = 50 * 1024 * 1024,
) -> AsyncIterable[bytes] | BytesIO:
    """Download log bytes with optional streaming for large files.

    Args:
        log_file: The log file to download.
        start: The start byte position to download from.
        end: The end byte position to download to (exclusive).
        log_file_size: The size of the log file, if known.
        stream_threshold_bytes: The threshold size in bytes for streaming.
    """
    if (start is None) != (end is None):
        raise ValueError("start and end must be both specified or both None")

    # fetch bytes
    fs = filesystem(log_file)

    if fs.is_local():
        if start is not None and end is not None:
            request_size = end - start + 1
        elif log_file_size is not None:
            request_size = log_file_size
        else:
            request_size = await get_log_size(log_file)

        # request_size routes buffered-vs-streaming only — it may be a stale
        # stat, so the reads below must run to EOF when open-ended rather
        # than treating it as a byte bound (files grow between stat and
        # read while an eval is in progress).
        if request_size <= stream_threshold_bytes:
            return BytesIO(await get_log_bytes(log_file, start, end))

        # Stream large local files chunked off the event loop rather than
        # buffering them. (Previously this fell through to the S3 path and
        # raised "Expected S3FileSystem" for local files over the threshold.)
        read_start = start or 0
        read_end = end + 1 if end is not None else None

        async def _stream_local() -> AsyncIterable[bytes]:
            byte_stream = await AsyncFilesystem().read_file_bytes(
                log_file, read_start, read_end
            )
            try:
                # pull 1MB per receive: iterating the stream directly uses
                # anyio's 64KB default, i.e. one thread hop per 64KB
                while True:
                    try:
                        yield await byte_stream.receive(_READ_FULLY_CHUNK_SIZE)
                    except EndOfStream:
                        break
            finally:
                await byte_stream.aclose()

        return _stream_local()

    if not fs.is_async() or not fs.is_s3():
        if start is not None and end is not None:
            request_size = end - start + 1
        elif log_file_size is not None:
            request_size = log_file_size
        else:
            request_size = await get_log_size(log_file)

        if request_size <= stream_threshold_bytes:
            # We only implement streaming for s3 and for large files (>50MB):
            bs = await get_log_bytes(log_file, start, end)
            return BytesIO(bs)

    connection = async_connection(log_file)

    if not isinstance(connection, S3FileSystem):
        raise ValueError("Expected S3FileSystem")

    bucket, key, vers = connection.split_path(log_file)

    if start is not None and end is not None:
        head = {"Range": f"bytes={start}-{end}"}
    else:
        head = {}

    async def _call_and_read() -> AsyncIterable[bytes]:
        resp = await connection._call_s3(
            "get_object",
            Bucket=bucket,
            Key=key,
            **version_id_kw(vers),
            **head,
            **connection.req_kw,
        )
        return cast(StreamingBody, resp["Body"])

    return cast(
        StreamingBody, await _error_wrapper(_call_and_read, retries=connection.retries)
    )


async def get_logs(
    request_log_dir: str, recursive: bool, fs_options: dict[str, Any]
) -> LogListingResponse | None:
    # if the log_dir contains the path to a specific file
    # then just return that file
    if is_log_file(request_log_dir, [".json"]):
        file_info = await eval_log_info_async(request_log_dir)
        if file_info is not None:
            return get_log_listing(logs=[file_info], log_dir=dirname(request_log_dir))
        else:
            return None

    # list logs
    logs = await list_eval_logs_async(
        log_dir=request_log_dir, recursive=recursive, fs_options=fs_options
    )
    return get_log_listing(logs, request_log_dir)


def get_log_listing(logs: list[EvalLogInfo], log_dir: str) -> LogListingResponse:
    return LogListingResponse(
        log_dir=aliased_path(log_dir),
        log_dir_uri=log_dir_uri(log_dir),
        files=[
            LogHandle(
                name=normalize_azure_listing_name(log_dir, log.name),
                mtime=log.mtime,
                task=log.task,
                task_id=log.task_id,
            )
            for log in logs
        ],
    )


def log_dir_uri(log_dir: str) -> str | None:
    """Resolve a log dir to the canonical URI namespace of listing file names.

    File names are `unstrip_protocol`-form URIs (e.g. `file:///abs/dir/x.eval`)
    while `log_dir` is echoed in request/display form (relative or `~`-aliased
    for local paths). The viewer scopes its cache by treating names as
    dir-prefixed identities, which requires the dir in the names' namespace.
    Returns None when the path can't be resolved (the viewer then skips
    cache persistence for the scope rather than storing unreachable rows).
    """
    try:
        fs = filesystem(log_dir)
        uri = fs.path_as_uri(fs.fs._strip_protocol(log_dir))
        return normalize_azure_listing_name(log_dir, uri)
    except Exception:
        return None


def _normalize_listing_name(log_dir: str | None, name: str) -> str:
    if log_dir is None:
        return name
    return normalize_azure_listing_name(log_dir, name)


_async_connections: dict[str, AsyncFileSystem] = {}


def async_connection(log_file: str) -> AsyncFileSystem:
    # determine protocol
    protocol, _ = split_protocol(log_file)
    protocol = protocol or "file"

    # create connection if required
    if protocol not in _async_connections.keys():
        _async_connections[protocol] = fsspec.filesystem(
            protocol,
            asynchronous=True,
            loop=asyncio.get_event_loop(),
            **default_fs_options(log_file),
        )

    # return async file-system
    return _async_connections.get(protocol)


@contextlib.asynccontextmanager
async def async_filesystem(
    location: str, fs_options: dict[str, Any] = {}
) -> AsyncIterator[AsyncFileSystem]:
    # determine protocol
    protocol, _ = split_protocol(location)
    protocol = protocol or "file"

    # build options
    options = default_fs_options(location)
    options.update(fs_options)

    if protocol == "s3":
        options["skip_instance_cache"] = True
        s3 = S3FileSystem(asynchronous=True, **options)
        session = await s3.set_session()
        try:
            yield s3
        finally:
            await session.close()
    else:
        options.update({"asynchronous": True, "loop": asyncio.get_event_loop()})
        yield fsspec.filesystem(protocol, **options)


async def list_eval_logs_async(
    log_dir: str = os.environ.get("INSPECT_LOG_DIR", "./logs"),
    formats: list[Literal["eval", "json"]] | None = None,
    recursive: bool = True,
    descending: bool = True,
    fs_options: dict[str, Any] = {},
) -> list[EvalLogInfo]:
    """List all eval logs in a directory.

    Will be async for filesystem providers that support async (e.g. s3, gcs, etc.)
    otherwise will fallback to sync implementation.

    Args:
      log_dir (str): Log directory (defaults to INSPECT_LOG_DIR)
      formats (Literal["eval", "json"]): Formats to list (default
        to listing all formats)
      recursive (bool): List log files recursively (defaults to True).
      descending (bool): List in descending order.
      fs_options (dict[str, Any]): Optional. Additional arguments to pass through
          to the filesystem provider (e.g. `S3FileSystem`).

    Returns:
       List of EvalLog Info.
    """
    # async filesystem if we can
    fs = filesystem(log_dir, fs_options)
    if fs.is_s3() and not fs_options:
        # S3: list via the shared async filesystem (one warm aioboto3 client +
        # connection pool, reused across requests when the view server binds it).
        # iter_files(detail=True) is a single list_objects_v2 sweep that returns
        # FileInfo (name/size/mtime) — no separate existence precheck or per-file
        # stat — and a missing prefix simply yields nothing.
        try:
            async with AsyncFilesystem() as afs:
                logs = [
                    info
                    async for info in afs.iter_files(
                        log_dir, recursive=recursive, detail=True
                    )
                ]
        except ClientError as ex:
            # a missing bucket is an empty listing (as with the existence
            # precheck the other branches perform), not an error
            if ex.response.get("Error", {}).get("Code") in (
                "NoSuchBucket",
                "404",
                "NotFound",
            ):
                return []
            raise
        # resolve to eval logs (async fan-out so header reads on
        # non-conforming filenames don't block the event loop)
        return await log_files_from_ls_async(logs, formats, descending)
    elif fs.is_async():
        async with async_filesystem(log_dir, fs_options=fs_options) as async_fs:
            # Attempt existence check with robust handling for Azure-style auth issues.
            try:
                exists = await async_fs._exists(log_dir)
            except Exception as ex:  # noqa: BLE001
                if should_suppress_azure_error(log_dir, ex):
                    logger.warning(azure_warning_hint(log_dir, ex))
                    exists = True
                else:
                    # TODO: Add S3 login error catching, as well as any other remote file system of interest
                    # Re-raise non-auth related issues
                    raise

            if exists:
                # prevent caching of listings
                async_fs.invalidate_cache(log_dir)
                # list logs
                if recursive:
                    if _walk_supports_detail(async_fs):
                        files = await _walk_with_detail(async_fs, log_dir)
                    else:
                        files = await _walk_without_detail(async_fs, log_dir)
                else:
                    files = cast(
                        list[dict[str, Any]],
                        await async_fs._ls(log_dir, detail=True),
                    )
                logs = [fs._file_info(file) for file in files]
                # resolve to eval logs (async fan-out so header reads on
                # non-conforming filenames don't block the event loop)
                return await log_files_from_ls_async(logs, formats, descending)
            else:
                return []
    else:
        # sync filesystem (e.g. local) — run the existence check and the
        # (potentially large recursive) listing in a worker thread so they
        # don't block the event loop
        if not await anyio.to_thread.run_sync(fs.exists, log_dir):
            return []
        logs = await anyio.to_thread.run_sync(
            partial(fs.ls, log_dir, recursive=recursive)
        )
        return await log_files_from_ls_async(logs, formats, descending)


def resolve_header_only(path: str, header_only: int | None) -> bool:
    # if there is a max_size passed, respect that and switch to
    # header_only mode if the file is too large
    if header_only == 0:
        return True
    if header_only is not None and size_in_mb(path) > int(header_only):
        return True
    else:
        return False


async def eval_log_info_async(
    log_file: str,
    fs_options: dict[str, Any] = {},
) -> EvalLogInfo | None:
    """Get EvalLogInfo for a specific log file asynchronously.

    Args:
        log_file (str): The complete path to the log file
        fs_options (dict[str, Any]): Optional. Additional arguments to pass through

    Returns:
        EvalLogInfo or None: The EvalLogInfo object if the file exists and is valid, otherwise None.
    """
    fs = filesystem(log_file, fs_options)
    if fs.exists(log_file):
        info = fs.info(log_file)
        return await log_file_info_async(info)
    else:
        return None


def aliased_path(path: str) -> str:
    home_dir = os.path.expanduser("~")
    if path.startswith(home_dir):
        return path.replace(home_dir, "~", 1)
    else:
        return path


def _walk_supports_detail(fs: AsyncFileSystem) -> bool:
    walk = getattr(fs, "_walk", None)
    if walk is None:
        return False
    try:
        signature = inspect.signature(walk)
    except (TypeError, ValueError):
        return False
    parameter = signature.parameters.get("detail")
    if parameter is None:
        return False
    return parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )


async def _walk_with_detail(fs: AsyncFileSystem, log_dir: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    async for _, _, filenames in fs._walk(log_dir, detail=True):
        files.extend(filenames.values())
    return files


async def _walk_without_detail(
    fs: AsyncFileSystem, log_dir: str
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    stack: list[str] = [log_dir]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        try:
            entries = await fs._ls(current, detail=True)
        except Exception:
            continue
        for entry in entries:
            name = entry.get("name") or entry.get("path")
            if not name:
                continue
            files.append(entry)
            entry_type = entry.get("type")
            if (entry_type == "directory" or name.endswith("/")) and name not in seen:
                seen.add(name)
                stack.append(name)
    return files
