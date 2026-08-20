"""Tests for sandbox-tools binary digest verification (SHA256SUMS pinning).

Covers the `_digests` owner module, the verified runtime download path in
`sandbox._download_from_s3`, the committed SHA256SUMS format, and the
verification helpers in `scripts/pypi-release.py`. See
`src/inspect_sandbox_tools/design/BINARY_INTEGRITY.md`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Iterator
from unittest.mock import MagicMock, patch

import httpx
import pytest

import inspect_ai.tool._sandbox_tools_utils.sandbox as sandbox_module
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._sandbox_tools_utils._build_config import filename_to_config
from inspect_ai.tool._sandbox_tools_utils._digests import (
    lookup_digest,
    parse_sha256sums,
    read_sha256sums,
    write_sha256sums,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# _digests.py
# ---------------------------------------------------------------------------


def test_digests_write_read_round_trip(tmp_path: Path) -> None:
    entries = {
        "inspect-sandbox-tools-amd64-v1": "a" * 64,
        "inspect-sandbox-tools-arm64-v1": "b" * 64,
    }
    sums = tmp_path / "SHA256SUMS"
    write_sha256sums(entries, sums)
    assert read_sha256sums(sums) == entries
    # standard sha256sum format: two spaces, sorted by filename, no markers
    lines = sums.read_text().splitlines()
    assert lines == [
        f"{'a' * 64}  inspect-sandbox-tools-amd64-v1",
        f"{'b' * 64}  inspect-sandbox-tools-arm64-v1",
    ]


def test_digests_parse_tolerates_binary_marker_and_case() -> None:
    digest = "AB" * 32
    text = f"{digest} *some-file\n\nnot a sums line\n"
    assert parse_sha256sums(text) == {"some-file": digest.lower()}


def test_digests_lookup_missing_entry_raises(tmp_path: Path) -> None:
    sums = tmp_path / "SHA256SUMS"
    write_sha256sums({"present-file": "c" * 64}, sums)
    assert lookup_digest("present-file", sums) == "c" * 64
    with pytest.raises(RuntimeError, match="No SHA256 entry for absent-file"):
        lookup_digest("absent-file", sums)


def test_digests_unreadable_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="unreadable"):
        read_sha256sums(tmp_path / "does-not-exist")


def test_committed_sha256sums_format() -> None:
    """The committed sums file pins the four arch x libc release artifacts.

    Deliberately does NOT assert that the shared version equals
    sandbox_tools_version.txt's: on a release PR the version bumps at PR-open
    while the sums are rewritten only at post-approval upload, so a lockstep
    assertion here would keep the fast suite red for the whole review window.
    Version lockstep belongs solely to the slow-tool-tests-release CI gate.
    """
    entries = read_sha256sums()
    assert len(entries) == 4
    configs = [filename_to_config(name) for name in entries]
    assert all(config.suffix is None for config in configs)
    assert len({config.version for config in configs}) == 1
    assert {(config.arch, config.musl) for config in configs} == {
        ("amd64", False),
        ("amd64", True),
        ("arm64", False),
        ("arm64", True),
    }


# ---------------------------------------------------------------------------
# sandbox._download_from_s3
# ---------------------------------------------------------------------------


class _FakeStream:
    """Drop-in replacement for the context manager returned by httpx.stream."""

    def __init__(self, status_code: int, content: bytes):
        self._status_code = status_code
        self._content = content

    def __enter__(self) -> "_FakeStream":
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
        size = chunk_size or 1024
        for start in range(0, len(self._content), size):
            yield self._content[start : start + size]


def _stream_factory(*responses: _FakeStream) -> MagicMock:
    iterator = iter(responses)
    mock = MagicMock()
    mock.side_effect = lambda method, url, **kwargs: next(iterator)
    return mock


async def test_download_from_s3_success_verifies_chmods_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"verified binary bytes" * 100
    filename = "inspect-sandbox-tools-amd64-v999"
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(sandbox_module, "lookup_digest", lambda name: _sha256(content))

    stream_mock = _stream_factory(_FakeStream(200, content))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        assert await sandbox_module._download_from_s3(filename) is True

    dest = tmp_path / filename
    assert dest.read_bytes() == content
    assert dest.stat().st_mode & 0o755 == 0o755
    # atomic: no tempfiles or partials left behind
    assert [p.name for p in tmp_path.iterdir()] == [filename]


async def test_download_from_s3_mismatch_raises_and_caches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename = "inspect-sandbox-tools-amd64-v999"
    monkeypatch.setenv(sandbox_module.STRICT_DIGESTS_VAR, "1")
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(sandbox_module, "lookup_digest", lambda name: "0" * 64)

    stream_mock = _stream_factory(_FakeStream(200, b"tampered bytes"))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        with pytest.raises(PrerequisiteError, match="Digest verification failed"):
            await sandbox_module._download_from_s3(filename)

    assert list(tmp_path.iterdir()) == []


async def test_download_from_s3_mismatch_warns_and_proceeds_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename = "inspect-sandbox-tools-amd64-v999"
    monkeypatch.delenv(sandbox_module.STRICT_DIGESTS_VAR, raising=False)
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(sandbox_module, "lookup_digest", lambda name: "0" * 64)

    # First response feeds the (failing) verified attempt; second feeds the
    # unverified re-fetch. Patching httpx.stream via either importer patches
    # the shared httpx module attribute, so one patch covers both call sites.
    stream_mock = _stream_factory(
        _FakeStream(200, b"tampered bytes"), _FakeStream(200, b"tampered bytes")
    )
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        assert await sandbox_module._download_from_s3(filename) is True

    dest = tmp_path / filename
    assert dest.read_bytes() == b"tampered bytes"
    assert dest.stat().st_mode & 0o755 == 0o755
    assert [p.name for p in tmp_path.iterdir()] == [filename]


async def test_download_from_s3_404_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename = "inspect-sandbox-tools-amd64-v999"
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(sandbox_module, "lookup_digest", lambda name: "0" * 64)

    stream_mock = _stream_factory(_FakeStream(404, b""))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        assert await sandbox_module._download_from_s3(filename) is False

    assert list(tmp_path.iterdir()) == []


async def test_download_from_s3_missing_sums_entry_raises_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sums = tmp_path / "SHA256SUMS"
    write_sha256sums({"some-other-file": "d" * 64}, sums)
    monkeypatch.setenv(sandbox_module.STRICT_DIGESTS_VAR, "1")
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(
        sandbox_module, "lookup_digest", lambda name: lookup_digest(name, sums)
    )

    stream_mock = _stream_factory()
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        with pytest.raises(RuntimeError, match="No SHA256 entry"):
            await sandbox_module._download_from_s3("inspect-sandbox-tools-amd64-v999")

    stream_mock.assert_not_called()


async def test_download_from_s3_missing_sums_entry_warns_and_downloads_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename = "inspect-sandbox-tools-amd64-v999"
    sums = tmp_path / "SHA256SUMS"
    write_sha256sums({"some-other-file": "d" * 64}, sums)
    monkeypatch.delenv(sandbox_module.STRICT_DIGESTS_VAR, raising=False)
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(
        sandbox_module, "lookup_digest", lambda name: lookup_digest(name, sums)
    )

    content = b"unverified binary bytes"
    stream_mock = _stream_factory(_FakeStream(200, content))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        assert await sandbox_module._download_from_s3(filename) is True

    dest = tmp_path / filename
    assert dest.read_bytes() == content
    assert dest.stat().st_mode & 0o755 == 0o755
    assert sorted(p.name for p in tmp_path.iterdir()) == ["SHA256SUMS", filename]


# ---------------------------------------------------------------------------
# scripts/pypi-release.py verification helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pypi_release() -> ModuleType:
    script = Path(__file__).parents[3] / "scripts" / "pypi-release.py"
    spec = importlib.util.spec_from_file_location("pypi_release", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeUrlResponse:
    def __init__(self, content: bytes):
        self._content = content
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self) -> "_FakeUrlResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, n: int) -> bytes:
        chunk, self._content = self._content[:n], self._content[n:]
        return chunk


def test_pypi_download_file_verifies_and_lands_atomically(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"wheel-bound binary"
    dest = tmp_path / "artifact"
    monkeypatch.setattr(
        pypi_release.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeUrlResponse(content),
    )

    assert pypi_release.download_file("http://x", dest, _sha256(content)) is True
    assert dest.read_bytes() == content
    assert dest.stat().st_mode & 0o755 == 0o755
    assert not (tmp_path / "artifact.partial").exists()


def test_pypi_download_file_mismatch_fails_and_writes_nothing(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "artifact"
    monkeypatch.setattr(
        pypi_release.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeUrlResponse(b"tampered"),
    )

    assert pypi_release.download_file("http://x", dest, "0" * 64) is False
    assert not dest.exists()
    assert not (tmp_path / "artifact.partial").exists()


def test_pypi_check_exist_rejects_wrong_digest(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binaries = tmp_path / "src" / "inspect_ai" / "binaries"
    binaries.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    (binaries / "inspect-sandbox-tools-amd64-v9").write_bytes(b"stale")
    (binaries / "inspect-sandbox-tools-arm64-v9").write_bytes(b"stale")
    digests = {
        "inspect-sandbox-tools-amd64-v9": _sha256(b"fresh"),
        "inspect-sandbox-tools-arm64-v9": _sha256(b"fresh"),
    }
    assert pypi_release.check_sandbox_tools_exist("9", digests) is False

    (binaries / "inspect-sandbox-tools-amd64-v9").write_bytes(b"fresh")
    (binaries / "inspect-sandbox-tools-arm64-v9").write_bytes(b"fresh")
    assert pypi_release.check_sandbox_tools_exist("9", digests) is True


def test_pypi_pre_build_gate(pypi_release: ModuleType, tmp_path: Path) -> None:
    amd64, arm64 = (
        "inspect-sandbox-tools-amd64-v9",
        "inspect-sandbox-tools-arm64-v9",
    )
    digests = {amd64: _sha256(b"amd64 bytes"), arm64: _sha256(b"arm64 bytes")}

    # missing artifact
    with pytest.raises(RuntimeError, match="must contain exactly"):
        pypi_release.verify_sandbox_tools_bundle("9", digests, tmp_path)

    (tmp_path / amd64).write_bytes(b"amd64 bytes")
    (tmp_path / arm64).write_bytes(b"arm64 bytes")
    pypi_release.verify_sandbox_tools_bundle("9", digests, tmp_path)

    # extra file
    extra = tmp_path / "inspect-sandbox-tools-amd64-v8"
    extra.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="must contain exactly"):
        pypi_release.verify_sandbox_tools_bundle("9", digests, tmp_path)
    extra.unlink()

    # wrong digest
    (tmp_path / amd64).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="does not match its pinned digest"):
        pypi_release.verify_sandbox_tools_bundle("9", digests, tmp_path)


def test_pypi_wheel_contents_gate(pypi_release: ModuleType, tmp_path: Path) -> None:
    required = [
        "inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS",
        "inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt",
        "inspect_ai/binaries/inspect-sandbox-tools-amd64-v9",
        "inspect_ai/binaries/inspect-sandbox-tools-arm64-v9",
    ]

    complete = tmp_path / "complete.whl"
    with zipfile.ZipFile(complete, "w") as wheel:
        for member in required:
            wheel.writestr(member, "content")
    pypi_release.verify_wheel_contents(complete, "9")

    incomplete = tmp_path / "incomplete.whl"
    with zipfile.ZipFile(incomplete, "w") as wheel:
        for member in required[1:]:
            wheel.writestr(member, "content")
    with pytest.raises(RuntimeError, match="SHA256SUMS"):
        pypi_release.verify_wheel_contents(incomplete, "9")
