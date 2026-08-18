"""Shared fixtures and helpers for the control-channel test suite."""

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def _isolate_terminal_source_caches() -> Iterator[None]:
    """Keep the terminal-source caches from leaking across tests.

    The events / messages readers cache resolved terminal sources for a few
    seconds (see ``inspect_ai._control.terminal_cache``). Tests in this suite
    reuse eval/sample ids (``e1`` / ``s1``) across monkeypatched sources, so
    without clearing, one test's cached source (which outlives its
    monkeypatches) would be served to the next.
    """
    from inspect_ai._control.terminal_cache import clear_terminal_source_caches

    clear_terminal_source_caches()
    try:
        yield
    finally:
        clear_terminal_source_caches()


@pytest.fixture
def short_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Short data dir under /tmp so AF_UNIX paths fit in 104 chars.

    macOS pytest tmp_path lives under ``/private/var/folders/...`` which
    blows past the AF_UNIX limit, and the control server binds a socket
    under the data dir during a run. Patches both control and ACP discovery
    modules so neither subsystem writes outside the test's sandbox.
    """
    dirpath = Path(tempfile.mkdtemp(prefix="ctl_", dir="/tmp"))

    def _stub(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("inspect_ai._control.discovery.inspect_data_dir", _stub)
    monkeypatch.setattr("inspect_ai.agent._acp.discovery.inspect_data_dir", _stub)
    try:
        yield dirpath
    finally:
        shutil.rmtree(dirpath, ignore_errors=True)


def cli_runner() -> CliRunner:
    """A CliRunner that captures stderr separately across click versions.

    click < 8.2 mixes stderr into stdout unless ``mix_stderr=False``; click
    >= 8.2 removed the parameter and always captures stderr separately
    (though its ``Result.output`` interleaves both streams — assert on
    ``Result.stdout`` for stdout contents, e.g. that every line parses as
    JSON, where log/warning lines would break those assertions).
    """
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()
