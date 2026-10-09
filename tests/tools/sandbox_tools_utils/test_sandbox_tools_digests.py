"""Tests for sandbox-tools binary digest verification (SHA256SUMS pinning).

Covers the `_digests` owner module, the verified runtime download path in
`sandbox._download_from_s3`, the committed SHA256SUMS format, and the
verification helpers in `scripts/pypi-release.py`. See
`src/inspect_sandbox_tools/design/BINARY_INTEGRITY.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import zipfile
from email.message import Message
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
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(sandbox_module, "lookup_digest", lambda name: "0" * 64)

    stream_mock = _stream_factory(_FakeStream(200, b"tampered bytes"))
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        with pytest.raises(PrerequisiteError, match="Digest verification failed"):
            await sandbox_module._download_from_s3(filename)

    assert list(tmp_path.iterdir()) == []
    stream_mock.assert_called_once()


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
    monkeypatch.setattr(sandbox_module, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(
        sandbox_module, "lookup_digest", lambda name: lookup_digest(name, sums)
    )

    stream_mock = _stream_factory()
    with patch("inspect_ai._util.download.httpx.stream", stream_mock):
        with pytest.raises(PrerequisiteError, match="No SHA256 entry"):
            await sandbox_module._download_from_s3("inspect-sandbox-tools-amd64-v999")

    stream_mock.assert_not_called()
    assert [p.name for p in tmp_path.iterdir()] == ["SHA256SUMS"]


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

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self._content)
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


_WHEEL_GLOBS = ["binaries/*", "**/*.yml", "_view/dist/**/*", "py.typed"]


def _wheel_members(version: str = "9") -> dict[str, bytes]:
    return {
        "inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS": b"sums",
        "inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt": b"9",
        f"inspect_ai/binaries/inspect-sandbox-tools-amd64-v{version}": b"amd64",
        f"inspect_ai/binaries/inspect-sandbox-tools-arm64-v{version}": b"arm64",
        "inspect_ai/_view/dist/index.html": b"<html>",
        "inspect_ai/_view/dist/assets/index.js": b"js",
        "inspect_ai/_view/dist/assets/index.css": b"css",
        "inspect_ai/_util/config.yml": b"key: value",
        "inspect_ai/py.typed": b"",
    }


def _write_wheel(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as wheel:
        for name, content in members.items():
            wheel.writestr(name, content)
    return path


def test_pypi_wheel_contents_gate(pypi_release: ModuleType, tmp_path: Path) -> None:
    complete = _write_wheel(tmp_path / "complete.whl", _wheel_members())
    pypi_release.verify_wheel_contents(complete, "9", _WHEEL_GLOBS)


@pytest.mark.parametrize(
    "change,error",
    [
        (
            {"inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS": None},
            "SHA256SUMS is missing",
        ),
        (
            {"inspect_ai/binaries/inspect-sandbox-tools-amd64-v9": b""},
            "amd64-v9 is empty",
        ),
        ({"inspect_ai/_view/dist/index.html": None}, "index.html is missing"),
        ({"inspect_ai/_view/dist/assets/index.css": None}, "viewer .css assets"),
        ({"inspect_ai/_util/config.yml": None}, r"'\*\*/\*\.yml' matches no files"),
        ({"inspect_ai/_util/config.yml": b""}, r"'\*\*/\*\.yml' has empty files"),
    ],
)
def test_pypi_wheel_contents_gate_rejects(
    pypi_release: ModuleType,
    tmp_path: Path,
    change: dict[str, bytes | None],
    error: str,
) -> None:
    members = {
        name: content
        for name, content in {**_wheel_members(), **change}.items()
        if content is not None
    }
    wheel = _write_wheel(tmp_path / "bad.whl", members)
    with pytest.raises(RuntimeError, match=error):
        pypi_release.verify_wheel_contents(wheel, "9", _WHEEL_GLOBS)


@pytest.mark.parametrize(
    "pattern,name,matches",
    [
        ("**/*.yml", "inspect_ai/a.yml", True),
        ("**/*.yml", "inspect_ai/x/y/a.yml", True),
        ("**/*.yml", "inspect_ai/a.yaml", False),
        ("binaries/*", "inspect_ai/binaries/tool", True),
        ("binaries/*", "inspect_ai/binaries/sub/tool", False),
        ("_view/dist/**/*", "inspect_ai/_view/dist/assets/index.js", True),
        ("py.typed", "inspect_ai/py.typed", True),
        ("py.typed", "inspect_ai/pyXtyped", False),
    ],
)
def test_pypi_package_data_regex(
    pypi_release: ModuleType, pattern: str, name: str, matches: bool
) -> None:
    assert bool(pypi_release._package_data_regex(pattern).fullmatch(name)) is matches


def test_committed_package_data_globs_match_source_files(
    pypi_release: ModuleType,
) -> None:
    """Every package-data glob but the downloaded binaries matches a source file.

    A stale entry would otherwise fail the release's wheel gate.
    """
    package = Path(__file__).parents[3] / "src" / "inspect_ai"
    files = [
        "inspect_ai/" + p.relative_to(package).as_posix()
        for p in package.rglob("*")
        if p.is_file() and "ts-mono" not in p.parts
    ]
    globs = pypi_release.read_package_data_globs()
    assert "binaries/*" in globs
    for pattern in globs:
        if pattern != "binaries/*":
            regex = pypi_release._package_data_regex(pattern)
            assert any(regex.fullmatch(f) for f in files), pattern


def _write_dist(dist: Path, wheel_version: str, sdist_version: str) -> None:
    dist.mkdir()
    _write_wheel(
        dist / f"inspect_ai-{wheel_version}-py3-none-any.whl", _wheel_members()
    )
    (dist / f"inspect_ai-{sdist_version}.tar.gz").write_bytes(b"sdist")


@pytest.fixture
def wheel_globs(pypi_release: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pypi_release, "read_package_data_globs", lambda: _WHEEL_GLOBS)


@pytest.mark.usefixtures("wheel_globs")
def test_pypi_verify_dist_accepts_matching_version(
    pypi_release: ModuleType, tmp_path: Path
) -> None:
    _write_dist(tmp_path / "dist", "0.3.278", "0.3.278")
    pypi_release.verify_dist(tmp_path / "dist", "0.3.278", "9")


@pytest.mark.usefixtures("wheel_globs")
@pytest.mark.parametrize(
    "wheel_version,sdist_version,bad",
    [
        ("0.3.279.dev1+g1234567", "0.3.278", "whl"),
        ("0.3.278", "0.3.278+d20261008", "tar.gz"),
    ],
)
def test_pypi_verify_dist_rejects_version_mismatch(
    pypi_release: ModuleType,
    tmp_path: Path,
    wheel_version: str,
    sdist_version: str,
    bad: str,
) -> None:
    _write_dist(tmp_path / "dist", wheel_version, sdist_version)
    with pytest.raises(
        RuntimeError, match=rf"\.{bad} has version .*, expected 0\.3\.278"
    ):
        pypi_release.verify_dist(tmp_path / "dist", "0.3.278", "9")


@pytest.mark.usefixtures("wheel_globs")
def test_pypi_verify_dist_rejects_unexpected_files(
    pypi_release: ModuleType, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    with pytest.raises(RuntimeError, match="exactly one wheel and one sdist"):
        pypi_release.verify_dist(dist, "0.3.278", "9")

    _write_dist(dist, "0.3.278", "0.3.278")
    (dist / "inspect_ai-0.3.277.tar.gz").write_bytes(b"stale sdist")
    with pytest.raises(RuntimeError, match="exactly one wheel and one sdist"):
        pypi_release.verify_dist(dist, "0.3.278", "9")


@pytest.mark.usefixtures("wheel_globs")
def test_pypi_verify_dist_runs_wheel_gate(
    pypi_release: ModuleType, tmp_path: Path
) -> None:
    _write_dist(tmp_path / "dist", "0.3.278", "0.3.278")
    with pytest.raises(RuntimeError, match="inspect-sandbox-tools-amd64-v10"):
        pypi_release.verify_dist(tmp_path / "dist", "0.3.278", "10")


def _prepare_repo(tmp_path: Path, digests: dict[str, str]) -> Path:
    utils = tmp_path / "src" / "inspect_ai" / "tool" / "_sandbox_tools_utils"
    utils.mkdir(parents=True)
    (utils / "sandbox_tools_version.txt").write_text("9\n")
    write_sha256sums(digests, utils / "SHA256SUMS")
    return tmp_path / "src" / "inspect_ai" / "binaries"


def test_pypi_prepare_downloads_verifies_and_removes_stale(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = {
        "inspect-sandbox-tools-amd64-v9": b"amd64 bytes",
        "inspect-sandbox-tools-arm64-v9": b"arm64 bytes",
    }
    binaries = _prepare_repo(
        tmp_path, {name: _sha256(content) for name, content in artifacts.items()}
    )
    binaries.mkdir()
    (binaries / "inspect-sandbox-tools-amd64-v8").write_bytes(b"old")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        pypi_release.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeUrlResponse(artifacts[url.rsplit("/", 1)[1]]),
    )

    pypi_release.prepare_command(argparse.Namespace())

    assert {f.name: f.read_bytes() for f in binaries.iterdir()} == artifacts


def test_pypi_prepare_fails_on_digest_mismatch(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binaries = _prepare_repo(
        tmp_path,
        {
            "inspect-sandbox-tools-amd64-v9": _sha256(b"amd64 bytes"),
            "inspect-sandbox-tools-arm64-v9": _sha256(b"arm64 bytes"),
        },
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        pypi_release.urllib.request,
        "urlopen",
        lambda url, timeout: _FakeUrlResponse(b"tampered"),
    )

    with pytest.raises(SystemExit) as exit_info:
        pypi_release.prepare_command(argparse.Namespace())
    assert exit_info.value.code == 1
    assert list(binaries.iterdir()) == []


_PUBLISHED = {
    "inspect-sandbox-tools-amd64-v9": b"amd64 bytes",
    "inspect-sandbox-tools-arm64-v9": b"arm64 bytes",
    "inspect-sandbox-tools-amd64-musl-v9": b"amd64 musl bytes",
    "inspect-sandbox-tools-arm64-musl-v9": b"arm64 musl bytes",
}


def _serve(
    pypi_release: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    published: dict[str, bytes],
) -> list[str]:
    requested: list[str] = []

    def urlopen(url: str, timeout: float) -> _FakeUrlResponse:
        requested.append(url)
        name = url.rsplit("/", 1)[1]
        if name not in published:
            raise urllib.error.HTTPError(url, 403, "Forbidden", Message(), None)
        return _FakeUrlResponse(published[name])

    monkeypatch.setattr(pypi_release.urllib.request, "urlopen", urlopen)
    return requested


def test_pypi_verify_sandbox_tools_published_checks_every_pinned_artifact(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested = _serve(pypi_release, monkeypatch, _PUBLISHED)
    digests = {name: _sha256(content) for name, content in _PUBLISHED.items()}

    pypi_release.verify_sandbox_tools_published("9", digests, tmp_path)

    assert sorted(requested) == sorted(
        f"{pypi_release.SANDBOX_TOOLS_BASE_URL}/{name}" for name in _PUBLISHED
    )


@pytest.mark.parametrize(
    "published",
    [
        # musl build never uploaded (the #5685/#5716 class)
        {k: v for k, v in _PUBLISHED.items() if "arm64-musl" not in k},
        # uploaded, but not the build SHA256SUMS pins
        {**_PUBLISHED, "inspect-sandbox-tools-amd64-v9": b"rebuilt"},
    ],
    ids=["missing", "digest-mismatch"],
)
def test_pypi_verify_sandbox_tools_published_rejects(
    pypi_release: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    published: dict[str, bytes],
) -> None:
    requested = _serve(pypi_release, monkeypatch, published)
    digests = {name: _sha256(content) for name, content in _PUBLISHED.items()}

    with pytest.raises(RuntimeError, match="Not published") as error:
        pypi_release.verify_sandbox_tools_published("9", digests, tmp_path)
    (bad,) = set(_PUBLISHED) - {
        k for k, v in published.items() if _PUBLISHED.get(k) == v
    }
    assert repr([bad]) in str(error.value)
    # keeps checking after a failure, so one run reports every bad artifact
    assert len(requested) == len(_PUBLISHED)


def test_pypi_verify_sandbox_tools_published_requires_pinned_version(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested = _serve(pypi_release, monkeypatch, _PUBLISHED)
    digests = {"inspect-sandbox-tools-amd64-v8": _sha256(b"old")}

    with pytest.raises(RuntimeError, match="has no digest for"):
        pypi_release.verify_sandbox_tools_published("9", digests, tmp_path)
    assert requested == []


def test_pypi_verify_sandbox_tools_published_command(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_repo(
        tmp_path, {name: _sha256(content) for name, content in _PUBLISHED.items()}
    )
    monkeypatch.chdir(tmp_path)
    _serve(pypi_release, monkeypatch, _PUBLISHED)
    pypi_release.verify_sandbox_tools_published_command(argparse.Namespace())

    _serve(pypi_release, monkeypatch, {})
    with pytest.raises(SystemExit) as exit_info:
        pypi_release.verify_sandbox_tools_published_command(argparse.Namespace())
    assert exit_info.value.code == 1
    # nothing downloaded into the tree
    assert not (tmp_path / "src" / "inspect_ai" / "binaries").exists()


def _write_sdist(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as sdist:
        for name, content in members.items():
            info = tarfile.TarInfo(f"inspect_ai-0.3.277/{name}")
            info.size = len(content)
            sdist.addfile(info, io.BytesIO(content))
    return path


def _scm_version(branch: str, node: str = "gaa20052a6") -> bytes:
    return json.dumps({"tag": "0.3.277", "node": node, "branch": branch}).encode()


_WHEEL = "inspect_ai-0.3.277-py3-none-any.whl"
_SDIST = "inspect_ai-0.3.277.tar.gz"
_SDIST_MEMBERS = {
    "PKG-INFO": b"Version: 0.3.277",
    "src/inspect_ai.egg-info/scm_version.json": _scm_version("main"),
}


def _publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pypi_release: ModuleType
) -> Path:
    """Serve a fake PyPI release of 0.3.277 and return the local dist dir."""
    published = tmp_path / "published"
    published.mkdir()
    files = {
        _WHEEL: _write_wheel(published / _WHEEL, _wheel_members()).read_bytes(),
        _SDIST: _write_sdist(published / _SDIST, _SDIST_MEMBERS).read_bytes(),
    }
    release = {
        "urls": [
            {
                "filename": name,
                "packagetype": "bdist_wheel" if name.endswith(".whl") else "sdist",
                "url": f"https://files.example/{name}",
                "digests": {"sha256": _sha256(content)},
            }
            for name, content in files.items()
        ]
    }

    def urlopen(url: str, timeout: int) -> _FakeUrlResponse:
        if url == pypi_release.PYPI_JSON_URL.format(version="0.3.277"):
            return _FakeUrlResponse(json.dumps(release).encode())
        return _FakeUrlResponse(files[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(pypi_release.urllib.request, "urlopen", urlopen)
    dist = tmp_path / "dist"
    dist.mkdir()
    return dist


def _build_wheel(path: Path, members: dict[str, bytes], year: int) -> Path:
    """A wheel whose archive metadata (timestamps) depends on `year`."""
    with zipfile.ZipFile(path, "w") as wheel:
        for name, content in members.items():
            wheel.writestr(
                zipfile.ZipInfo(name, date_time=(year, 1, 1, 0, 0, 0)), content
            )
    return path


def _build_sdist(path: Path, members: dict[str, bytes], mtime: int) -> Path:
    with tarfile.open(path, "w:gz") as sdist:
        for name, content in members.items():
            info = tarfile.TarInfo(f"inspect_ai-0.3.277/{name}")
            info.size = len(content)
            info.mtime = mtime
            sdist.addfile(info, io.BytesIO(content))
    return path


def _sdist_members(branch: str) -> dict[str, bytes]:
    return {
        **_SDIST_MEMBERS,
        "src/inspect_ai.egg-info/scm_version.json": _scm_version(branch),
    }


def _serve_pypi(
    pypi_release: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, bytes],
) -> list[str]:
    """Serve `files` as PyPI's release of 0.3.277; return downloaded filenames."""
    downloaded: list[str] = []
    release = {
        "urls": [
            {
                "filename": name,
                "url": f"https://files.example/{name}",
                "digests": {"sha256": _sha256(content)},
            }
            for name, content in files.items()
        ]
    }

    def urlopen(url: str, timeout: int) -> _FakeUrlResponse:
        if url == pypi_release.PYPI_JSON_URL.format(version="0.3.277"):
            if not files:
                raise urllib.error.HTTPError(url, 404, "Not Found", Message(), None)
            return _FakeUrlResponse(json.dumps(release).encode())
        name = url.rsplit("/", 1)[1]
        downloaded.append(name)
        return _FakeUrlResponse(files[name])

    monkeypatch.setattr(pypi_release.urllib.request, "urlopen", urlopen)
    return downloaded


def _rebuild(tmp_path: Path) -> Path:
    """The release rebuilt on retry: same contents, different archive metadata.

    The sdist also records the CI checkout's branch, which parity ignores.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    _build_wheel(dist / _WHEEL, _wheel_members(), 2027)
    _build_sdist(dist / _SDIST, _sdist_members("HEAD"), 1_800_000_000)
    return dist


def _original() -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as tmp:
        return {
            _WHEEL: _build_wheel(
                Path(tmp) / _WHEEL, _wheel_members(), 2026
            ).read_bytes(),
            _SDIST: _build_sdist(
                Path(tmp) / _SDIST, _sdist_members("main"), 1_700_000_000
            ).read_bytes(),
        }


def test_pypi_skip_published_accepts_a_rebuild_with_different_archive_metadata(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _original()
    downloaded = _serve_pypi(pypi_release, monkeypatch, original)
    dist = _rebuild(tmp_path)
    for name, content in original.items():
        assert _sha256((dist / name).read_bytes()) != _sha256(content)

    skipped = pypi_release.skip_published_dists(dist, "0.3.277", tmp_path / "done")

    assert skipped == sorted([_WHEEL, _SDIST])
    assert list(dist.iterdir()) == []
    assert sorted(downloaded) == sorted([_WHEEL, _SDIST])


def test_pypi_skip_published_partial_publication_leaves_the_rest_to_upload(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wheel was uploaded before the failure; the rebuilt sdist still goes up."""
    _serve_pypi(pypi_release, monkeypatch, {_WHEEL: _original()[_WHEEL]})
    dist = _rebuild(tmp_path)

    skipped = pypi_release.skip_published_dists(dist, "0.3.277", tmp_path / "done")

    assert skipped == [_WHEEL]
    assert [p.name for p in dist.iterdir()] == [_SDIST]


def test_pypi_skip_published_identical_file_is_not_downloaded(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _original()
    downloaded = _serve_pypi(pypi_release, monkeypatch, original)
    dist = tmp_path / "dist"
    dist.mkdir()
    for name, content in original.items():
        (dist / name).write_bytes(content)

    skipped = pypi_release.skip_published_dists(dist, "0.3.277", tmp_path / "done")

    assert skipped == sorted([_WHEEL, _SDIST])
    assert downloaded == []


@pytest.mark.parametrize(
    "members,difference",
    [
        (
            {**_wheel_members(), "inspect_ai/_view/dist/index.html": b"<html>v2"},
            "differing ['inspect_ai/_view/dist/index.html']",
        ),
        (
            {**_wheel_members(), "inspect_ai/new.py": b"x"},
            "extra ['inspect_ai/new.py']",
        ),
    ],
    ids=["changed-member", "extra-member"],
)
def test_pypi_skip_published_rejects_different_contents(
    pypi_release: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    members: dict[str, bytes],
    difference: str,
) -> None:
    _serve_pypi(pypi_release, monkeypatch, _original())
    dist = _rebuild(tmp_path)
    _build_wheel(dist / _WHEEL, members, 2027)

    with pytest.raises(RuntimeError, match="different contents") as error:
        pypi_release.skip_published_dists(dist, "0.3.277", tmp_path / "done")
    assert difference in str(error.value)
    assert (dist / _WHEEL).exists()


def test_pypi_skip_published_rejects_an_unreadable_build(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_pypi(pypi_release, monkeypatch, _original())
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / _WHEEL).write_bytes(b"not a zip")

    with pytest.raises(RuntimeError, match="Could not compare"):
        pypi_release.skip_published_dists(dist, "0.3.277", tmp_path / "done")


def test_pypi_skip_published_keeps_everything_for_a_new_version(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_pypi(pypi_release, monkeypatch, {})
    dist = _rebuild(tmp_path)
    assert pypi_release.skip_published_dists(dist, "0.3.277", tmp_path / "done") == []
    assert sorted(p.name for p in dist.iterdir()) == sorted([_WHEEL, _SDIST])


def test_pypi_skip_published_command_fails_when_pypi_is_unreachable(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    def urlopen(url: str, timeout: int) -> _FakeUrlResponse:
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(pypi_release.urllib.request, "urlopen", urlopen)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exit_info:
        pypi_release.skip_published_command(
            argparse.Namespace(
                version="0.3.278", dist_dir="dist", published_dir="dist-published"
            )
        )
    assert exit_info.value.code == 1


def test_pypi_verify_parity_accepts_identical_build(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = _publish(tmp_path, monkeypatch, pypi_release)
    _write_wheel(dist / _WHEEL, _wheel_members())
    # a detached tag checkout records branch "HEAD"; that alone is not a diff
    _write_sdist(
        dist / _SDIST,
        {
            **_SDIST_MEMBERS,
            "src/inspect_ai.egg-info/scm_version.json": _scm_version("HEAD"),
        },
    )
    pypi_release.verify_parity(dist, "0.3.277")


def test_pypi_verify_parity_reports_differences(
    pypi_release: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dist = _publish(tmp_path, monkeypatch, pypi_release)
    wheel = _wheel_members()
    del wheel["inspect_ai/binaries/inspect-sandbox-tools-amd64-v9"]
    wheel["inspect_ai/_view/dist/assets/index.js"] = b"rebuilt js"
    wheel["inspect_ai/_view/dist/assets/index.js.map"] = b"map"
    _write_wheel(dist / _WHEEL, wheel)
    _write_sdist(
        dist / _SDIST,
        {
            **_SDIST_MEMBERS,
            "src/inspect_ai.egg-info/scm_version.json": _scm_version("HEAD", "g0"),
        },
    )

    with caplog.at_level("INFO"), pytest.raises(RuntimeError, match="differ from PyPI"):
        pypi_release.verify_parity(dist, "0.3.277")
    assert f"{_WHEEL}: missing from build: inspect_ai/binaries/" in caplog.text
    assert "extra in build: inspect_ai/_view/dist/assets/index.js.map" in caplog.text
    assert "content differs: inspect_ai/_view/dist/assets/index.js" in caplog.text
    assert "content differs: src/inspect_ai.egg-info/scm_version.json" in caplog.text
    assert "1 missing, 1 extra, 1 differing" in caplog.text


def test_pypi_verify_parity_requires_published_files_built(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = _publish(tmp_path, monkeypatch, pypi_release)
    _write_wheel(dist / _WHEEL, _wheel_members())
    with pytest.raises(RuntimeError, match=f"{_SDIST} was not built"):
        pypi_release.verify_parity(dist, "0.3.277")


def test_pypi_verify_parity_rejects_digest_mismatch(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = _publish(tmp_path, monkeypatch, pypi_release)
    real = pypi_release.urllib.request.urlopen
    monkeypatch.setattr(
        pypi_release.urllib.request,
        "urlopen",
        lambda url, timeout: (
            _FakeUrlResponse(b"tampered")
            if url.endswith(_WHEEL)
            else real(url, timeout)
        ),
    )
    with pytest.raises(RuntimeError, match=f"Could not download {_WHEEL}"):
        pypi_release.verify_parity(dist, "0.3.277")


_RELEASE_SCRIPT = Path(__file__).parents[3] / "scripts" / "pypi-release.py"
_COMMANDS = [
    "release",
    "sandbox-tools-download",
    "prepare",
    "verify-dist",
    "verify-parity",
    "verify-sandbox-tools-published",
    "skip-published",
]


@pytest.mark.parametrize("command", _COMMANDS)
def test_pypi_release_script_loads_without_a_toml_library(command: str) -> None:
    """Only the wheel gate reads pyproject.toml; every command starts without it."""
    blocked = (
        "import runpy, sys; "
        "sys.modules['tomllib'] = sys.modules['tomli'] = None; "
        f"sys.argv = [{str(_RELEASE_SCRIPT)!r}, {command!r}, '--help']; "
        f"runpy.run_path({str(_RELEASE_SCRIPT)!r}, run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-c", blocked], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_pypi_read_package_data_globs_without_a_toml_library(
    pypi_release: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "tomllib", None)
    monkeypatch.setitem(sys.modules, "tomli", None)
    with pytest.raises(RuntimeError, match="requires tomli"):
        pypi_release.read_package_data_globs()


@pytest.mark.skipif(shutil.which("python3.10") is None, reason="needs python3.10")
@pytest.mark.parametrize("command", ["sandbox-tools-download", "release"])
def test_pypi_release_script_runs_on_bare_python_310(command: str) -> None:
    """Python 3.10 with no site-packages (so no tomli), as for local releases."""
    python310 = shutil.which("python3.10")
    assert python310
    result = subprocess.run(
        [python310, "-I", "-S", str(_RELEASE_SCRIPT), command, "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_pypi_verify_parity_rejects_duplicate_wheel_members(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = _publish(tmp_path, monkeypatch, pypi_release)
    members = _wheel_members()
    with zipfile.ZipFile(dist / _WHEEL, "w") as wheel:
        # an earlier entry with the same name is shadowed by the later one
        wheel.writestr("inspect_ai/_util/config.yml", b"extra different entry")
        with pytest.warns(UserWarning, match="Duplicate name"):
            for name, content in members.items():
                wheel.writestr(name, content)
    _write_sdist(dist / _SDIST, _SDIST_MEMBERS)

    with pytest.raises(
        RuntimeError, match="duplicate member 'inspect_ai/_util/config.yml'"
    ):
        pypi_release.verify_parity(dist, "0.3.277")


def test_pypi_verify_parity_rejects_duplicate_sdist_members(
    pypi_release: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = _publish(tmp_path, monkeypatch, pypi_release)
    _write_wheel(dist / _WHEEL, _wheel_members())
    with tarfile.open(dist / _SDIST, "w:gz") as sdist:
        for name, content in [
            ("PKG-INFO", b"extra different entry"),
            *_SDIST_MEMBERS.items(),
        ]:
            info = tarfile.TarInfo(f"inspect_ai-0.3.277/{name}")
            info.size = len(content)
            sdist.addfile(info, io.BytesIO(content))

    with pytest.raises(RuntimeError, match="duplicate member 'PKG-INFO'"):
        pypi_release.verify_parity(dist, "0.3.277")
