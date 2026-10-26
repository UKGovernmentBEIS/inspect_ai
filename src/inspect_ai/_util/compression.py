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


class _ZstdFrames:
    """Decompresses a sequence of zstd frames fed in pieces."""

    def __init__(self) -> None:
        self._dctx = zstandard.ZstdDecompressor()
        self._obj = self._dctx.decompressobj()
        self._in_frame = False
        self.unused_data = b""
        """Input past the end of the frame the last call completed."""

    def decompress(self, data: bytes) -> bytes:
        """Decompress ``data`` up to the end of the current frame.

        Stops at a frame boundary, leaving the rest of ``data`` in
        ``unused_data``, so one call never inflates more than one frame.
        """
        out = self._obj.decompress(data)
        if self._obj.eof:
            self.unused_data = self._obj.unused_data
            self._obj = self._dctx.decompressobj()
            self._in_frame = False
        else:
            self.unused_data = b""
            self._in_frame = self._in_frame or bool(data)
        return out

    def finish(self) -> None:
        """Raise ``ValueError`` if the input ended inside a frame."""
        if self._in_frame:
            raise ValueError("Truncated zstd stream")


class ZstdDecompressor(Decompressor):
    """Decompressor for zstd compressed data, supporting multi-frame streams."""

    def __init__(self) -> None:
        self._frames: _ZstdFrames | None = None
        self._exhausted = False

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    async def decompress_next(self, stream_iterator: AsyncIterator[bytes]) -> bytes:
        """Read compressed chunks until decompressed output is available.

        Raises:
            ValueError: The stream ends inside a frame.
        """
        if self._exhausted:
            raise StopAsyncIteration
        if self._frames is None:
            self._frames = _ZstdFrames()
        while True:
            data = self._frames.unused_data
            if not data:
                try:
                    data = await stream_iterator.__anext__()
                except StopAsyncIteration:
                    self._exhausted = True
                    self._frames.finish()
                    raise
            decompressed = self._frames.decompress(data)
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
        """Read compressed chunks until decompressed output is available.

        Raises:
            ValueError: The stream ends before the end of the DEFLATE data.
        """
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
                eof = self._decompressor.eof
                self._decompressor = None
                self._exhausted = True
                if not eof:
                    raise ValueError("Truncated DEFLATE stream") from None
                if final:
                    return final
                raise


def decompress_bytes(data: bytes, method: ZipCompressionMethod) -> bytes:
    """Decompress a complete buffer using the given ZIP compression method.

    Raises:
        ValueError: The buffer ends before the end of the compressed data.
        NotImplementedError: The compression method is not supported.
    """
    if method == ZipCompressionMethod.STORED:
        return data
    elif method == ZipCompressionMethod.DEFLATE:
        deflate = zlib.decompressobj(-15)
        decompressed = deflate.decompress(data) + deflate.flush()
        if not deflate.eof:
            raise ValueError("Truncated DEFLATE stream")
        return decompressed
    elif method == ZipCompressionMethod.ZSTD:
        frames = _ZstdFrames()
        out = [frames.decompress(data)]
        while frames.unused_data:
            out.append(frames.decompress(frames.unused_data))
        frames.finish()
        return b"".join(out)
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
