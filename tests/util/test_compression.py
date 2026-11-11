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
    assert b"".join(pieces) == data
    assert max(len(piece) for piece in pieces) <= 64 * 1024


@pytest.mark.timeout(10)
def test_piece_decompressor_ignores_data_after_a_deflate_stream() -> None:
    # output spanning several pieces, then bytes past the end of the stream
    data = os.urandom(200 * 1024)
    compressed = _compress(data, ZipCompressionMethod.DEFLATE) + b"TAIL"
    pieces: list[bytes] = []
    decompressor = PieceDecompressor(
        ZipCompressionMethod.DEFLATE, pieces.append, piece_size=64 * 1024
    )
    decompressor.write(compressed)
    decompressor.write(b"more")
    decompressor.finish()
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
