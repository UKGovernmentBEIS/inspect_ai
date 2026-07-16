from __future__ import annotations

import functools
import io
import logging
import shutil
import time
from contextlib import AbstractAsyncContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from fnmatch import fnmatchcase
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    BinaryIO,
    Callable,
    Coroutine,
    Iterator,
    Literal,
    NamedTuple,
    TypeVar,
    cast,
    overload,
)
from urllib.parse import urlparse

import anyio
import anyio.to_thread
from anyio import AsyncFile, EndOfStream, open_file
from anyio.abc import ByteReceiveStream
from botocore.exceptions import ClientError
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from typing_extensions import TYPE_CHECKING, override

if TYPE_CHECKING:
    from aiobotocore.response import StreamingBody
    from boto3.s3.transfer import TransferConfig

from inspect_ai._util._async import current_async_backend
from inspect_ai._util.constants import HTTP
from inspect_ai._util.file import FileInfo, file, filesystem, local_path

logger = logging.getLogger(__name__)


class _BytesByteReceiveStream(ByteReceiveStream):
    """
    Adapt bytes into an AnyIO ByteReceiveStream

    This adapter is needed when using sync S3 under Trio
    """

    def __init__(self, data: bytes, chunk_size: int = 1024 * 1024):
        """Initialize with bytes data and chunk size (default 1MB)."""
        self._data = data
        self._chunk_size = chunk_size
        self._position = 0

    async def receive(self, max_bytes: int = 65536) -> bytes:
        """Receive up to max_bytes from the stream."""
        if self._position >= len(self._data):
            raise EndOfStream

        # Use the smaller of max_bytes or remaining data
        end = min(self._position + max_bytes, len(self._data))
        chunk = self._data[self._position : end]
        self._position = end
        return chunk

    async def aclose(self) -> None:
        """Close the stream."""
        pass


class _StreamingBodyByteReceiveStream(ByteReceiveStream):
    """
    Adapt AioBoto's StreamingBody into an AnyIO ByteReceiveStream

    This adapter is needed when using async S3 under asyncio
    """

    def __init__(self, body: StreamingBody):
        """Initialize with S3 response body stream."""
        self._body = body

    async def receive(self, max_bytes: int = 65536) -> bytes:
        """Receive up to max_bytes from the S3 body stream."""
        # TODO: It's kind of lame that we're forced to provide an arbitrary max_bytes
        # It would be preferable if we could just read whatever is naturally in
        # the http response buffer
        chunk = await self._body.read(max_bytes)
        if not chunk:
            raise EndOfStream
        return chunk

    async def aclose(self) -> None:
        """Close the underlying S3 body stream."""
        self._body.close()


class _AnyIOFileByteReceiveStream(ByteReceiveStream):
    """
    Adapt a file's contents into an AnyIO ByteReceiveStream

    This adapter is needed when reading files.

    NOTE: This class does not support concurrent calls to receive.
    """

    def __init__(self, filename: str, start: int, end: int):
        """Initialize with file path and byte range."""
        self._filename = filename
        self._start = start
        self._end = end
        self._position = start
        self._file: AsyncFile[bytes] | None = None

    async def receive(self, max_bytes: int = 65536) -> bytes:
        """Receive up to max_bytes from the file."""
        if self._file is None:
            self._file = await open_file(self._filename, "rb")
            await self._file.seek(self._start)

        if self._position >= self._end or not (
            chunk := await self._file.read(min(max_bytes, self._end - self._position))
        ):
            raise EndOfStream

        self._position += len(chunk)

        return chunk

    async def aclose(self) -> None:
        """Close the file if it was opened."""
        if self._file is not None:
            await self._file.aclose()
            self._file = None


@dataclass
class SuffixResult:
    """Result of reading the suffix of a file."""

    data: bytes
    file_size: int
    etag: str | None = None


class _RetiredClient(NamedTuple):
    """An async S3 client rotated out by `client_ttl`, awaiting closure."""

    client: Any
    retired_at: float


class AsyncFilesystem(AbstractAsyncContextManager["AsyncFilesystem"]):
    """Interface for reading/writing files that uses different interfaces depending on context

    1. Use aioboto3 when accessing s3 under the asyncio backend
    2. Use boto3 with anyio.to_thread when using s3 under the trio backend
    3. Use fsspec when using any other filesystem

    When used as a context manager, the filesystem is registered in a ContextVar
    so that it is shared with all downstream code within the same async context.
    If a shared filesystem already exists, the context manager reuses it and does
    not close it on exit (the original owner handles cleanup).
    """

    def __init__(
        self,
        anonymous: bool = False,
        region_name: str | None = None,
        client_ttl: float | None = None,
    ) -> None:
        """Initialize the filesystem.

        Args:
            anonymous: Use unsigned (anonymous) S3 requests.
            region_name: AWS region for the S3 client.
            client_ttl: Recreate the cached async S3 client when it is older
                than this many seconds, so that externally rotated static
                credentials (e.g. tooling that rewrites ~/.aws/credentials)
                get picked up without a restart — botocore only auto-refreshes
                provider-based credentials (STS/SSO/IMDS); static keys are
                pinned at client creation. None (the default) never recreates;
                intended for long-lived instances such as the view server's
                shared filesystem.
        """
        self._anonymous = anonymous
        self._region_name = region_name
        self._client_ttl = client_ttl
        self._s3_client: Any | None = None
        self._s3_client_async: Any | None = None
        self._s3_client_async_created: float = 0.0
        self._s3_clients_retired: list[_RetiredClient] = []
        self._s3_lock = anyio.Lock()
        self._owns_context: bool = False

    async def get_size(self, filename: str) -> int:
        return (await self.info(filename)).size

    async def info(self, filename: str) -> FileInfo:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                response = await (await self.s3_client_async()).head_object(
                    Bucket=bucket, Key=key
                )
                return _s3_head_to_file_info(filename, response)
            return await anyio.to_thread.run_sync(
                s3_info, self.s3_client(), bucket, key, filename
            )
        else:
            return filesystem(filename).info(filename)

    async def exists(self, filename: str) -> bool:
        """Return True if `filename` exists, False otherwise."""
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                from botocore.exceptions import ClientError

                try:
                    await (await self.s3_client_async()).head_object(
                        Bucket=bucket, Key=key
                    )
                    return True
                except ClientError as e:
                    if e.response.get("Error", {}).get("Code") in (
                        "404",
                        "NoSuchKey",
                        "NotFound",
                    ):
                        return False
                    raise
            return await anyio.to_thread.run_sync(
                s3_exists, self.s3_client(), bucket, key
            )
        else:
            return filesystem(filename).exists(filename)

    async def read_file(self, filename: str) -> bytes:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                response = await (await self.s3_client_async()).get_object(
                    Bucket=bucket, Key=key
                )
                body = response["Body"]
                try:
                    return cast(bytes, await body.read())
                finally:
                    body.close()

            else:
                return await anyio.to_thread.run_sync(
                    s3_read_file, self.s3_client(), bucket, key
                )
        else:
            with file(filename, "rb") as f:
                return f.read()

    async def read_file_bytes(
        self, filename: str, start: int, end: int
    ) -> ByteReceiveStream:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                response = await (await self.s3_client_async()).get_object(
                    Bucket=bucket, Key=key, Range=f"bytes={start}-{end - 1}"
                )
                return _StreamingBodyByteReceiveStream(response["Body"])
            return _BytesByteReceiveStream(
                await anyio.to_thread.run_sync(
                    s3_read_file_bytes, self.s3_client(), bucket, key, start, end
                )
            )
        else:
            fs = filesystem(filename)
            if fs.is_local():
                # If local, use AnyIO's async/chunking file reading support
                return _AnyIOFileByteReceiveStream(local_path(filename), start, end)
            with file(filename, "rb") as f:
                f.seek(start)
                return _BytesByteReceiveStream(f.read(end - start))

    async def read_file_bytes_fully(self, filename: str, start: int, end: int) -> bytes:
        """Read a byte range from a file and consume the stream fully into bytes."""
        stream = await self.read_file_bytes(filename, start, end)
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        return b"".join(chunks)

    async def read_file_suffix(self, filename: str, suffix_length: int) -> SuffixResult:
        """Read the last suffix_length bytes of a file.

        Uses a suffix range request (``bytes=-N``) to avoid a separate
        HEAD request for the file size.

        Returns:
            SuffixResult with data, file_size, and etag (S3 only).
        """
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                response = await (await self.s3_client_async()).get_object(
                    Bucket=bucket, Key=key, Range=f"bytes=-{suffix_length}"
                )
                content_range: str = response["ContentRange"]
                total_size = int(content_range.split("/")[-1])
                etag_raw = response.get("ETag")
                etag = cast(str, etag_raw).strip('"') if etag_raw else None
                body = response["Body"]
                try:
                    data = cast(bytes, await body.read())
                finally:
                    body.close()
                return SuffixResult(data, total_size, etag)
            else:
                return await anyio.to_thread.run_sync(
                    s3_read_file_suffix,
                    self.s3_client(),
                    bucket,
                    key,
                    suffix_length,
                )
        else:
            file_size = filesystem(filename).info(filename).size
            start = max(0, file_size - suffix_length)
            data = await self.read_file_bytes_fully(filename, start, file_size)
            return SuffixResult(data, file_size)

    async def write_file(self, filename: str, content: bytes) -> None:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)

            async def do_put() -> None:
                if current_async_backend() == "asyncio":
                    client = await self.s3_client_async()
                    await client.upload_fileobj(
                        Fileobj=io.BytesIO(content), Bucket=bucket, Key=key
                    )
                else:
                    await anyio.to_thread.run_sync(
                        s3_write_file, self.s3_client(), bucket, key, content
                    )

            await _s3_put_with_retry(do_put, location=filename)
        else:
            with file(filename, "wb") as f:
                f.write(content)

    async def write_file_streaming(self, filename: str, source: BinaryIO) -> None:
        """Write a file from a binary stream without reading it all into memory.

        Uses the appropriate backend for streaming writes:
        - S3: native upload_fileobj with TransferConfig for multipart chunking
        - Local/other: chunked copy via fsspec with explicit block_size

        Args:
            filename: Destination file path or URL.
            source: A readable binary file-like object.
        """
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)

            try:
                # Only retry streams we can replay exactly from their current offset.
                # Non-seekable streams use one upload attempt because a retry after a
                # partial read could otherwise write a truncated object.
                start = source.tell() if source.seekable() else None
                if start is not None:
                    source.seek(start)
            except (AttributeError, OSError):
                start = None

            async def do_put() -> None:
                if start is not None:
                    source.seek(start)
                if current_async_backend() == "asyncio":
                    client = await self.s3_client_async()
                    await client.upload_fileobj(
                        Fileobj=source,
                        Bucket=bucket,
                        Key=key,
                        Config=_s3_transfer_config(),
                    )
                else:
                    await anyio.to_thread.run_sync(
                        s3_write_file_streaming,
                        self.s3_client(),
                        bucket,
                        key,
                        source,
                    )

            if start is None:
                await do_put()
            else:
                await _s3_put_with_retry(do_put, location=filename)
        else:
            with file(
                filename, "wb", fs_options={"block_size": _FSSPEC_WRITE_BLOCK_SIZE}
            ) as f:
                shutil.copyfileobj(source, f, length=_STREAMING_COPY_BUFSIZE)

    async def get_file(self, remote: str, local: str) -> None:
        """Download `remote` to local path `local`."""
        if is_s3_filename(remote):
            bucket, key = s3_bucket_and_key(remote)
            if current_async_backend() == "asyncio":
                client = await self.s3_client_async()
                await client.download_file(Bucket=bucket, Key=key, Filename=local)
            else:
                await anyio.to_thread.run_sync(
                    s3_get_file, self.s3_client(), bucket, key, local
                )
        else:
            filesystem(remote).get_file(remote, local)

    @overload
    def iter_files(
        self,
        base: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        detail: Literal[False] = False,
    ) -> AsyncIterator[str]: ...

    @overload
    def iter_files(
        self,
        base: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        detail: Literal[True],
    ) -> AsyncIterator[FileInfo]: ...

    async def iter_files(
        self,
        base: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        detail: bool = False,
    ) -> AsyncIterator[str | FileInfo]:
        """Yield files under `base` — URIs, or `FileInfo` when ``detail=True``.

        Matching is fnmatch-on-basename (case-sensitive). When `recursive`
        is False, only direct children of `base` are considered; otherwise
        any file at any depth under `base` is considered.

        The `pattern` argument matches the basename only; it must not
        contain `/`. With ``detail=True`` each match is a `FileInfo`
        (name/size/mtime/etag) built from metadata the listing already
        returns — no extra stat calls.
        """
        if is_s3_filename(base):
            bucket, prefix = s3_bucket_and_key(base)
            prefix = prefix.rstrip("/") + "/" if prefix else ""
            if current_async_backend() == "asyncio":
                client = await self.s3_client_async()
                paginator = client.get_paginator("list_objects_v2")
                kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
                if not recursive:
                    kwargs["Delimiter"] = "/"
                async for page in paginator.paginate(**kwargs):
                    for obj in page.get("Contents", []):
                        if fnmatchcase(obj["Key"].rsplit("/", 1)[-1], pattern):
                            yield (
                                _s3_obj_to_file_info(bucket, obj)
                                if detail
                                else f"s3://{bucket}/{obj['Key']}"
                            )
            else:
                results = await anyio.to_thread.run_sync(
                    s3_iter_files,
                    self.s3_client(),
                    bucket,
                    prefix,
                    pattern,
                    recursive,
                    detail,
                )
                for r in results:
                    yield r
        else:
            fsw = filesystem(base)
            fs = fsw.fs
            if recursive:
                if detail:
                    found = fs.find(base, detail=True)
                    for path, info in found.items():
                        if fnmatchcase(path.rsplit("/", 1)[-1], pattern):
                            yield fsw._file_info(info)
                else:
                    paths = fs.find(base)
                    if isinstance(paths, dict):
                        paths = list(paths.keys())
                    for path in paths:
                        if fnmatchcase(path.rsplit("/", 1)[-1], pattern):
                            yield path
            else:
                for entry in fs.ls(base, detail=True):
                    if entry["type"] == "file":
                        name = entry["name"]
                        if fnmatchcase(name.rsplit("/", 1)[-1], pattern):
                            yield fsw._file_info(entry) if detail else name

    async def iter_dirs(
        self, base: str, pattern: str = "*", *, recursive: bool = False
    ) -> AsyncIterator[str]:
        """Yield URIs (ending in `/`) of directory-like entries under `base`.

        Matching is fnmatch-on-terminal-name (case-sensitive). When
        `recursive` is False, only direct subdirectories of `base` are
        considered; otherwise matching directories at any depth are
        yielded once (deduplicated).

        The `pattern` argument matches the terminal name only; it must
        not contain `/`.
        """
        if is_s3_filename(base):
            bucket, prefix = s3_bucket_and_key(base)
            prefix = prefix.rstrip("/") + "/" if prefix else ""
            if current_async_backend() == "asyncio":
                client = await self.s3_client_async()
                paginator = client.get_paginator("list_objects_v2")
                if not recursive:
                    async for page in paginator.paginate(
                        Bucket=bucket, Prefix=prefix, Delimiter="/"
                    ):
                        for cp in page.get("CommonPrefixes", []):
                            cp_key = cp["Prefix"]
                            name = cp_key.rstrip("/").rsplit("/", 1)[-1]
                            if fnmatchcase(name, pattern):
                                yield f"s3://{bucket}/{cp_key}"
                else:
                    base_depth = len(prefix.rstrip("/").split("/")) if prefix else 0
                    seen: set[str] = set()
                    async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                        for obj in page.get("Contents", []):
                            key = obj["Key"]
                            parts = key.split("/")
                            for i in range(base_depth, len(parts) - 1):
                                if fnmatchcase(parts[i], pattern):
                                    dir_path = "/".join(parts[: i + 1])
                                    if dir_path not in seen:
                                        seen.add(dir_path)
                                        yield f"s3://{bucket}/{dir_path}/"
            else:
                results = await anyio.to_thread.run_sync(
                    s3_iter_dirs,
                    self.s3_client(),
                    bucket,
                    prefix,
                    pattern,
                    recursive,
                )
                for r in results:
                    yield r
        else:
            fs = filesystem(base).fs
            if not recursive:
                for entry in fs.ls(base, detail=True):
                    if entry["type"] == "directory":
                        name = entry["name"]
                        terminal = name.rstrip("/").rsplit("/", 1)[-1]
                        if fnmatchcase(terminal, pattern):
                            yield name.rstrip("/") + "/"
            else:
                for dirpath, dirnames, _ in fs.walk(base):
                    for dirname in dirnames:
                        if fnmatchcase(dirname, pattern):
                            yield f"{dirpath.rstrip('/')}/{dirname}/"

    @override
    async def __aenter__(self) -> "AsyncFilesystem":
        existing = _current_async_fs.get()
        if existing is not None:
            self._owns_context = False
            return existing
        self._owns_context = True
        _current_async_fs.set(self)
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._owns_context:
            _current_async_fs.set(None)
            await self.close()

    async def close(
        self,
    ) -> None:
        clients = [retired.client for retired in self._s3_clients_retired]
        if self._s3_client_async is not None:
            clients.append(self._s3_client_async)
        self._s3_client_async = None
        self._s3_clients_retired = []
        for client in clients:
            await client.__aexit__(None, None, None)

    def s3_client(self) -> Any:
        if self._s3_client is None:
            import boto3
            from botocore import UNSIGNED
            from botocore.config import Config

            config = Config(
                max_pool_connections=50,
                retries={"max_attempts": 10, "mode": "adaptive"},
                # Disable boto3 1.36+ default integrity checksums.
                # The AwsChunkedWrapper body framing is buggy under
                # concurrent multipart uploads and intermittently
                # produces IncompleteBody from S3. See GH-3858.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                **({"signature_version": UNSIGNED} if self._anonymous else {}),
            )
            self._s3_client = boto3.client(
                "s3", config=config, region_name=self._region_name
            )

        return self._s3_client

    async def s3_client_async(self) -> Any:
        def expired() -> bool:
            if self._s3_client_async is None:
                return True
            return (
                self._client_ttl is not None
                and time.monotonic() - self._s3_client_async_created > self._client_ttl
            )

        if expired():
            async with self._s3_lock:
                if expired():
                    if self._s3_client_async is not None:
                        # retired, not closed: in-flight operations may still
                        # hold a reference to it; closed once a full client_ttl
                        # has passed (below, on a later rotation) or in close()
                        self._s3_clients_retired.append(
                            _RetiredClient(self._s3_client_async, time.monotonic())
                        )
                        self._s3_client_async = None
                    client = await self._create_s3_client_async(
                        anonymous=self._anonymous,
                        region_name=self._region_name,
                    )
                    self._s3_client_async = client
                    self._s3_client_async_created = time.monotonic()
                    if self._s3_clients_retired:
                        await self._close_retired_clients_past_grace()
        return self._s3_client_async

    async def _close_retired_clients_past_grace(self) -> None:
        """Close retired clients that have aged past the reuse-safety grace.

        The grace period is one `client_ttl`: an operation still streaming
        through a retired client when it was rotated out gets at least a full
        TTL to finish before the client can be closed under it. Called only
        from `s3_client_async` while holding `_s3_lock`, so rotations (the
        only producer of retirees) and reaping never interleave.
        """
        assert self._client_ttl is not None
        now = time.monotonic()
        due = [
            retired
            for retired in self._s3_clients_retired
            if now - retired.retired_at > self._client_ttl
        ]
        if due:
            self._s3_clients_retired = [
                retired
                for retired in self._s3_clients_retired
                if now - retired.retired_at <= self._client_ttl
            ]
            for retired in due:
                try:
                    await retired.client.__aexit__(None, None, None)
                except Exception:
                    logger.warning("Error closing retired S3 client", exc_info=True)

    @staticmethod
    async def _create_s3_client_async(
        anonymous: bool = False, region_name: str | None = None
    ) -> Any:
        import aioboto3
        from aiobotocore.config import AioConfig
        from botocore import UNSIGNED

        session = aioboto3.Session()
        config = AioConfig(
            max_pool_connections=50,
            retries={"max_attempts": 10, "mode": "adaptive"},
            # Disable boto3 1.36+ default integrity checksums.
            # The AwsChunkedWrapper body framing is buggy under
            # concurrent multipart uploads and intermittently
            # produces IncompleteBody from S3. See GH-3858.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            **({"signature_version": UNSIGNED} if anonymous else {}),
        )
        return await session.client(
            "s3", config=config, region_name=region_name
        ).__aenter__()


def _s3_head_to_file_info(filename: str, response: dict[str, Any]) -> FileInfo:
    size = cast(int, response["ContentLength"])
    last_modified = response.get("LastModified")
    mtime = last_modified.timestamp() * 1000 if last_modified else None
    etag_raw = response.get("ETag")
    etag = cast(str, etag_raw).strip('"') if etag_raw else None
    return FileInfo(name=filename, type="file", size=size, mtime=mtime, etag=etag)


def _s3_obj_to_file_info(bucket: str, obj: dict[str, Any]) -> FileInfo:
    """Build a FileInfo from a `list_objects_v2` `Contents` entry.

    Mirrors `FileSystem._file_info`: name is the full `s3://` URI and mtime is
    `LastModified` in milliseconds, so listings match the fsspec-built path.
    """
    last_modified = obj.get("LastModified")
    mtime = last_modified.timestamp() * 1000 if last_modified else None
    etag_raw = obj.get("ETag")
    etag = cast(str, etag_raw).strip('"') if etag_raw else None
    return FileInfo(
        name=f"s3://{bucket}/{obj['Key']}",
        type="file",
        size=cast(int, obj.get("Size", 0)),
        mtime=mtime,
        etag=etag,
    )


def s3_info(s3: Any, bucket: str, key: str, filename: str) -> FileInfo:
    response = s3.head_object(Bucket=bucket, Key=key)
    return _s3_head_to_file_info(filename, response)


def s3_read_file(s3: Any, bucket: str, key: str) -> bytes:
    response = s3.get_object(Bucket=bucket, Key=key)
    return cast(bytes, response["Body"].read())


def s3_read_file_bytes(s3: Any, bucket: str, key: str, start: int, end: int) -> bytes:
    range_header = f"bytes={start}-{end - 1}"
    response = s3.get_object(Bucket=bucket, Key=key, Range=range_header)
    return cast(bytes, response["Body"].read())


def s3_read_file_suffix(
    s3: Any, bucket: str, key: str, suffix_length: int
) -> SuffixResult:
    response = s3.get_object(Bucket=bucket, Key=key, Range=f"bytes=-{suffix_length}")
    content_range: str = response["ContentRange"]
    total_size = int(content_range.split("/")[-1])
    etag_raw = response.get("ETag")
    etag = cast(str, etag_raw).strip('"') if etag_raw else None
    data = cast(bytes, response["Body"].read())
    return SuffixResult(data, total_size, etag)


def s3_write_file(s3: Any, bucket: str, key: str, content: bytes) -> None:
    s3.upload_fileobj(Fileobj=io.BytesIO(content), Bucket=bucket, Key=key)


def s3_write_file_streaming(s3: Any, bucket: str, key: str, source: BinaryIO) -> None:
    """Upload a file-like stream to S3 using multipart upload."""
    s3.upload_fileobj(
        Fileobj=source, Bucket=bucket, Key=key, Config=_s3_transfer_config()
    )


def _is_stale_signature_error(ex: BaseException) -> bool:
    return (
        isinstance(ex, ClientError)
        and ex.response.get("Error", {}).get("Code") == "RequestTimeTooSkewed"
    )


def _log_s3_retry_attempt(location: str) -> Callable[[RetryCallState], None]:
    def log_attempt(retry_state: RetryCallState) -> None:
        from inspect_ai._util.retry import report_http_retry, sample_context_prefix

        ex = retry_state.outcome.exception() if retry_state.outcome else None
        request_id = ""
        if isinstance(ex, ClientError):
            request_id = ex.response.get("ResponseMetadata", {}).get("RequestId", "")

        report_http_retry("transient")
        logger.log(
            HTTP,
            "%sS3 write to %s hit RequestTimeTooSkewed on attempt %d; "
            "retrying in %.0fs (request id %s)",
            sample_context_prefix(),
            location,
            retry_state.attempt_number,
            retry_state.upcoming_sleep,
            request_id or "unknown",
        )

    return log_attempt


async def _s3_put_with_retry(
    do_put: Callable[[], Coroutine[Any, Any, None]], *, location: str
) -> None:
    # bound by attempt count only (each attempt re-signs the request). A
    # wall-clock stop (stop_after_delay) is exactly wrong for this error:
    # a stale signature means the attempt itself was delayed (e.g. queued
    # behind a starved connection pool for 15+ minutes), so a single slow
    # failure would exhaust the budget and the write would never be retried
    # with a fresh signature.
    async for attempt in AsyncRetrying(
        retry=retry_if_exception(_is_stale_signature_error),
        wait=wait_exponential_jitter(),
        stop=stop_after_attempt(5),
        sleep=anyio.sleep,
        before_sleep=_log_s3_retry_attempt(location),
        reraise=True,
    ):
        with attempt:
            await do_put()


def s3_get_file(s3: Any, bucket: str, key: str, filename: str) -> None:
    s3.download_file(Bucket=bucket, Key=key, Filename=filename)


def s3_iter_files(
    s3: Any,
    bucket: str,
    prefix: str,
    pattern: str,
    recursive: bool,
    detail: bool = False,
) -> list[str | FileInfo]:
    paginator = s3.get_paginator("list_objects_v2")
    kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
    if not recursive:
        kwargs["Delimiter"] = "/"
    results: list[str | FileInfo] = []
    for page in paginator.paginate(**kwargs):
        for obj in page.get("Contents", []):
            if fnmatchcase(obj["Key"].rsplit("/", 1)[-1], pattern):
                results.append(
                    _s3_obj_to_file_info(bucket, obj)
                    if detail
                    else f"s3://{bucket}/{obj['Key']}"
                )
    return results


def s3_iter_dirs(
    s3: Any, bucket: str, prefix: str, pattern: str, recursive: bool
) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    results: list[str] = []
    if not recursive:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                cp_key = cp["Prefix"]
                name = cp_key.rstrip("/").rsplit("/", 1)[-1]
                if fnmatchcase(name, pattern):
                    results.append(f"s3://{bucket}/{cp_key}")
    else:
        base_depth = len(prefix.rstrip("/").split("/")) if prefix else 0
        seen: set[str] = set()
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                parts = key.split("/")
                for i in range(base_depth, len(parts) - 1):
                    if fnmatchcase(parts[i], pattern):
                        dir_path = "/".join(parts[: i + 1])
                        if dir_path not in seen:
                            seen.add(dir_path)
                            results.append(f"s3://{bucket}/{dir_path}/")
    return results


def s3_exists(s3: Any, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def s3_bucket_and_key(filename: str) -> tuple[str, str]:
    parsed = urlparse(filename)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def is_s3_filename(filename: str) -> bool:
    return filename.startswith("s3://")


_current_async_fs: ContextVar[AsyncFilesystem | None] = ContextVar(
    "_current_async_fs", default=None
)


_T = TypeVar("_T")


def with_async_fs(
    main: Callable[[], Coroutine[Any, Any, _T]],
) -> Callable[[], Coroutine[Any, Any, _T]]:
    """Wrap an async callable so it runs with a shared AsyncFilesystem."""

    async def wrapper() -> _T:
        async with AsyncFilesystem():
            return await main()

    return wrapper


def get_async_filesystem() -> AsyncFilesystem:
    """Get the current shared AsyncFilesystem from the ContextVar.

    Raises:
        RuntimeError: If no AsyncFilesystem has been established via
            ``async with AsyncFilesystem()``.
    """
    fs = _current_async_fs.get()
    if fs is None:
        raise RuntimeError(
            "No AsyncFilesystem is available. "
            "Use 'async with AsyncFilesystem()' to establish one."
        )
    return fs


@contextmanager
def bind_async_filesystem(fs: AsyncFilesystem) -> Iterator[None]:
    """Bind `fs` as the shared AsyncFilesystem for the current context.

    Unlike ``async with AsyncFilesystem()``, this neither creates nor closes a
    filesystem — the caller owns ``fs``'s lifecycle. Within the bound scope (and
    any child tasks that inherit the context), ``get_async_filesystem()`` and
    ``async with AsyncFilesystem()`` reuse ``fs``, so downstream S3 access shares
    its client and connection pool.

    Intended for binding a single long-lived, pre-warmed filesystem around a
    unit of work — e.g. per-request in ASGI middleware — so reads don't re-pay
    client/connection setup. Safe to nest; the previous binding is restored on
    exit.
    """
    token = _current_async_fs.set(fs)
    try:
        yield
    finally:
        _current_async_fs.reset(token)


@functools.cache
def _s3_transfer_config() -> TransferConfig:
    # boto3 S3 multipart upload configuration for streaming writes.
    # Values are the boto3.s3.transfer.TransferConfig library defaults
    # as of 2026-03-07.
    # - multipart_threshold: use multipart upload for files larger than this
    # - multipart_chunksize: size of each part in a multipart upload
    # - max_concurrency: maximum threads for concurrent part uploads
    from boto3.s3.transfer import TransferConfig

    return TransferConfig(
        multipart_threshold=8 * 1024 * 1024,  # 8 MB
        multipart_chunksize=8 * 1024 * 1024,  # 8 MB
        max_concurrency=10,
    )


# fsspec write buffer size for cloud storage backends (GCS, Azure, etc.).
# 4MB is the fsspec AbstractFileSystem.blocksize library default
# as of 2026-03-07. We set to 8 MB to match boto3 values above.
# When the in-memory write buffer reaches this size, it is flushed as
# a multipart upload part. Individual backends may override this class
# attribute with a different default.
_FSSPEC_WRITE_BLOCK_SIZE = 8 * 1024 * 1024  # 8 MB

# Size of chunks read from the source stream per iteration when
# copying to local or fsspec-backed files via shutil.copyfileobj.
_STREAMING_COPY_BUFSIZE = 16 * 1024 * 1024  # 16 MB
