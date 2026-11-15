import os
import zlib

import pytest
import zstandard

from inspect_ai._util.compression import PieceDecompressor
from inspect_ai._util.zip_common import ZipCompressionMethod


def _compress(data: bytes, method: ZipCompressionMethod) -> bytes:
    if method == ZipCompressionMethod.DEFLATE:
        compressor = zlib.compressobj(wbits=-15)
        return compressor.compress(data) + compressor.flush()
    if method == ZipCompressionMethod.ZSTD:
        # two frames, as the zip writer splits large members
        half = len(data) // 2
        zstd = zstandard.ZstdCompressor()
        return zstd.compress(data[:half]) + zstd.compress(data[half:])
    return data


@pytest.mark.parametrize(
    "method",
    [
        ZipCompressionMethod.STORED,
        ZipCompressionMethod.DEFLATE,
        ZipCompressionMethod.ZSTD,
    ],
)
def test_piece_decompressor_bounds_each_piece(method: ZipCompressionMethod) -> None:
    # compressible data expands far beyond each compressed chunk
    data = (os.urandom(1024).hex() * 2048).encode()
    compressed = _compress(data, method)
    pieces: list[bytes] = []
    decompressor = PieceDecompressor(method, pieces.append, piece_size=64 * 1024)
    for start in range(0, len(compressed), 1024 * 1024):
        decompressor.write(compressed[start : start + 1024 * 1024])
    decompressor.finish()
    assert b"".join(pieces) == data
    assert max(len(piece) for piece in pieces) <= 64 * 1024


@pytest.mark.timeout(10)
def test_piece_decompressor_refuses_data_after_a_deflate_stream() -> None:
    # output spanning several pieces, then bytes past the end of the stream
    data = os.urandom(200 * 1024)
    compressed = _compress(data, ZipCompressionMethod.DEFLATE)
    pieces: list[bytes] = []
    decompressor = PieceDecompressor(
        ZipCompressionMethod.DEFLATE, pieces.append, piece_size=64 * 1024
    )
    with pytest.raises(zlib.error, match="bytes after the end of a deflate stream"):
        decompressor.write(compressed + b"TAIL")
    assert b"".join(pieces) == data

    pieces.clear()
    decompressor = PieceDecompressor(
        ZipCompressionMethod.DEFLATE, pieces.append, piece_size=64 * 1024
    )
    decompressor.write(compressed)
    with pytest.raises(zlib.error, match="bytes after the end of a deflate stream"):
        decompressor.write(b"more")
    assert b"".join(pieces) == data


def test_piece_decompressor_refuses_a_deflate_stream_without_its_final_block() -> None:
    data = b"abc" * 4096
    compressed = bytearray(_compress(data, ZipCompressionMethod.DEFLATE))
    # clear the final-block bit: the output is complete, the stream is not
    compressed[0] &= 0xFE
    pieces: list[bytes] = []
    decompressor = PieceDecompressor(ZipCompressionMethod.DEFLATE, pieces.append)
    decompressor.write(bytes(compressed))
    assert b"".join(pieces) == data
    with pytest.raises(zlib.error, match="incomplete or truncated stream"):
        decompressor.finish()


def _zstd_frame_of_raw_blocks(data: bytes, last_block: bool) -> bytes:
    """A zstd frame holding `data` in raw blocks, the last one flagged if asked."""
    # descriptor: no checksum or content size; window descriptor: 128 KiB
    frame = bytearray(b"\x28\xb5\x2f\xfd\x00\x38")
    block_size = 64 * 1024
    for start in range(0, len(data), block_size):
        block = data[start : start + block_size]
        last = last_block and start + block_size >= len(data)
        frame += ((len(block) << 3) | last).to_bytes(3, "little") + block
    return bytes(frame)


@pytest.mark.parametrize(
    "frame,complete",
    [
        ("raw blocks", True),
        ("raw blocks without the last-block flag", False),
        ("compressed with a checksum", True),
        ("compressed without its checksum", False),
        ("two frames, the second truncated", False),
    ],
)
def test_piece_decompressor_refuses_an_incomplete_zstd_frame(
    frame: str, complete: bool
) -> None:
    data = os.urandom(100 * 1024).hex().encode()
    zstd = zstandard.ZstdCompressor(write_checksum=True)
    compressed = {
        "raw blocks": _zstd_frame_of_raw_blocks(data, last_block=True),
        "raw blocks without the last-block flag": _zstd_frame_of_raw_blocks(
            data, last_block=False
        ),
        "compressed with a checksum": zstd.compress(data),
        "compressed without its checksum": zstd.compress(data)[:-4],
        "two frames, the second truncated": zstd.compress(data[:1000])
        + zstd.compress(data[1000:])[:-100],
    }[frame]
    pieces: list[bytes] = []
    decompressor = PieceDecompressor(ZipCompressionMethod.ZSTD, pieces.append)
    # fed in pieces that split every field of the frame
    for start in range(0, len(compressed), 7):
        decompressor.write(compressed[start : start + 7])
    if complete:
        decompressor.finish()
        assert b"".join(pieces) == data
    else:
        with pytest.raises(zstandard.ZstdError, match="incomplete or truncated"):
            decompressor.finish()
