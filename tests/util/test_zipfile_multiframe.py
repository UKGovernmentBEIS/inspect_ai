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

# Importing this module installs the zstd compression patches (both the
# zipfile_zstd delegation on Python < 3.14 and our multi-frame wrapper).
import inspect_ai._util.zipfile  # noqa: F401

MAX_INPUT_PER_FRAME = 200 * 1024 * 1024  # must match the value in _util/zipfile.py
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _moderately_compressible_payload(total_bytes: int) -> bytes:
    """Build a deterministic payload that compresses at a realistic ratio.

    Pure random data bypasses zstd's match-finder (compressor emits raw
    blocks); pure-constant data collapses to tiny output. We want something
    in between so the compressed output is a non-trivial fraction of input —
    close to the JSON-like eval workload we care about.
    """
    fragments = [
        b'{"role": "assistant", "content": "The quick brown fox jumps over the lazy dog."}\n',
        b'{"role": "user", "content": "What is the capital of France? Please answer in one sentence."}\n',
        b'{"tool_calls": [{"name": "search", "arguments": {"query": "weather in paris"}}]}\n',
        b'{"metadata": {"timestamp": "2026-04-23T10:00:00Z", "model": "claude-opus-4-7"}}\n',
    ]
    chunk = b"".join(fragments)
    n = (total_bytes // len(chunk)) + 1
    return (chunk * n)[:total_bytes]


@pytest.fixture(scope="module")
def large_payload() -> bytes:
    """~450 MiB of moderately compressible JSON-like bytes."""
    return _moderately_compressible_payload(450 * 1024 * 1024)


def _read_raw_compressed_entry(zip_path: Path, entry_name: str) -> bytes:
    """Return the raw compressed bytes stored for a zip entry (no decompression)."""
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo(entry_name)
        with open(zip_path, "rb") as f:
            f.seek(info.header_offset)
            # Skip local file header to reach the data. Using ZipFile's private
            # helper is fragile; instead, decode the local header manually.
            import struct

            sig_version_etc = f.read(30)
            assert sig_version_etc[:4] == b"PK\x03\x04", "not a local file header"
            name_len = struct.unpack("<H", sig_version_etc[26:28])[0]
            extra_len = struct.unpack("<H", sig_version_etc[28:30])[0]
            f.read(name_len + extra_len)
            return f.read(info.compress_size)


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
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_ZSTANDARD) as zf:
        zf.writestr("big.json", large_payload)

    raw = _read_raw_compressed_entry(zip_path, "big.json")

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
    payload = _moderately_compressible_payload(1 * 1024 * 1024)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_ZSTANDARD) as zf:
        zf.writestr("small.json", payload)

    raw = _read_raw_compressed_entry(zip_path, "small.json")
    assert raw.count(ZSTD_MAGIC) == 1, (
        f"expected exactly 1 frame for small entry, got {raw.count(ZSTD_MAGIC)}"
    )
