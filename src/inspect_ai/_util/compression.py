import zlib
from collections.abc import AsyncIterator
from typing import Protocol

import zstandard


class Decompressor(Protocol):
    """Protocol for async decompressors that read from a stream iterator."""

    @property
    def exhausted(self) -> bool:
        """Whether the decompressor has finished processing all input."""
        ...

    async def decompress_next(self, stream_iterator: AsyncIterator[bytes]) -> bytes:
        """Read compressed chunks until decompressed output is available.

        The decompressor may buffer multiple input chunks before producing output,
        as it needs to accumulate enough compressed data to decode a full block.
        This method keeps reading from the source stream until decompression
        yields non-empty output.

        Raises:
            StopAsyncIteration: When the stream is exhausted.
        """
        ...


class ZstdDecompressor(Decompressor):
    """Decompressor for zstd compressed data."""

    def __init__(self) -> None:
        self._decompressor: zstandard.ZstdDecompressionObj | None = None
        self._exhausted = False

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    async def decompress_next(self, stream_iterator: AsyncIterator[bytes]) -> bytes:
        """Read compressed chunks until decompressed output is available."""
        if self._decompressor is None:
            self._decompressor = zstandard.ZstdDecompressor().decompressobj()
        while True:
            try:
                chunk = await stream_iterator.__anext__()
                decompressed = self._decompressor.decompress(chunk)
                if decompressed:
                    return decompressed
            except StopAsyncIteration:
                # Note: Unlike zlib, zstandard's decompressobj doesn't have
                # a flush() method. Passing empty bytes can trigger output
                # of any remaining buffered data in some edge cases.
                try:
                    final = self._decompressor.decompress(b"")
                except zstandard.ZstdError:
                    final = b""
                self._decompressor = None
                self._exhausted = True
                if final:
                    return final
                raise


class DeflateDecompressor(Decompressor):
    """Decompressor for DEFLATE (raw) compressed data."""

    def __init__(self) -> None:
        self._decompressor: zlib._Decompress | None = None
        self._exhausted = False

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    async def decompress_next(self, stream_iterator: AsyncIterator[bytes]) -> bytes:
        """Read compressed chunks until decompressed output is available."""
        if self._decompressor is None:
            self._decompressor = zlib.decompressobj(-15)  # Raw DEFLATE
        while True:
            try:
                chunk = await stream_iterator.__anext__()
                decompressed = self._decompressor.decompress(chunk)
                if decompressed:
                    return decompressed
            except StopAsyncIteration:
                final = self._decompressor.flush()
                self._decompressor = None
                self._exhausted = True
                if final:
                    return final
                raise


class Compressor(Protocol):
    """Protocol for async compressors that read from a stream iterator."""

    @property
    def exhausted(self) -> bool:
        """Whether the compressor has finished processing all input."""
        ...

    async def compress_next(self, stream_iterator: AsyncIterator[bytes]) -> bytes:
        """Read uncompressed chunks until compressed output is available.

        The compressor may buffer multiple input chunks before producing output,
        as it needs to accumulate enough data to form a compressed block.
        This method keeps reading from the source stream until compression
        yields non-empty output.

        Raises:
            StopAsyncIteration: When the stream is exhausted.
        """
        ...


class DeflateCompressor(Compressor):
    """Compressor for DEFLATE (raw) compressed data."""

    def __init__(self) -> None:
        # wbits=-15 produces raw DEFLATE (no zlib/gzip wrapper)
        self._compressor: zlib._Compress | None = zlib.compressobj(
            level=6,
            wbits=-15,
        )
        self._exhausted = False

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    async def compress_next(self, stream_iterator: AsyncIterator[bytes]) -> bytes:
        """Read uncompressed chunks until compressed output is available."""
        while True:
            try:
                chunk = await stream_iterator.__anext__()
                if self._compressor is None:
                    raise StopAsyncIteration
                compressed = self._compressor.compress(chunk)
                if compressed:
                    return compressed
                # If no compressed data yet (buffered), continue reading
            except StopAsyncIteration:
                # Input stream exhausted, flush any remaining data
                if self._compressor:
                    final = self._compressor.flush()
                    self._compressor = None
                    self._exhausted = True
                    if final:
                        return final
                raise
