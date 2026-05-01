"""Tests for inspect_ai._util.download."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, patch

import httpx
import pytest
from tenacity import RetryError

from inspect_ai._util.download import download, gdrive_download
from inspect_ai._util.error import PrerequisiteError


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip tenacity retry sleeps so retry-exercising tests are fast."""
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class _FakeStream:
    """Drop-in replacement for the context manager returned by httpx.stream."""

    def __init__(
        self,
        status_code: int,
        content: bytes,
        *,
        raise_during_iter: BaseException | None = None,
    ):
        self._status_code = status_code
        self._content = content
        self._raise_during_iter = raise_during_iter

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self._status_code >= 400:
            request = httpx.Request("GET", "http://test.example")
            response = httpx.Response(self._status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self._status_code}", request=request, response=response
            )

    def iter_bytes(self, chunk_size: int | None = None) -> Iterator[bytes]:
        if self._raise_during_iter is not None:
            raise self._raise_during_iter
        size = chunk_size or 1024
        for start in range(0, len(self._content), size):
            yield self._content[start : start + size]


def _stream_factory(*responses: _FakeStream) -> MagicMock:
    """Return a mock for httpx.stream that yields the given responses in order.

    Captures kwargs (headers, follow_redirects) from each call on `mock.calls`.
    """
    iterator = iter(responses)
    mock = MagicMock()
    mock.calls = []

    def stream(method: str, url: str, **kwargs: object) -> _FakeStream:
        mock.calls.append({"method": method, "url": url, **kwargs})
        return next(iterator)

    mock.side_effect = stream
    return mock


def test_skip_when_file_exists_with_matching_checksum(tmp_path: Path) -> None:
    content = b"already cached"
    dest = tmp_path / "cached.bin"
    dest.write_bytes(content)

    stream_mock = _stream_factory()  # no responses; should not be called
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        result = download("http://example.com/x", _sha256(content), dest)

    assert result == dest
    assert dest.read_bytes() == content
    stream_mock.assert_not_called()


def test_redownload_when_file_exists_with_wrong_checksum(tmp_path: Path) -> None:
    correct = b"the real bytes"
    dest = tmp_path / "f.bin"
    dest.write_bytes(b"stale junk")

    stream_mock = _stream_factory(_FakeStream(200, correct))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        download("http://example.com/x", _sha256(correct), dest)

    assert dest.read_bytes() == correct


def test_successful_download_writes_bytes_and_verifies(tmp_path: Path) -> None:
    content = b"hello world" * 100
    dest = tmp_path / "out.bin"

    stream_mock = _stream_factory(_FakeStream(200, content))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        result = download("http://example.com/x", _sha256(content), dest)

    assert result == dest
    assert dest.read_bytes() == content
    assert not (tmp_path / "out.bin.partial").exists()


def test_checksum_mismatch_raises_and_cleans_up(tmp_path: Path) -> None:
    content = b"actual bytes"
    dest = tmp_path / "f.bin"

    stream_mock = _stream_factory(_FakeStream(200, content))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        with pytest.raises(ValueError, match="Checksum mismatch"):
            download("http://example.com/x", "0" * 64, dest)

    assert not dest.exists()
    assert not (tmp_path / "f.bin.partial").exists()


def test_atomic_write_cleans_partial_on_mid_stream_failure(tmp_path: Path) -> None:
    dest = tmp_path / "f.bin"

    # ReadError is retryable; supply enough failures to exhaust retries (5 attempts).
    stream_mock = _stream_factory(
        *[
            _FakeStream(
                200, b"x" * 100, raise_during_iter=httpx.ReadError("connection dropped")
            )
            for _ in range(5)
        ]
    )
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        with pytest.raises(RetryError):
            download("http://example.com/x", _sha256(b""), dest)

    assert not dest.exists()
    assert not (tmp_path / "f.bin.partial").exists()


def test_5xx_retried_then_succeeds(tmp_path: Path) -> None:
    content = b"finally"
    dest = tmp_path / "f.bin"

    stream_mock = _stream_factory(
        _FakeStream(503, b""),
        _FakeStream(200, content),
    )
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        download("http://example.com/x", _sha256(content), dest)

    assert dest.read_bytes() == content
    assert len(stream_mock.calls) == 2


def test_404_not_retried(tmp_path: Path) -> None:
    dest = tmp_path / "f.bin"

    stream_mock = _stream_factory(_FakeStream(404, b""))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        with pytest.raises(httpx.HTTPStatusError):
            download("http://example.com/x", "0" * 64, dest)

    assert len(stream_mock.calls) == 1
    assert not dest.exists()


def test_429_retried(tmp_path: Path) -> None:
    content = b"ok"
    dest = tmp_path / "f.bin"

    stream_mock = _stream_factory(
        _FakeStream(429, b""),
        _FakeStream(200, content),
    )
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        download("http://example.com/x", _sha256(content), dest)

    assert len(stream_mock.calls) == 2


def test_custom_headers_forwarded(tmp_path: Path) -> None:
    content = b"data"
    dest = tmp_path / "f.bin"
    headers = {"Authorization": "Bearer secret", "X-Custom": "1"}

    stream_mock = _stream_factory(_FakeStream(200, content))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        download("http://example.com/x", _sha256(content), dest, headers=headers)

    assert stream_mock.calls[0]["headers"] == headers


def test_creates_parent_directory(tmp_path: Path) -> None:
    content = b"nested"
    dest = tmp_path / "deep" / "nested" / "f.bin"

    stream_mock = _stream_factory(_FakeStream(200, content))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        download("http://example.com/x", _sha256(content), dest)

    assert dest.read_bytes() == content


def test_gdrive_download_missing_gdown_raises_prerequisite_error(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "g.bin"
    with patch.dict(sys.modules, {"gdown": None}):
        with pytest.raises(PrerequisiteError):
            gdrive_download("file-id", "0" * 64, dest)


def test_gdrive_download_happy_path(tmp_path: Path) -> None:
    content = b"google drive bytes"
    dest = tmp_path / "g.bin"

    fake_gdown = MagicMock()

    def fake_download(*, id: str, output: str, quiet: bool) -> None:
        Path(output).write_bytes(content)

    fake_gdown.download = fake_download

    with patch.dict(sys.modules, {"gdown": fake_gdown}):
        result = gdrive_download("file-id", _sha256(content), dest)

    assert result == dest
    assert dest.read_bytes() == content


def test_gdrive_download_skip_when_checksum_matches(tmp_path: Path) -> None:
    content = b"already there"
    dest = tmp_path / "g.bin"
    dest.write_bytes(content)

    fake_gdown = MagicMock()
    fake_gdown.download = MagicMock(side_effect=AssertionError("should not be called"))

    with patch.dict(sys.modules, {"gdown": fake_gdown}):
        gdrive_download("file-id", _sha256(content), dest)

    fake_gdown.download.assert_not_called()


def test_gdrive_download_checksum_mismatch_cleans_up(tmp_path: Path) -> None:
    dest = tmp_path / "g.bin"

    fake_gdown = MagicMock()

    def fake_download(*, id: str, output: str, quiet: bool) -> None:
        Path(output).write_bytes(b"wrong content")

    fake_gdown.download = fake_download

    with patch.dict(sys.modules, {"gdown": fake_gdown}):
        with pytest.raises(ValueError, match="Checksum mismatch"):
            gdrive_download("file-id", "0" * 64, dest)

    assert not dest.exists()
    assert not (tmp_path / "g.bin.partial").exists()
