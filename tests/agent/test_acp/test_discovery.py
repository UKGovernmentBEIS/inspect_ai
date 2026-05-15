"""Tests for ``resolve_target()`` + the discovery enumeration helpers.

Covers the resolution policy used by the Phase 13 ``inspect acp
--stdio`` bridge:

- ``--socket`` (explicit override) — parses the value, returns a
  target without touching the discovery dir.
- ``--eval-id`` — looks up the matching discovery file or errors.
- Otherwise — auto-discovery: pick the most-recently-started live
  eval; error only when zero are alive.

Also pins the no-flags happy path so a future regression can't
silently force ``--eval-id`` to become mandatory.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from inspect_ai.agent._acp._discovery import (
    DiscoveredEval,
    TargetAddress,
    TargetResolutionError,
    list_discovered_evals,
    resolve_target,
)


@pytest.fixture
def short_data_dir(monkeypatch):
    """Stub ``inspect_data_dir`` to a temp dir + treat all PIDs as alive.

    Also stubs ``pid_alive`` to ``True`` so tests can use synthetic
    PIDs (so multiple "running" evals don't collide on the same
    ``{pid}.json`` file name). Tests that specifically need the
    stale-PID filtering path override the patch with a per-test lambda.
    """
    dirpath = Path(tempfile.mkdtemp(prefix="acp_disc_", dir="/tmp"))

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
) -> Path:
    """Write one discovery JSON file shaped like ``_AcpServer.start`` does."""
    acp = short_data_dir / "acp"
    acp.mkdir(parents=True, exist_ok=True)
    path = acp / f"{pid}.json"
    path.write_text(
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
    return path


# ---------------------------------------------------------------------------
# --socket override (no discovery touched)
# ---------------------------------------------------------------------------


def test_socket_unix_path_returns_unix_target(short_data_dir: Path) -> None:
    target, picked = resolve_target(eval_id=None, socket="/tmp/foo.sock")
    assert picked is None
    assert target == TargetAddress(socket_path=Path("/tmp/foo.sock"))


def test_socket_loopback_host_port_returns_tcp_target(short_data_dir: Path) -> None:
    target, picked = resolve_target(eval_id=None, socket="127.0.0.1:4444")
    assert picked is None
    assert target == TargetAddress(host="127.0.0.1", port=4444)


def test_socket_non_loopback_host_port_returns_tcp_target(
    short_data_dir: Path,
) -> None:
    target, picked = resolve_target(eval_id=None, socket="0.0.0.0:5555")
    assert picked is None
    assert target == TargetAddress(host="0.0.0.0", port=5555)


def test_socket_ipv6_bracket_form_returns_tcp_target(short_data_dir: Path) -> None:
    target, picked = resolve_target(eval_id=None, socket="[::1]:6666")
    assert picked is None
    assert target == TargetAddress(host="::1", port=6666)


@pytest.mark.parametrize(
    "bad_socket",
    [
        "127.0.0.1:99999",  # out-of-range high
        "127.0.0.1:65536",  # one past the max
        "127.0.0.1:-1",  # negative
        "[::1]:99999",  # IPv6 form, out-of-range
    ],
)
def test_socket_out_of_range_port_raises(short_data_dir: Path, bad_socket: str) -> None:
    """Syntactically-valid host:port with a port outside 0-65535 → clean error.

    Without this check, ``asyncio.open_connection`` raises
    ``OverflowError: connect(): port must be 0-65535`` mid-bridge,
    which the CLI's catch (``ConnectionRefusedError`` /
    ``FileNotFoundError``) doesn't handle — the user sees a
    traceback instead of "exit 2 + stderr diagnostic." Validate at
    parse time so the error surfaces before any I/O is attempted.
    """
    with pytest.raises(TargetResolutionError) as exc:
        resolve_target(eval_id=None, socket=bad_socket)
    assert "port" in str(exc.value).lower()
    assert "0-65535" in str(exc.value)


def test_socket_port_at_max_boundary_is_accepted(short_data_dir: Path) -> None:
    """Port 65535 is the highest valid TCP port; must not be rejected."""
    target, _ = resolve_target(eval_id=None, socket="127.0.0.1:65535")
    assert target == TargetAddress(host="127.0.0.1", port=65535)


def test_socket_port_zero_is_accepted(short_data_dir: Path) -> None:
    """Port 0 = "OS picks one"; legitimate for some test setups."""
    target, _ = resolve_target(eval_id=None, socket="127.0.0.1:0")
    assert target == TargetAddress(host="127.0.0.1", port=0)


def test_socket_override_does_not_touch_discovery(short_data_dir: Path) -> None:
    """--socket short-circuits before discovery dir is scanned.

    Pinned so a future refactor can't accidentally route the
    explicit-override path through ``list_discovered_evals`` (which
    would defeat the "bypass discovery" semantic).
    """
    # No discovery files exist — bare auto-discovery would raise. The
    # override should succeed.
    target, _ = resolve_target(eval_id=None, socket="/tmp/explicit.sock")
    assert target.socket_path == Path("/tmp/explicit.sock")


# ---------------------------------------------------------------------------
# --eval-id lookup
# ---------------------------------------------------------------------------


def test_eval_id_no_match_raises(short_data_dir: Path) -> None:
    """Specific id requested but no live eval has it → error."""
    _write_discovery(short_data_dir, pid=os.getpid(), eval_id="real")
    with pytest.raises(TargetResolutionError) as exc:
        resolve_target(eval_id="nonexistent", socket=None)
    assert "nonexistent" in str(exc.value)


def test_eval_id_match_unix_target(short_data_dir: Path) -> None:
    _write_discovery(
        short_data_dir,
        pid=os.getpid(),
        eval_id="abc",
        socket_path="/tmp/abc.sock",
    )
    target, picked = resolve_target(eval_id="abc", socket=None)
    assert picked is None
    assert target == TargetAddress(socket_path=Path("/tmp/abc.sock"), eval_id="abc")


def test_eval_id_match_tcp_target(short_data_dir: Path) -> None:
    _write_discovery(
        short_data_dir,
        pid=os.getpid(),
        eval_id="def",
        host="127.0.0.1",
        port=9999,
    )
    target, picked = resolve_target(eval_id="def", socket=None)
    assert picked is None
    assert target == TargetAddress(host="127.0.0.1", port=9999, eval_id="def")


# ---------------------------------------------------------------------------
# Auto-discovery (no flags supplied)
# ---------------------------------------------------------------------------


def test_auto_zero_alive_raises(short_data_dir: Path) -> None:
    """No discovery files → actionable error message."""
    with pytest.raises(TargetResolutionError) as exc:
        resolve_target(eval_id=None, socket=None)
    msg = str(exc.value)
    assert "no running evals" in msg
    assert "--acp-server" in msg  # suggests the next step


def test_auto_one_alive_is_the_happy_path_no_flags_required(
    short_data_dir: Path,
) -> None:
    """The common case: exactly one eval, no flags needed.

    Pinned so a future regression can't silently make ``--eval-id``
    required when the user has just one eval running.
    """
    _write_discovery(
        short_data_dir,
        pid=os.getpid(),
        eval_id="only",
        socket_path="/tmp/only.sock",
    )
    target, picked = resolve_target(eval_id=None, socket=None)
    assert picked is None
    assert target.eval_id == "only"
    assert target.socket_path == Path("/tmp/only.sock")


def test_auto_many_alive_picks_newest_and_reports_candidates(
    short_data_dir: Path,
) -> None:
    """Multiple evals → most-recently-started wins; picked_from has the full list."""
    older_path = _write_discovery(
        short_data_dir,
        pid=100001,
        eval_id="older",
        socket_path="/tmp/older.sock",
        started_at=1000.0,
    )
    newer_path = _write_discovery(
        short_data_dir,
        pid=100002,
        eval_id="newer",
        socket_path="/tmp/newer.sock",
        started_at=2000.0,
    )
    # Make sure both files actually exist (sanity).
    assert older_path.exists() and newer_path.exists()

    target, picked = resolve_target(eval_id=None, socket=None)
    assert target.eval_id == "newer"  # newest wins
    assert picked is not None and len(picked) == 2
    assert [e.eval_id for e in picked] == ["newer", "older"]  # sorted newest-first


def test_auto_stale_pid_filtered_so_resolution_succeeds(
    short_data_dir: Path,
    monkeypatch,
) -> None:
    """A dead-PID discovery file should be ignored; the alive one wins."""
    # Override the fixture's "everything alive" patch with one that
    # treats PID 999999 as dead and everything else as alive.
    monkeypatch.setattr(
        "inspect_ai.agent._acp._discovery.pid_alive",
        lambda pid: pid > 0 and pid != 999999,
    )
    _write_discovery(
        short_data_dir,
        pid=999999,
        eval_id="dead",
        socket_path="/tmp/dead.sock",
    )
    _write_discovery(
        short_data_dir,
        pid=os.getpid(),
        eval_id="alive",
        socket_path="/tmp/alive.sock",
    )
    target, picked = resolve_target(eval_id=None, socket=None)
    assert target.eval_id == "alive"
    # picked_from is None because there was only ONE alive candidate
    # after filtering (the dead one was silently dropped).
    assert picked is None


def test_auto_malformed_discovery_file_is_skipped(short_data_dir: Path) -> None:
    """A garbage JSON file in the discovery dir doesn't break resolution."""
    acp = short_data_dir / "acp"
    acp.mkdir(parents=True, exist_ok=True)
    (acp / "garbage.json").write_text("not valid json {{{")
    _write_discovery(
        short_data_dir,
        pid=os.getpid(),
        eval_id="valid",
        socket_path="/tmp/valid.sock",
    )
    target, _ = resolve_target(eval_id=None, socket=None)
    assert target.eval_id == "valid"


# ---------------------------------------------------------------------------
# list_discovered_evals (used by Phase 15's unified picker)
# ---------------------------------------------------------------------------


def test_list_discovered_evals_returns_newest_first(short_data_dir: Path) -> None:
    _write_discovery(
        short_data_dir,
        pid=100001,
        eval_id="a",
        started_at=1.0,
        socket_path="/tmp/a.sock",
    )
    _write_discovery(
        short_data_dir,
        pid=100002,
        eval_id="b",
        started_at=3.0,
        socket_path="/tmp/b.sock",
    )
    _write_discovery(
        short_data_dir,
        pid=100003,
        eval_id="c",
        started_at=2.0,
        socket_path="/tmp/c.sock",
    )
    evals = list_discovered_evals()
    assert [e.eval_id for e in evals] == ["b", "c", "a"]
    assert all(isinstance(e, DiscoveredEval) for e in evals)


def test_list_discovered_evals_empty_when_no_dir(short_data_dir: Path) -> None:
    """No acp/ subdir → empty list, no error."""
    # Don't write any discovery files; the acp/ dir may not exist.
    assert list_discovered_evals() == []
