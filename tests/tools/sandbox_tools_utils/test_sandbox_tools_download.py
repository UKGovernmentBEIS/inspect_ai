"""Tests for `inspect download sandbox-tools`."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from inspect_ai._cli import download as download_cli
from inspect_ai.tool._sandbox_tools_utils.sandbox import _get_executable_name

_NAMES = [
    _get_executable_name(arch, dev=False, musl=musl)
    for arch in ("amd64", "arm64")
    for musl in (False, True)
]


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    install_state: str,
    on_s3: set[str],
) -> list[str]:
    """Point the command at `tmp_path`; return the names it asks S3 for."""
    requested: list[str] = []

    async def fake_download_from_s3(filename: str) -> bool:
        requested.append(filename)
        if filename not in on_s3:
            return False
        (tmp_path / filename).write_bytes(b"binary")
        return True

    monkeypatch.setattr(download_cli, "_binaries_dir", lambda: tmp_path)
    monkeypatch.setattr(download_cli, "_download_from_s3", fake_download_from_s3)
    monkeypatch.setenv("INSPECT_SANDBOX_TOOLS_INSTALL_STATE", install_state)
    return requested


@pytest.mark.parametrize("install_state", ["pypi", "clean"])
def test_downloads_only_missing_binaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, install_state: str
) -> None:
    present = _NAMES[:2]
    for name in present:
        (tmp_path / name).write_bytes(b"binary")
    requested = _setup(monkeypatch, tmp_path, install_state, on_s3=set(_NAMES))

    result = CliRunner().invoke(download_cli.download_command, ["sandbox-tools"])

    assert result.exit_code == 0, result.output
    assert requested == _NAMES[2:]
    assert all((tmp_path / name).exists() for name in _NAMES)
    assert "already present" in result.output
    assert "downloaded" in result.output


def test_reports_binary_not_on_s3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = _NAMES[-1]
    requested = _setup(monkeypatch, tmp_path, "clean", on_s3=set(_NAMES[:-1]))

    result = CliRunner().invoke(download_cli.download_command, ["sandbox-tools"])

    assert result.exit_code == 1, result.output
    assert requested == _NAMES
    assert not (tmp_path / missing).exists()
    assert "Sandbox tools" in result.output
    assert "not on S3" in result.output
    assert f"Not on S3: {missing}" in result.output


def test_edited_install_does_not_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requested = _setup(monkeypatch, tmp_path, "edited", on_s3=set(_NAMES))

    result = CliRunner().invoke(download_cli.download_command, ["sandbox-tools"])

    assert result.exit_code == 0, result.output
    assert requested == []
    assert list(tmp_path.iterdir()) == []
    assert "on demand" in result.output
