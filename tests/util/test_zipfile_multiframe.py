"""Tests for multi-frame zstd compression of ZIP entries.

Producer-side fix: every ZIP_ZSTANDARD entry should be a multi-frame zstd
stream, capped at 200 MiB of input per frame, so JS decoders with per-frame
size limits (fzstd @ 256 MiB) can decode large inspect_ai .eval files.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest
import zstandard
from test_helpers.zstd import (
    ZSTD_MAGIC,
    moderately_compressible_payload,
    read_raw_compressed_entry,
)

# Importing this module installs the zstd compression patches (both the
# zipfile_zstd delegation on Python < 3.14 and our multi-frame wrapper).
import inspect_ai._util.zipfile
from inspect_ai._util.zipfile import _MultiFrameZstdDecompressObj

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


# ---------------------------------------------------------------------------
# Consumer-side contract: CPython gh-156002 made zipfile._read1 call
# ``decompress(data, max_length)`` on non-deflate decompressors and consult
# ``needs_input`` before reading more compressed bytes. Our multi-frame wrapper
# sits behind ``zipfile._get_decompressor`` on every Python version, so it must
# honour that contract or every .eval read fails with AttributeError.
# ---------------------------------------------------------------------------


def _two_frame_stream(payload: bytes, split: int) -> bytes:
    cctx = zstandard.ZstdCompressor(level=3)
    return cctx.compress(payload[:split]) + cctx.compress(payload[split:])


def _decompressor_for_zstd() -> _MultiFrameZstdDecompressObj:
    # zipfile._get_decompressor is private and absent from the typeshed stubs.
    get_decompressor = getattr(zipfile, "_get_decompressor", None)
    assert get_decompressor is not None
    decomp = get_decompressor(ZIP_ZSTANDARD)
    assert isinstance(decomp, _MultiFrameZstdDecompressObj)
    return decomp


def test_registered_zstd_decompressor_exposes_needs_input() -> None:
    """The stdlib's ``_decompressor_needs_input`` probes ``needs_input`` first."""
    decomp = _decompressor_for_zstd()
    assert decomp.needs_input is True


def test_unbounded_decompress_returns_everything() -> None:
    """The pre-gh-156002 call shape ``decompress(data)`` is unchanged."""
    payload = moderately_compressible_payload(64 * 1024)
    decomp = _decompressor_for_zstd()
    out = decomp.decompress(_two_frame_stream(payload, 20_000))
    assert out == payload
    assert decomp.needs_input is True
    assert decomp.eof is False


MIN_READ_SIZE = 4096  # zipfile.ZipExtFile.MIN_READ_SIZE


def _read_like_post_gh156002(decomp: Any, compressed: bytes, n: int) -> bytes:
    """Mirror ``ZipExtFile._read1``'s non-deflate branch after CPython gh-156002.

    Probe ``needs_input`` (falling back to ``_needs_input`` like the stdlib),
    read more compressed bytes only while it is True, call
    ``decompress(data, max_length)``, and stop on
    ``eof or (no compressed bytes left and needs_input)``.  This exercises the
    new call shape on interpreters whose ``zipfile`` predates the change.
    """

    def needs_input(d: Any) -> bool:
        probe = getattr(d, "needs_input", None)
        return d._needs_input if probe is None else probe

    out, pos, eof, calls = bytearray(), 0, False, 0
    while not eof:
        calls += 1
        assert calls <= len(compressed) // MIN_READ_SIZE + 4, (
            "drain loop never terminates"
        )
        if needs_input(decomp):
            chunk = compressed[pos : pos + max(n, MIN_READ_SIZE)]
            pos += len(chunk)
        else:
            chunk = b""
        out += decomp.decompress(chunk, max(n, MIN_READ_SIZE))
        eof = decomp.eof or (pos >= len(compressed) and needs_input(decomp))
    return bytes(out)


@pytest.mark.parametrize("n", [1, 4096, 65_536])
def test_post_gh156002_read1_loop_reassembles_multi_frame_entry(n: int) -> None:
    payload = moderately_compressible_payload(50_000)
    stream = _two_frame_stream(payload, 17_000)
    assert _read_like_post_gh156002(_decompressor_for_zstd(), stream, n) == payload


def test_partial_input_across_a_frame_boundary() -> None:
    """Input arriving in arbitrary slices is reassembled across frames."""
    payload = moderately_compressible_payload(30_000)
    stream = _two_frame_stream(payload, 15_000)
    decomp = _decompressor_for_zstd()

    out = b""
    for i in range(0, len(stream), 100):
        out += decomp.decompress(stream[i : i + 100], 4096)
        assert decomp.needs_input is True
    assert out == payload


def test_zip_member_read_paths_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``read``, ``read1`` and ``readline`` all reassemble a multi-frame entry.

    Exercises whatever ``zipfile._read1`` the running interpreter ships.
    """
    # Shrink the frame cap so a 3 MiB payload becomes a 3-frame entry.
    monkeypatch.setattr(inspect_ai._util.zipfile, "_MAX_INPUT_PER_FRAME", 1024 * 1024)
    payload = moderately_compressible_payload(3 * 1024 * 1024)
    zip_path = tmp_path / "paths.zip"
    with zipfile.ZipFile(zip_path, "w", compression=ZIP_ZSTANDARD) as zf:
        zf.writestr("entry.json", payload)
    assert read_raw_compressed_entry(zip_path, "entry.json").count(ZSTD_MAGIC) == 3

    with zipfile.ZipFile(zip_path) as zf:
        assert zf.read("entry.json") == payload

        with zf.open("entry.json") as fp:
            assert isinstance(fp, zipfile.ZipExtFile)
            got = bytearray()
            while chunk := fp.read1(7_000):
                got += chunk
            assert bytes(got) == payload

        with zf.open("entry.json") as fp:
            assert b"".join(iter(fp.readline, b"")) == payload
