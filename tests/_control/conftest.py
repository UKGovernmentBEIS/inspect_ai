"""Shared fixtures and helpers for the control-channel test suite."""

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def _isolate_active_model() -> Iterator[None]:
    """Keep the active-model contextvar from leaking across tests.

    ``eval`` sets the process ``active_model`` contextvar. Tests in this
    suite run ``eval`` / ``eval_set`` *synchronously* in the test's own
    context (not a background thread), so without isolation that set
    persists after the call and leaks ``mockllm/model`` into later tests —
    e.g. one resolving a bare ``inspect`` model, which then resolves to the
    leaked active model instead of ``INSPECT_EVAL_MODEL``. Restore the
    contextvar after each test.
    """
    from inspect_ai.model._model import active_model_context_var

    token = active_model_context_var.set(active_model_context_var.get(None))
    try:
        yield
    finally:
        active_model_context_var.reset(token)


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
