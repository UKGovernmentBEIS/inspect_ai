"""Tests for the restic binary resolver.

Three contracts:
1. A pre-existing cache file short-circuits without invoking the network.
2. A cache miss downloads, verifies SHA256, and populates the cache.
3. A SHA256 mismatch raises and leaves the cache untouched.

All tests mock at the urllib layer; no network, no fixtures on disk other
than what the test itself writes.
"""

from __future__ import annotations

import bz2
import hashlib
import io
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from inspect_ai.util._restic._platform import Platform
from inspect_ai.util._restic._resolver import (
    _archive_filename,
    cache_path,
    resolve_restic,
)

PLATFORM: Platform = "linux_amd64"
FAKE_BINARY = b"#!/bin/sh\necho fake-restic\n"
FAKE_BINARY_SHA = hashlib.sha256(bz2.compress(FAKE_BINARY)).hexdigest()


@contextmanager
def _patch_cache_dir(tmp_path: Path) -> Iterator[None]:
    """Redirect inspect_cache_dir(...) to a tmp directory for the test."""

    def fake_cache_dir(subdir: str | None) -> Path:
        d = tmp_path / (subdir or "")
        d.mkdir(parents=True, exist_ok=True)
        return d

    with patch(
        "inspect_ai.util._restic._resolver.inspect_cache_dir",
        side_effect=fake_cache_dir,
    ):
        yield


def _make_urlopen(sums_text: str) -> Callable[[str], io.BytesIO]:
    """Dispatch by URL: SHA256SUMS or archive bytes."""

    def fake(url: str) -> io.BytesIO:
        if url.endswith("SHA256SUMS"):
            return io.BytesIO(sums_text.encode())
        return io.BytesIO(bz2.compress(FAKE_BINARY))

    return fake


@contextmanager
def _patch_urlopen(side_effect: Callable[[str], io.BytesIO]) -> Iterator[None]:
    with patch(
        "inspect_ai.util._restic._resolver.urllib.request.urlopen",
        side_effect=side_effect,
    ):
        yield


async def test_cache_hit_short_circuits(tmp_path: Path) -> None:
    with _patch_cache_dir(tmp_path):
        target = cache_path(PLATFORM)
        target.write_bytes(b"already-here")

        with patch(
            "inspect_ai.util._restic._resolver.urllib.request.urlopen"
        ) as urlopen:
            result = await resolve_restic(PLATFORM)

        assert result == target
        assert target.read_bytes() == b"already-here"
        urlopen.assert_not_called()


async def test_cache_miss_downloads_and_populates(tmp_path: Path) -> None:
    archive_name = _archive_filename(_read_version(), PLATFORM)
    sums_text = f"{FAKE_BINARY_SHA}  {archive_name}\n"

    with _patch_cache_dir(tmp_path), _patch_urlopen(_make_urlopen(sums_text)):
        target = cache_path(PLATFORM)
        assert not target.exists()

        first = await resolve_restic(PLATFORM)
        assert first == target
        assert target.exists()
        assert target.read_bytes() == FAKE_BINARY

        # Second call should be a cache hit; rewrite the cache to a sentinel
        # and verify the resolver returns the same path without re-downloading.
        target.write_bytes(b"sentinel")
        second = await resolve_restic(PLATFORM)
        assert second == target
        assert target.read_bytes() == b"sentinel"


async def test_sha256_mismatch_raises_and_leaves_cache_clean(tmp_path: Path) -> None:
    archive_name = _archive_filename(_read_version(), PLATFORM)
    sums_text = f"{'0' * 64}  {archive_name}\n"

    with _patch_cache_dir(tmp_path), _patch_urlopen(_make_urlopen(sums_text)):
        target = cache_path(PLATFORM)
        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            await resolve_restic(PLATFORM)
        assert not target.exists()


def _read_version() -> str:
    from inspect_ai.util._restic._resolver import _version

    return _version()
