"""CLI smoke tests for ``inspect acp`` (Phase 13).

These tests cover the click surface: argument parsing, mutually-
exclusive option validation, exit codes, stderr diagnostics. They use
``CliRunner.invoke`` so they're fast and don't require spawning a
subprocess. End-to-end bridge behavior (initialize round-trip, EOF
cascade, framing) is covered by ``tests/agent/test_acp/test_stdio_bridge.py``;
this file pins the *CLI* contract that editors interact with.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from inspect_ai._cli.acp import acp_command


@pytest.fixture(autouse=True)
def mock_stdio_streams(monkeypatch):
    """Replace ``acp.stdio.stdio_streams`` with a working in-memory pair.

    CliRunner wraps ``sys.stdin``/``sys.stdout`` in StringIO that lack
    a ``fileno()``, so the real ``stdio_streams`` (which calls
    ``loop.connect_read_pipe(sys.stdin)``) blows up with
    ``OSError: [Errno 9] fileno``. Stubbing it lets us exercise the
    bridge layer cleanly — the bridge's eventual connect call still
    fails (because the test specifies a bad socket) and we observe
    that failure instead of an unrelated stdio-setup error.
    """
    import asyncio as _aio

    async def _mock() -> tuple[_aio.StreamReader, _aio.StreamWriter]:
        loop = _aio.get_event_loop()
        reader = _aio.StreamReader(loop=loop)
        reader.feed_eof()  # bridge would exit cleanly even on success

        class _NoopProtocol(_aio.BaseProtocol):
            async def _drain_helper(self):
                return None

        class _NullTransport(_aio.WriteTransport):
            def write(self, data):
                pass

            def close(self):
                pass

            def is_closing(self):
                return False

            def can_write_eof(self):
                return False

            def get_extra_info(self, name, default=None):
                return default

        writer = _aio.StreamWriter(_NullTransport(), _NoopProtocol(), None, loop)
        return reader, writer

    monkeypatch.setattr("inspect_ai._cli.acp.stdio_streams", _mock)


@pytest.fixture
def short_data_dir(monkeypatch):
    """Stub ``inspect_data_dir`` to an empty per-test temp dir.

    Also stubs ``pid_alive`` to ``True`` so synthetic-PID discovery
    files in the temp dir register as live.
    """
    dirpath = Path(tempfile.mkdtemp(prefix="acp_cli_", dir="/tmp"))

    def _stub(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(
        "inspect_ai.agent._acp._discovery.inspect_data_dir",
        _stub,
    )
    monkeypatch.setattr(
        "inspect_ai.agent._acp._discovery.pid_alive",
        lambda pid: pid > 0,
    )
    try:
        yield dirpath
    finally:
        for p in sorted(dirpath.rglob("*"), reverse=True):
            try:
                if p.is_dir():
                    p.rmdir()
                else:
                    p.unlink()
            except OSError:
                pass
        try:
            dirpath.rmdir()
        except OSError:
            pass


def _write_discovery(
    short_data_dir: Path,
    *,
    pid: int,
    eval_id: str,
    socket_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
    started_at: float | None = None,
) -> None:
    acp = short_data_dir / "acp"
    acp.mkdir(parents=True, exist_ok=True)
    (acp / f"{pid}.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "eval_id": eval_id,
                "socket_path": socket_path,
                "host": host,
                "port": port,
                "started_at": started_at if started_at is not None else time.time(),
            }
        )
    )


# ---------------------------------------------------------------------------
# Bare command — Phase 15 placeholder
# ---------------------------------------------------------------------------


def test_bare_command_rejects_with_phase_15_hint(short_data_dir: Path) -> None:
    """``inspect acp`` (no flag) prints a helpful message + exits 2.

    Pinned so a future Phase 15 PR that lifts this error must do so
    intentionally (the test will fail and force the author to delete
    it as part of the TUI landing).
    """
    runner = CliRunner()
    result = runner.invoke(acp_command, [], standalone_mode=False)
    # ctx.exit(2) under standalone_mode=False returns the code as
    # result.return_value rather than raising SystemExit.
    assert result.return_value == 2
    # Click prints to stderr via ``click.echo(..., err=True)``.
    assert "Phase 15" in result.stderr
    assert "--stdio" in result.stderr


# ---------------------------------------------------------------------------
# Mutually-exclusive option handling
# ---------------------------------------------------------------------------


def test_eval_id_and_socket_are_mutually_exclusive(short_data_dir: Path) -> None:
    """Both flags together → exit 2 with a clear error message."""
    runner = CliRunner()
    result = runner.invoke(
        acp_command,
        ["--stdio", "--eval-id=X", "--socket=/tmp/Y.sock"],
        standalone_mode=False,
    )
    assert result.return_value == 2
    assert "mutually exclusive" in result.stderr


# ---------------------------------------------------------------------------
# Discovery resolution failures (bridge never connects)
# ---------------------------------------------------------------------------


def test_stdio_with_empty_discovery_dir_exits_2(short_data_dir: Path) -> None:
    """No evals running → exit 2 with actionable hint to ``--acp-server``."""
    runner = CliRunner()
    result = runner.invoke(acp_command, ["--stdio"], standalone_mode=False)
    # The CLI catches TargetResolutionError, prints to stderr,
    # sys.exit(2). The exception itself isn't surfaced as result.exit_code
    # under standalone_mode=False — check the captured SystemExit.
    assert isinstance(result.exception, SystemExit)
    assert result.exception.code == 2
    assert "no running evals" in result.stderr


def test_stdio_eval_id_nonexistent_exits_2(short_data_dir: Path) -> None:
    """``--eval-id`` for an unknown id → exit 2 with the id named."""
    _write_discovery(
        short_data_dir,
        pid=100001,
        eval_id="real",
        socket_path="/tmp/real.sock",
    )
    runner = CliRunner()
    result = runner.invoke(
        acp_command, ["--stdio", "--eval-id=ghost"], standalone_mode=False
    )
    assert isinstance(result.exception, SystemExit)
    assert result.exception.code == 2
    assert "ghost" in result.stderr


def test_stdio_bad_socket_path_exits_2(short_data_dir: Path) -> None:
    """``--socket=<nonexistent path>`` → bridge tries to connect, fails."""
    runner = CliRunner()
    result = runner.invoke(
        acp_command,
        ["--stdio", "--socket=/tmp/does/not/exist/inspect.sock"],
        standalone_mode=False,
    )
    assert isinstance(result.exception, SystemExit)
    assert result.exception.code == 2
    assert "/tmp/does/not/exist/inspect.sock" in result.stderr


def test_stdio_out_of_range_port_exits_2(short_data_dir: Path) -> None:
    """``--socket=host:99999`` exits cleanly instead of dumping a traceback.

    Without port-range validation, ``asyncio.open_connection`` raises
    ``OverflowError: connect(): port must be 0-65535`` which the
    CLI's ``(ConnectionRefusedError, FileNotFoundError)`` handler
    doesn't catch — the user sees a Python traceback instead of a
    clean stderr message + exit 2.
    """
    runner = CliRunner()
    result = runner.invoke(
        acp_command,
        ["--stdio", "--socket=127.0.0.1:99999"],
        standalone_mode=False,
    )
    assert isinstance(result.exception, SystemExit)
    assert result.exception.code == 2
    # Diagnostic mentions the offending value and the valid range.
    assert "127.0.0.1:99999" in result.stderr
    assert "0-65535" in result.stderr


# ---------------------------------------------------------------------------
# Multi-eval picker policy
# ---------------------------------------------------------------------------


def test_stdio_multi_eval_picks_newest_and_logs_to_stderr(
    short_data_dir: Path,
) -> None:
    """Multiple evals, no ``--eval-id`` → newest wins; stderr names the pick.

    Pinned so a future regression can't silently force ``--eval-id``
    to become mandatory in the multi-eval case (the design choice was
    "pick the most-recently-started one" so editor configs Just Work
    when the user spawns a second eval mid-session).
    """
    _write_discovery(
        short_data_dir,
        pid=100001,
        eval_id="older",
        socket_path="/tmp/acp_older.sock",
        started_at=1000.0,
    )
    _write_discovery(
        short_data_dir,
        pid=100002,
        eval_id="newer",
        socket_path="/tmp/acp_newer.sock",
        started_at=2000.0,
    )
    runner = CliRunner()
    result = runner.invoke(acp_command, ["--stdio"], standalone_mode=False)
    # Bridge picks "newer" then fails to connect (socket doesn't exist).
    # Either FileNotFoundError or ConnectionRefusedError; both become
    # exit 2 with a "not reachable" message.
    assert isinstance(result.exception, SystemExit)
    assert result.exception.code == 2
    # Pick-notice landed BEFORE the connect failure.
    assert "most recent of 2" in result.stderr
    assert "newer" in result.stderr
    assert "older" in result.stderr


def test_stdio_single_eval_no_pick_notice(short_data_dir: Path) -> None:
    """One eval running, no ``--eval-id`` → no pick-notice on stderr.

    Pins the contract that the pick-notice is only emitted when
    discovery had to disambiguate; the unambiguous happy path stays
    quiet.
    """
    _write_discovery(
        short_data_dir,
        pid=os.getpid(),
        eval_id="only",
        socket_path="/tmp/acp_only.sock",
    )
    runner = CliRunner()
    result = runner.invoke(acp_command, ["--stdio"], standalone_mode=False)
    # Connection fails (socket doesn't exist), but the stderr should
    # contain ONLY the connect failure, not a pick-notice.
    assert isinstance(result.exception, SystemExit)
    assert result.exception.code == 2
    assert "most recent of" not in result.stderr


# ---------------------------------------------------------------------------
# --help content
# ---------------------------------------------------------------------------


def test_help_lists_all_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(acp_command, ["--help"], standalone_mode=False)
    assert result.exit_code == 0
    assert "--stdio" in result.output
    assert "--eval-id" in result.output
    assert "--socket" in result.output
