"""Tests for the restic binary resolver.

Contracts:
1. A pre-existing cache file short-circuits without invoking the network.
2. A cache miss downloads the archive, verifies it against the vendored
   SHA256SUMS (read from disk, not fetched), and populates the cache.
3. The SHA256SUMS file is read locally; only the archive is fetched.
4. A SHA256 mismatch raises and leaves the cache untouched.
5. A missing vendored SHA256SUMS entry raises with a regenerate hint.
6. The committed SHA256SUMS covers every supported platform.

The archive is mocked at the urllib layer; the expected checksum comes from a
patched vendored SHA256SUMS file. No network, no on-disk fixtures other than
what the test itself writes.
"""

from __future__ import annotations

import bz2
import hashlib
import io
import urllib.error
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from inspect_ai.util._restic.resolver import (
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


def _archive_urlopen() -> Callable[..., io.BytesIO]:
    """Urlopen stub returning the fake compressed archive for any URL."""

    def fake(url: str, *args: object, **kwargs: object) -> io.BytesIO:
        return io.BytesIO(bz2.compress(FAKE_BINARY))

    return fake


@contextmanager
def _patch_urlopen(side_effect: Callable[..., io.BytesIO]) -> Iterator[None]:
    with patch(
        "inspect_ai.util._restic.resolver.urllib.request.urlopen",
        side_effect=side_effect,
    ):
        yield


def _sums_for(archive_name: str, digest: str = FAKE_BINARY_SHA) -> str:
    return f"{digest}  {archive_name}\n"


async def test_cache_hit_short_circuits(tmp_path: Path) -> None:
    with _patch_cache_dir(tmp_path):
        target = cache_path(PLATFORM)
        target.write_bytes(b"already-here")

        with patch(
            "inspect_ai.util._restic.resolver.urllib.request.urlopen"
        ) as urlopen:
            result = await resolve_restic(PLATFORM)

        assert result == target
        assert target.read_bytes() == b"already-here"
        urlopen.assert_not_called()


async def test_cache_miss_downloads_and_populates(tmp_path: Path) -> None:
    archive_name = _archive_filename(_version(), PLATFORM)

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name)),
        _patch_urlopen(_archive_urlopen()),
    ):
        target = cache_path(PLATFORM)
        assert not target.exists()

        first = await resolve_restic(PLATFORM)
        assert first == target
        assert target.exists()
        assert target.read_bytes() == FAKE_BINARY

        # Second call is a cache hit: rewrite the cache to a sentinel and
        # verify the resolver returns it without re-downloading.
        target.write_bytes(b"sentinel")
        second = await resolve_restic(PLATFORM)
        assert second == target
        assert target.read_bytes() == b"sentinel"


async def test_sums_are_read_locally_not_fetched(tmp_path: Path) -> None:
    archive_name = _archive_filename(_version(), PLATFORM)

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name)),
    ):
        with patch(
            "inspect_ai.util._restic.resolver.urllib.request.urlopen",
            side_effect=_archive_urlopen(),
        ) as urlopen:
            await resolve_restic(PLATFORM)

    assert urlopen.call_count == 1
    called_url = urlopen.call_args.args[0]
    assert called_url.endswith(archive_name)
    assert not called_url.endswith("SHA256SUMS")


async def test_sha256_mismatch_raises_and_leaves_cache_clean(tmp_path: Path) -> None:
    archive_name = _archive_filename(_version(), PLATFORM)

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name, "0" * 64)),
        _patch_urlopen(_archive_urlopen()),
    ):
        target = cache_path(PLATFORM)
        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            await resolve_restic(PLATFORM)
        assert not target.exists()


async def test_missing_vendored_entry_raises_with_hint(tmp_path: Path) -> None:
    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for("some-other-file.bz2")),
        _patch_urlopen(_archive_urlopen()),
    ):
        with pytest.raises(RuntimeError, match="regenerate"):
            await resolve_restic(PLATFORM)


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


async def test_archive_download_retries_transient_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _s: None)
    archive_name = _archive_filename(_version(), PLATFORM)
    calls = {"n": 0}

    def flaky(url: str, *args: object, **kwargs: object) -> io.BytesIO:
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("temporary failure")
        return io.BytesIO(bz2.compress(FAKE_BINARY))

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name)),
        _patch_urlopen(flaky),
    ):
        result = await resolve_restic(PLATFORM)
        assert result.exists()
        assert result.read_bytes() == FAKE_BINARY
    assert calls["n"] == 3


async def test_archive_download_does_not_retry_permanent_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _s: None)
    archive_name = _archive_filename(_version(), PLATFORM)
    calls = {"n": 0}

    def not_found(url: str, *args: object, **kwargs: object) -> io.BytesIO:
        calls["n"] += 1
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)  # type: ignore[arg-type]

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name)),
        _patch_urlopen(not_found),
    ):
        with pytest.raises(RuntimeError, match="Failed to download"):
            await resolve_restic(PLATFORM)
    assert calls["n"] == 1


async def test_archive_download_gives_up_after_max_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _s: None)
    archive_name = _archive_filename(_version(), PLATFORM)
    calls = {"n": 0}

    def always_fail(url: str, *args: object, **kwargs: object) -> io.BytesIO:
        calls["n"] += 1
        raise urllib.error.URLError("down")

    with (
        _patch_cache_dir(tmp_path),
        _patch_sums_file(tmp_path, _sums_for(archive_name)),
        _patch_urlopen(always_fail),
    ):
        with pytest.raises(RuntimeError, match="Failed to download"):
            await resolve_restic(PLATFORM)
    assert calls["n"] == 5
