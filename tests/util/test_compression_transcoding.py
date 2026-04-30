"""Tests for compression_transcoding helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator

import zstandard

from inspect_ai._util.compression_transcoding import _ZstdDecompressIterator


async def _aiter_chunks(data: bytes, chunk_size: int) -> AsyncIterator[bytes]:
    """Yield ``data`` as fixed-size async chunks."""
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def _multi_frame_zstd(parts: list[bytes]) -> bytes:
    """Compress each part as its own zstd frame; concatenate the frames."""
    cctx = zstandard.ZstdCompressor()
    return b"".join(cctx.compress(part) for part in parts)


async def test_multi_frame_round_trip() -> None:
    """Decompresses a stream containing two zstd frames concatenated."""
    parts = [b"frame one payload " * 64, b"frame two payload " * 64]
    expected = b"".join(parts)
    compressed = _multi_frame_zstd(parts)

    iterator = _ZstdDecompressIterator(_aiter_chunks(compressed, 7))
    chunks: list[bytes] = []
    async for chunk in iterator:
        chunks.append(chunk)
    assert b"".join(chunks) == expected


async def test_single_frame_still_works() -> None:
    """Single-frame zstd input still decompresses correctly (no regression)."""
    payload = b"hello zstd " * 1024
    compressed = zstandard.ZstdCompressor().compress(payload)

    iterator = _ZstdDecompressIterator(_aiter_chunks(compressed, 16))
    chunks: list[bytes] = []
    async for chunk in iterator:
        chunks.append(chunk)
    assert b"".join(chunks) == payload


async def test_three_frames_round_trip() -> None:
    """Stream of three frames (two boundary transitions) round-trips."""
    parts = [b"alpha " * 100, b"beta " * 100, b"gamma " * 100]
    expected = b"".join(parts)
    compressed = _multi_frame_zstd(parts)

    iterator = _ZstdDecompressIterator(_aiter_chunks(compressed, 13))
    assert b"".join([chunk async for chunk in iterator]) == expected
