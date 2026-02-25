from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from functools import partial
from types import TracebackType
from typing import Any, Awaitable, Callable, Iterable, TypeVar, cast
from urllib.parse import urlparse

import anyio.to_thread
import boto3
from aiobotocore.config import AioConfig
from aiobotocore.response import StreamingBody
from anyio import AsyncFile, EndOfStream, open_file
from anyio.abc import ByteReceiveStream
from botocore.config import Config
from typing_extensions import override

from inspect_ai._util._async import current_async_backend, run_coroutine, tg_collect
from inspect_ai._util.file import FileInfo, file, filesystem


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


class AsyncFilesystem(AbstractAsyncContextManager["AsyncFilesystem"]):
    """Interface for reading/writing files that uses different interfaces depending on context

    1. Use aioboto3 when accessing s3 under the asyncio backend
    2. Use boto3 with anyio.to_thread when using s3 under the trio backend
    3. Use fsspec when using any other filesystem

    Call close() when finished with the filesystem (or use it as a context manager)
    """

    _s3_client: Any | None = None
    _s3_client_async: Any | None = None

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
                return _AnyIOFileByteReceiveStream(_local_path(filename), start, end)
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
            if current_async_backend() == "asyncio":
                await (await self.s3_client_async()).put_object(
                    Bucket=bucket, Key=key, Body=content
                )
            else:
                await anyio.to_thread.run_sync(
                    s3_write_file, self.s3_client(), bucket, key, content
                )
        else:
            with file(filename, "wb") as f:
                f.write(content)

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(
        self,
    ) -> None:
        if self._s3_client_async is not None:
            await self._s3_client_async.__aexit__(None, None, None)
            self._s3_client_async = None

    def s3_client(self) -> Any:
        if self._s3_client is None:
            config = Config(
                max_pool_connections=50,
                retries={"max_attempts": 10, "mode": "adaptive"},
            )
            self._s3_client = boto3.client("s3", config=config)

        return self._s3_client

    async def s3_client_async(self) -> Any:
        if self._s3_client_async is None:
            import aioboto3

            session = aioboto3.Session()
            config = AioConfig(
                max_pool_connections=50,
                retries={"max_attempts": 10, "mode": "adaptive"},
            )
            self._s3_client_async = await session.client(
                "s3", config=config
            ).__aenter__()

        return self._s3_client_async


def _s3_head_to_file_info(filename: str, response: dict[str, Any]) -> FileInfo:
    size = cast(int, response["ContentLength"])
    last_modified = response.get("LastModified")
    mtime = last_modified.timestamp() * 1000 if last_modified else None
    etag_raw = response.get("ETag")
    etag = cast(str, etag_raw).strip('"') if etag_raw else None
    return FileInfo(name=filename, type="file", size=size, mtime=mtime, etag=etag)


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
    s3.put_object(Bucket=bucket, Key=key, Body=content)


def s3_bucket_and_key(filename: str) -> tuple[str, str]:
    parsed = urlparse(filename)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def is_s3_filename(filename: str) -> bool:
    return filename.startswith("s3://")


def _local_path(filename: str) -> str:
    """Convert a file:// URL to a local path, or return as-is."""
    if filename.startswith("file://"):
        return urlparse(filename).path
    return filename


R = TypeVar("R")


async def tg_collect_with_fs(
    funcs: Iterable[Callable[[AsyncFilesystem], Awaitable[R]]],
    exception_group: bool = False,
) -> list[R]:
    """Run funcs concurrently with a shared AsyncFilesystem.

    Each func receives an AsyncFilesystem as its sole argument. A single
    shared filesystem is created and used across all concurrent tasks.

    Args:
        funcs: Async callables that accept an AsyncFilesystem.
        exception_group: ``True`` to raise an ExceptionGroup,
            ``False`` (default) to raise only the first exception.

    Returns:
        List of results in the same order as input funcs.
    """
    async with AsyncFilesystem() as fs:
        return await tg_collect(
            [partial(fn, fs) for fn in funcs],
            exception_group=exception_group,
        )


def run_tg_collect_with_fs(
    funcs: Iterable[Callable[[AsyncFilesystem], Awaitable[R]]],
    exception_group: bool = False,
) -> list[R]:
    """Sync wrapper for :func:`tg_collect_with_fs`.

    Creates a shared AsyncFilesystem, runs all funcs concurrently,
    and returns results via ``run_coroutine``.
    """
    return run_coroutine(tg_collect_with_fs(funcs, exception_group))
