import zlib
from collections.abc import AsyncIterator
from typing import Protocol

import zstandard

from .zip_common import ZipCompressionMethod


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
    """Decompressor for zstd compressed data, supporting multi-frame streams.

    A single ``zstandard`` decompressobj only spans one frame; on eof it
    rejects further input. This class chains fresh inner decompressobj
    instances across frame boundaries, carrying the previous frame's
    ``unused_data`` into the next frame.
    """

    def __init__(self) -> None:
        self._dctx: zstandard.ZstdDecompressor | None = None
        self._obj: zstandard.ZstdDecompressionObj | None = None
        self._pending: bytes = b""
        self._exhausted = False

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    async def decompress_next(self, stream_iterator: AsyncIterator[bytes]) -> bytes:
        """Read compressed chunks until decompressed output is available."""
        if self._exhausted:
            raise StopAsyncIteration
        if self._dctx is None:
            self._dctx = zstandard.ZstdDecompressor()
            self._obj = self._dctx.decompressobj()
        assert self._obj is not None and self._dctx is not None
        while True:
            if self._pending:
                data, self._pending = self._pending, b""
            else:
                try:
                    data = await stream_iterator.__anext__()
                except StopAsyncIteration:
                    # Note: Unlike zlib, zstandard's decompressobj doesn't
                    # have a flush() method. Passing empty bytes can trigger
                    # output of any remaining buffered data in some edge
                    # cases; if the inner is already eof'd, swallow the
                    # error.
                    try:
                        final = self._obj.decompress(b"")
                    except zstandard.ZstdError:
                        final = b""
                    self._obj = None
                    self._dctx = None
                    self._exhausted = True
                    if final:
                        return final
                    raise
            decompressed = self._obj.decompress(data)
            if self._obj.eof:
                # Inner frame complete; carry leftover bytes (the start of
                # the next frame) into a fresh inner decompressobj.
                self._pending = self._obj.unused_data
                self._obj = self._dctx.decompressobj()
            if decompressed:
                return decompressed


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


def decompress_bytes(data: bytes, method: ZipCompressionMethod) -> bytes:
    """Decompress a complete buffer using the given ZIP compression method."""
    if method == ZipCompressionMethod.STORED:
        return data
    elif method == ZipCompressionMethod.DEFLATE:
        return zlib.decompress(data, -15)
    elif method == ZipCompressionMethod.ZSTD:
        return zstandard.ZstdDecompressor().stream_reader(data).read()
    else:
        raise NotImplementedError(f"Unsupported compression method: {method}")


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
