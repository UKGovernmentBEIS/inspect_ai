"""Shared test helpers for zstd zip-entry construction and inspection.

Used by:
- tests/util/test_zipfile_multiframe.py (existing sync multi-frame tests)
- tests/util/test_async_zip.py (new async multi-frame integration test)
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def moderately_compressible_payload(total_bytes: int) -> bytes:
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


def read_raw_compressed_entry(zip_path: Path, entry_name: str) -> bytes:
    """Return the raw compressed bytes stored for a zip entry (no decompression)."""
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo(entry_name)
        with open(zip_path, "rb") as f:
            f.seek(info.header_offset)
            sig_version_etc = f.read(30)
            assert sig_version_etc[:4] == b"PK\x03\x04", "not a local file header"
            name_len: int = struct.unpack("<H", sig_version_etc[26:28])[0]
            extra_len: int = struct.unpack("<H", sig_version_etc[28:30])[0]
            f.read(name_len + extra_len)
            return f.read(info.compress_size)
