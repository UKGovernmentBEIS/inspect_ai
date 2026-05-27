from collections.abc import AsyncIterable, AsyncIterator
from typing import IO, Protocol, TypeGuard, cast

import anyio
from typing_extensions import Self


class AsyncBytesReader(Protocol):
    """Protocol defining the minimal async file-like interface for ijson.

    ijson.parse_async() requires an async file-like object with a read() method that:
    - Can be awaited (is an async method)
    - Returns bytes (binary mode)
    - Accepts a size parameter for the number of bytes to read

    This protocol captures that minimal requirement without requiring the full BinaryIO
    interface that includes methods like seek(), tell(), close(), etc.

    Also supports async context manager protocol for usage ensuring proper resource
    cleanup.
    """

    async def read(self, size: int) -> bytes: ...
    async def aclose(self) -> None: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *args: object) -> None: ...


def _is_async_iterable(
    io_or_iter: IO[bytes] | AsyncIterable[bytes],
) -> TypeGuard[AsyncIterable[bytes]]:
    return hasattr(io_or_iter, "__aiter__")


def adapt_to_reader(io_or_iter: IO[bytes] | AsyncIterable[bytes]) -> AsyncBytesReader:
    """Adapt a byte source to an async file-like interface (e.g. for ijson).

    Use as async context manager to ensure cleanup of underlying async iterators.
    """
    return (
        _BytesIterableReader(io_or_iter)
        if _is_async_iterable(io_or_iter)
        else _BytesIOReader(cast(IO[bytes], io_or_iter))
    )


class _BytesIOReader(AsyncBytesReader):
    """Wrapper to make synchronous I/O operations async-compatible.

    This class is needed because zipfile.ZipFile and other standard library I/O
    operations are strictly synchronous. To achieve concurrency and avoid blocking
    the main thread, this wrapper uses anyio.to_thread to run blocking I/O operations
    in a thread pool while maintaining async/await compatibility.

    The internal lock ensures thread-safe access to the underlying synchronous I/O object.
    """

    def __init__(self, sync_io: IO[bytes]):
        self._sync_io = sync_io
        self._lock = anyio.Lock()

    async def read(self, size: int) -> bytes:
        async with self._lock:
            return await anyio.to_thread.run_sync(self._sync_io.read, size)

    async def aclose(self) -> None:
        pass  # caller owns the IO[bytes]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


class _BytesIterableReader(AsyncBytesReader):
    """AsyncBytesReader implementation that reads from an AsyncIterable[bytes]."""

    def __init__(self, async_iterable: AsyncIterable[bytes]):
        self._async_iter: AsyncIterator[bytes] = aiter(async_iterable)
        self._current_chunk: bytes = b""
        self._offset = 0

    async def read(self, size: int) -> bytes:
        if size < 0:
            raise ValueError("size must be non-negative")
        if size == 0:
            return b""

        chunks_to_return: list[bytes] = []
        total = 0

        while total < size:
            # Get more data from current chunk if available
            available = len(self._current_chunk) - self._offset
            if available > 0:
                bytes_to_take = min(size - total, available)
                chunks_to_return.append(
                    self._current_chunk[self._offset : self._offset + bytes_to_take]
                )
                self._offset += bytes_to_take
                total += bytes_to_take
            else:
                # Current chunk exhausted, fetch next
                try:
                    self._current_chunk = await anext(self._async_iter)
                    self._offset = 0
                except StopAsyncIteration:
                    break  # No more data

        return b"".join(chunks_to_return)

    async def aclose(self) -> None:
        if hasattr(self._async_iter, "aclose"):
            await self._async_iter.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
