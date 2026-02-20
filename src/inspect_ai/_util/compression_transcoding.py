from collections.abc import AsyncIterable, AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Literal

import zstandard
from anyio.abc import ByteReceiveStream

from .compression import DeflateCompressor, DeflateDecompressor, ZstdDecompressor
from .zip_common import ZipCompressionMethod


class CompressedToUncompressedStream(AsyncIterator[bytes]):
    """AsyncIterator that decompresses ZIP member data streams.

    Supports DEFLATE (mode 8) and zstd (mode 93) compression methods.
    For uncompressed data (COMPRESSION_STORED), use the source stream directly.

    This class provides explicit control over resource cleanup via the aclose()
    method, fixing Python 3.12 issues where async generator cleanup could fail
    with "generator already running" errors during event loop shutdown.
    """

    def __init__(
        self,
        compressed_stream: ByteReceiveStream,
        compression_method: Literal[
            ZipCompressionMethod.DEFLATE, ZipCompressionMethod.ZSTD
        ],
    ):
        """Initialize the decompression stream.

        Args:
            compressed_stream: The compressed input byte stream
            compression_method: Compression format of input (8=DEFLATE, 93=zstd).
        """
        self._compressed_stream = compressed_stream
        self._decompressor = (
            DeflateDecompressor()
            if compression_method == ZipCompressionMethod.DEFLATE
            else ZstdDecompressor()
        )
        self._stream_iterator: AsyncIterator[bytes] | None = None
        self._closed = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        """Return self as the async iterator."""
        return self

    async def __anext__(self) -> bytes:
        if self._closed or self._decompressor.exhausted:
            raise StopAsyncIteration

        # Initialize stream iterator on first call
        if self._stream_iterator is None:
            self._stream_iterator = self._compressed_stream.__aiter__()

        return await self._decompressor.decompress_next(self._stream_iterator)

    async def aclose(self) -> None:
        """Explicitly close the stream and underlying resources.

        This method ensures the ByteReceiveStream is properly closed even
        when the iterator is not fully consumed.
        """
        if self._closed:
            return

        self._closed = True

        # Close the underlying stream
        await self._compressed_stream.aclose()


class CompressedToDeflateStream:
    """Async context manager that transcodes a potentially compressed stream to deflate.

    Decompresses the source stream (if compressed) and re-compresses to deflate
    for HTTP streaming (browsers support Content-Encoding: deflate but not zstd).

    Example:
        async with DeflateTranscodingStream(zstd_cm, COMPRESSION_ZSTD) as stream:
            async for chunk in stream:
                yield chunk
    """

    def __init__(
        self,
        source_cm: AbstractAsyncContextManager[AsyncIterable[bytes]],
        source_compression: ZipCompressionMethod = ZipCompressionMethod.STORED,
    ) -> None:
        """Initialize the transcoding stream.

        Args:
            source_cm: Async context manager that yields compressed bytes
            source_compression: Compression method of source (0=stored, 93=zstd)
        """
        self._source_cm = source_cm
        self._source_compression = source_compression
        self._deflate_stream: _DeflateCompressStream | None = None
        self._closed = False

    async def __aenter__(self) -> AsyncIterator[bytes]:
        source_iter = await self._source_cm.__aenter__()
        try:
            # Decompress source if needed, then deflate-compress
            if self._source_compression == ZipCompressionMethod.DEFLATE:
                # Already deflate-compressed, pass through unchanged
                return source_iter.__aiter__()
            elif self._source_compression == ZipCompressionMethod.ZSTD:
                decompressed_iter = _ZstdDecompressIterator(source_iter.__aiter__())
                self._deflate_stream = _DeflateCompressStream(decompressed_iter)
            else:
                # Source is uncompressed (COMPRESSION_STORED), just deflate-compress
                self._deflate_stream = _DeflateCompressStream(source_iter.__aiter__())
            return self._deflate_stream
        except Exception:
            # Clean up source if stream creation fails
            await self._source_cm.__aexit__(None, None, None)
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._closed:
            return
        self._closed = True
        if self._deflate_stream:
            await self._deflate_stream.aclose()
        await self._source_cm.__aexit__(exc_type, exc_val, exc_tb)

    async def aclose(self) -> None:
        """Explicitly close resources without entering the context manager.

        Safe to call multiple times or after __aexit__.
        """
        if self._closed:
            return
        self._closed = True
        # source_cm was never entered, nothing to close


class _DeflateCompressStream(AsyncIterator[bytes]):
    """AsyncIterator wrapper for deflate-compressing an async byte stream.

    Used to transcode zstd-compressed data to deflate for HTTP streaming,
    since browsers support Content-Encoding: deflate but not zstd.
    """

    def __init__(self, source_stream: AsyncIterator[bytes]):
        """Initialize the deflate compression stream.

        Args:
            source_stream: The input byte stream to compress
        """
        self._source_stream = source_stream
        self._compressor = DeflateCompressor()
        self._closed = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        """Return self as the async iterator."""
        return self

    async def __anext__(self) -> bytes:
        """Get the next chunk of deflate-compressed data.

        Returns:
            Next chunk of compressed bytes

        Raises:
            StopAsyncIteration: When stream is exhausted
        """
        if self._closed or self._compressor.exhausted:
            raise StopAsyncIteration

        return await self._compressor.compress_next(self._source_stream)

    async def aclose(self) -> None:
        """Explicitly close the stream.

        Safe to call multiple times.
        """
        if self._closed:
            return

        self._closed = True


class _ZstdDecompressIterator(AsyncIterator[bytes]):
    """AsyncIterator that decompresses zstd data from a source iterator."""

    def __init__(self, source: AsyncIterator[bytes]):
        self._source = source
        dctx = zstandard.ZstdDecompressor()
        self._decompressor: zstandard.ZstdDecompressionObj | None = dctx.decompressobj()
        self._exhausted = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> bytes:
        if self._exhausted or self._decompressor is None:
            raise StopAsyncIteration

        while True:
            try:
                chunk = await self._source.__anext__()
                decompressed = self._decompressor.decompress(chunk)
                if decompressed:
                    return decompressed
            except StopAsyncIteration:
                # Flush any remaining data
                if self._decompressor:
                    try:
                        final = self._decompressor.decompress(b"")
                    except zstandard.ZstdError:
                        final = b""
                    self._decompressor = None
                    self._exhausted = True
                    if final:
                        return final
                raise
