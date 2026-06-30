"""Tests for the restic binary resolver.

Contracts:
1. A pre-existing cache file short-circuits without downloading.
2. A cache miss downloads the archive via the shared ``download()`` helper
   (passing the archive URL, the expected hash read from the vendored
   SHA256SUMS, and the raised timeout), extracts it, and populates the cache.
3. A download failure (e.g. checksum mismatch) surfaces as ``RuntimeError`` and
   leaves the cache untouched.
4. A missing vendored SHA256SUMS entry raises with a regenerate hint before any
   download is attempted.
5. The committed SHA256SUMS covers every supported platform.

The download is mocked at the resolver's ``download`` import; the expected
checksum comes from a patched vendored SHA256SUMS file. No network, no on-disk
fixtures other than what the test itself writes.
"""

from __future__ import annotations

import bz2
import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from inspect_ai.util._restic.resolver import (
    _DOWNLOAD_TIMEOUT,
    SUPPORTED_PLATFORMS,
    Platform,
    _archive_filename,
    _extract_expected_hash,
    _version,
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
        "inspect_ai.util._restic.resolver.inspect_cache_dir",
        side_effect=fake_cache_dir,
    ):
        yield


@contextmanager
def _patch_sums_file(tmp_path: Path, sums_text: str) -> Iterator[None]:
    """Point the vendored SHA256SUMS path at a tmp file with controlled content."""
    sums_file = tmp_path / "SHA256SUMS"
    sums_file.write_text(sums_text)
    with patch("inspect_ai.util._restic.resolver._SHA256SUMS_FILE", sums_file):
        yield


@contextmanager
def _patch_download(side_effect: Callable[..., Path]) -> Iterator[MagicMock]:
    """Patch the download() helper imported into the resolver."""
    with patch(
        "inspect_ai.util._restic.resolver.download", side_effect=side_effect
    ) as mock:
        yield mock


def _download_writes_archive(
    url: str,
    sha256: str,
    dest: Path,
    *,
    headers: object = None,
    timeout: object = None,
) -> Path:
    """Stand-in for download(): write a valid compressed archive to ``dest``."""
    Path(dest).write_bytes(bz2.compress(FAKE_BINARY))
    return Path(dest)


def _sums_for(archive_name: str, digest: str = FAKE_BINARY_SHA) -> str:
    return f"{digest}  {archive_name}\n"


async def test_cache_hit_short_circuits(tmp_path: Path) -> None:
    with _patch_cache_dir(tmp_path):
        target = cache_path(PLATFORM)
        target.write_bytes(b"already-here")

        with patch("inspect_ai.util._restic.resolver.download") as download_mock:
            result = await resolve_restic(PLATFORM)

        assert result == target
        assert target.read_bytes() == b"already-here"
        download_mock.assert_not_called()


async def test_cache_miss_downloads_and_populates(tmp_path: Path) -> None:
    archive_name = _archive_filename(_version(), PLATFORM)

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name)),
        _patch_download(_download_writes_archive) as download_mock,
    ):
        target = cache_path(PLATFORM)
        assert not target.exists()

        first = await resolve_restic(PLATFORM)
        assert first == target
        assert target.read_bytes() == FAKE_BINARY

        # download() received the archive URL, the hash read from the vendored
        # SHA256SUMS, and the raised timeout.
        call = download_mock.call_args
        assert call.args[0].endswith(archive_name)
        assert call.args[1] == FAKE_BINARY_SHA
        assert call.kwargs["timeout"] == _DOWNLOAD_TIMEOUT

        # Second call is a cache hit: rewrite the cache to a sentinel and verify
        # the resolver returns it without downloading again.
        target.write_bytes(b"sentinel")
        second = await resolve_restic(PLATFORM)
        assert second == target
        assert target.read_bytes() == b"sentinel"
        assert download_mock.call_count == 1


async def test_download_failure_raises_runtime_error_and_leaves_cache_clean(
    tmp_path: Path,
) -> None:
    archive_name = _archive_filename(_version(), PLATFORM)

    def _raise_mismatch(
        url: str,
        sha256: str,
        dest: Path,
        *,
        headers: object = None,
        timeout: object = None,
    ) -> Path:
        raise ValueError(f"Checksum mismatch for {url}: expected {sha256}, got beef")

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name)),
        _patch_download(_raise_mismatch),
    ):
        target = cache_path(PLATFORM)
        with pytest.raises(RuntimeError, match="Failed to download"):
            await resolve_restic(PLATFORM)
        assert not target.exists()


async def test_missing_vendored_entry_raises_before_download(tmp_path: Path) -> None:
    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for("some-other-file.bz2")),
        _patch_download(_download_writes_archive) as download_mock,
    ):
        with pytest.raises(RuntimeError, match="regenerate"):
            await resolve_restic(PLATFORM)
        download_mock.assert_not_called()


def test_vendored_sums_cover_all_supported_platforms() -> None:
    """Check the committed SHA256SUMS covers every supported platform.

    Guards against a forgotten regeneration after a restic version bump.
    """
    from inspect_ai.util._restic.resolver import _SHA256SUMS_FILE

    sums_text = _SHA256SUMS_FILE.read_text()
    version = _version()
    for platform in SUPPORTED_PLATFORMS:
        archive_name = _archive_filename(version, platform)
        digest = _extract_expected_hash(sums_text, archive_name)
        assert len(digest) == 64
