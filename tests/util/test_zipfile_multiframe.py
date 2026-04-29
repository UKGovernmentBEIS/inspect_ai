"""Tests for multi-frame zstd compression of ZIP entries.

Producer-side fix: every ZIP_ZSTANDARD entry should be a multi-frame zstd
stream, capped at 200 MiB of input per frame, so JS decoders with per-frame
size limits (fzstd @ 256 MiB) can decode large inspect_ai .eval files.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import zstandard
from test_helpers.zstd import (
    ZSTD_MAGIC,
    moderately_compressible_payload,
    read_raw_compressed_entry,
)

# Importing this module installs the zstd compression patches (both the
# zipfile_zstd delegation on Python < 3.14 and our multi-frame wrapper).
import inspect_ai._util.zipfile  # noqa: F401

MAX_INPUT_PER_FRAME = 200 * 1024 * 1024  # must match the value in _util/zipfile.py

# zipfile_zstd adds ZIP_ZSTANDARD (93) to zipfile at import time; use getattr
# so type checkers on Python < 3.14 (where stdlib zipfile doesn't declare it)
# stay happy.
ZIP_ZSTANDARD: int = getattr(zipfile, "ZIP_ZSTANDARD", 93)


@pytest.fixture(scope="module")
def large_payload() -> bytes:
    """~450 MiB of moderately compressible JSON-like bytes."""
    return moderately_compressible_payload(450 * 1024 * 1024)


def _iter_frames(compressed: bytes):
    """Yield (frame_index, decompressed_bytes) for each frame in a zstd stream."""
    dctx = zstandard.ZstdDecompressor()
    idx = 0
    remaining = compressed
    while remaining:
        obj = dctx.decompressobj()
        out = obj.decompress(remaining)
        # decompressobj consumes one frame; remaining bytes are in unused_data
        yield idx, out
        idx += 1
        remaining = obj.unused_data


def test_large_entry_emits_multiple_capped_frames(
    tmp_path: Path, large_payload: bytes
) -> None:
    """A ~450 MiB payload should produce ≥3 zstd frames, each ≤ 200 MiB uncompressed."""
    zip_path = tmp_path / "large.zip"
    with zipfile.ZipFile(zip_path, "w", compression=ZIP_ZSTANDARD) as zf:
        zf.writestr("big.json", large_payload)

    raw = read_raw_compressed_entry(zip_path, "big.json")

    magic_count = raw.count(ZSTD_MAGIC)
    assert magic_count >= 3, (
        f"expected ≥3 zstd frames in a 450 MiB entry, found {magic_count}"
    )

    frame_sizes = [len(out) for _, out in _iter_frames(raw)]
    assert len(frame_sizes) == magic_count, (
        f"magic count {magic_count} != frames walked {len(frame_sizes)}"
    )
    for i, size in enumerate(frame_sizes):
        assert size <= MAX_INPUT_PER_FRAME, (
            f"frame {i} decompressed to {size} bytes, exceeds cap {MAX_INPUT_PER_FRAME}"
        )


def test_small_entry_emits_single_frame(tmp_path: Path) -> None:
    """A 1 MiB entry should still be exactly one zstd frame."""
    zip_path = tmp_path / "small.zip"
    payload = moderately_compressible_payload(1 * 1024 * 1024)
    with zipfile.ZipFile(zip_path, "w", compression=ZIP_ZSTANDARD) as zf:
        zf.writestr("small.json", payload)

    raw = read_raw_compressed_entry(zip_path, "small.json")
    assert raw.count(ZSTD_MAGIC) == 1, (
        f"expected exactly 1 frame for small entry, got {raw.count(ZSTD_MAGIC)}"
    )


def test_large_entry_round_trip(tmp_path: Path, large_payload: bytes) -> None:
    """Writing and reading back a multi-frame entry must preserve bytes exactly."""
    zip_path = tmp_path / "rt.zip"
    with zipfile.ZipFile(zip_path, "w", compression=ZIP_ZSTANDARD) as zf:
        zf.writestr("big.json", large_payload)

    with zipfile.ZipFile(zip_path) as zf:
        got = zf.read("big.json")

    assert got == large_payload, (
        f"round-trip mismatch: input {len(large_payload)} bytes, got {len(got)} bytes"
    )
