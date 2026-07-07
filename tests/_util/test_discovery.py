"""Unit tests for :mod:`inspect_ai._util.discovery`."""

import json
import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from inspect_ai._util.discovery import (
    DISCOVERY_DIR_MODE,
    DISCOVERY_FILE_MODE,
    list_alive_discovery_entries,
    prepare_discovery_dir,
    write_discovery_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmpdir_path() -> Iterator[Path]:
    """Fresh temp directory per test, auto-cleaned at teardown."""
    with tempfile.TemporaryDirectory(prefix="discovery_test_") as d:
        yield Path(d)


def _alive_only_above_zero(pid: int) -> bool:
    """Treat any positive PID as alive.

    Useful when tests want to enumerate live entries without racing
    against process recycling.
    """
    return pid > 0


# ---------------------------------------------------------------------------
# prepare_discovery_dir
# ---------------------------------------------------------------------------


def test_prepare_discovery_dir_creates_missing(tmpdir_path: Path) -> None:
    """First call creates the directory."""
    target = tmpdir_path / "nested" / "control"
    assert not target.exists()
    prepare_discovery_dir(target)
    assert target.exists() and target.is_dir()


def test_prepare_discovery_dir_locks_perms_to_0700(tmpdir_path: Path) -> None:
    """Directory ends up at 0700 even if umask would have made it wider."""
    target = tmpdir_path / "ctl"
    prepare_discovery_dir(target)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == DISCOVERY_DIR_MODE == 0o700


def test_prepare_discovery_dir_relocks_existing_loose_perms(
    tmpdir_path: Path,
) -> None:
    """If the dir already exists at 0755, prepare_ tightens it to 0700.

    Defends against an older Inspect that bound without the chmod, or
    against an external tool that opened the directory wider.
    """
    target = tmpdir_path / "ctl"
    target.mkdir()
    target.chmod(0o755)
    prepare_discovery_dir(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_prepare_discovery_dir_is_idempotent(tmpdir_path: Path) -> None:
    """Calling twice doesn't error and leaves the dir at 0700."""
    target = tmpdir_path / "ctl"
    prepare_discovery_dir(target)
    prepare_discovery_dir(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_prepare_discovery_dir_returns_dir_path(tmpdir_path: Path) -> None:
    """Returns the same path it was given (for fluent chaining)."""
    target = tmpdir_path / "ctl"
    result = prepare_discovery_dir(target)
    assert result == target


# ---------------------------------------------------------------------------
# prepare_discovery_dir — integrated stale sweep
# ---------------------------------------------------------------------------


def test_prepare_sweeps_stale_entries(tmpdir_path: Path) -> None:
    """A discovery file with a dead PID is removed; orphan socket too."""
    # Stale entry: PID guaranteed-dead (use a huge sentinel that is
    # essentially never assigned).
    tmpdir_path.mkdir(parents=True, exist_ok=True)
    stale_sock = tmpdir_path / "stale.sock"
    stale_sock.touch()
    stale_discovery = tmpdir_path / "999999.json"
    stale_discovery.write_text(
        json.dumps(
            {
                "pid": 999999,
                "eval_id": "old",
                "socket_path": str(stale_sock),
                "started_at": 0,
            }
        )
    )
    # Live entry: our own PID; must NOT be removed.
    live_discovery = tmpdir_path / f"{os.getpid()}.json"
    live_discovery.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "eval_id": "live",
                "socket_path": None,
                "started_at": 0,
            }
        )
    )

    prepare_discovery_dir(tmpdir_path)

    assert not stale_discovery.exists()
    assert not stale_sock.exists()
    assert live_discovery.exists()


def test_prepare_tolerates_malformed_files(tmpdir_path: Path) -> None:
    """Bogus or unreadable discovery files are skipped silently."""
    (tmpdir_path / "garbage.json").write_text("{not valid json")
    (tmpdir_path / "missing-pid.json").write_text(json.dumps({"socket_path": "/foo"}))
    # Should not raise.
    prepare_discovery_dir(tmpdir_path)
    # Malformed files left alone (best-effort policy — we only delete
    # entries we can positively identify as stale).
    assert (tmpdir_path / "garbage.json").exists()
    assert (tmpdir_path / "missing-pid.json").exists()


def test_prepare_respects_custom_pid_alive_fn(tmpdir_path: Path) -> None:
    """A caller-supplied pid_alive_fn drives the sweep decision."""
    (tmpdir_path / "555.json").write_text(json.dumps({"pid": 555, "socket_path": None}))
    # Treat every PID as DEAD via the custom fn.
    prepare_discovery_dir(tmpdir_path, pid_alive_fn=lambda pid: False)
    assert not (tmpdir_path / "555.json").exists()


def test_prepare_picks_up_monkeypatched_process_pid_alive(
    tmpdir_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an explicit pid_alive_fn, the default resolves dynamically.

    A test that monkey-patches ``inspect_ai._util.process.pid_alive``
    affects the next call — verifies the late-binding behavior of
    ``_resolve_pid_alive``.
    """
    (tmpdir_path / "555.json").write_text(json.dumps({"pid": 555, "socket_path": None}))
    monkeypatch.setattr("inspect_ai._util.process.pid_alive", lambda pid: False)
    prepare_discovery_dir(tmpdir_path)
    assert not (tmpdir_path / "555.json").exists()


# ---------------------------------------------------------------------------
# write_discovery_file
# ---------------------------------------------------------------------------


def test_write_discovery_file_roundtrips_payload(tmpdir_path: Path) -> None:
    """Payload written under <pid>.json reads back identically as JSON."""
    payload = {
        "pid": 12345,
        "run_id": "abc",
        "socket_path": "/tmp/foo.sock",
        "started_at": 1.5,
    }
    path = write_discovery_file(tmpdir_path, 12345, payload)
    assert path == tmpdir_path / "12345.json"
    assert json.loads(path.read_text()) == payload


def test_write_discovery_file_locks_perms_to_0600(tmpdir_path: Path) -> None:
    """File is locked to owner-only at write time."""
    path = write_discovery_file(tmpdir_path, 42, {"pid": 42})
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == DISCOVERY_FILE_MODE == 0o600


def test_write_discovery_file_overwrites_existing(tmpdir_path: Path) -> None:
    """A second write to the same pid replaces the previous content."""
    write_discovery_file(tmpdir_path, 7, {"pid": 7, "v": 1})
    write_discovery_file(tmpdir_path, 7, {"pid": 7, "v": 2})
    assert json.loads((tmpdir_path / "7.json").read_text()) == {"pid": 7, "v": 2}


# ---------------------------------------------------------------------------
# list_alive_discovery_entries
# ---------------------------------------------------------------------------


def test_list_returns_empty_when_dir_missing(tmpdir_path: Path) -> None:
    """Non-existent directory yields the empty list, not an error."""
    target = tmpdir_path / "does_not_exist"
    assert list_alive_discovery_entries(target) == []


def test_list_returns_only_alive_entries(tmpdir_path: Path) -> None:
    """Entries whose PIDs aren't alive (per pid_alive_fn) are skipped."""
    write_discovery_file(tmpdir_path, 100, {"pid": 100, "label": "alive"})
    write_discovery_file(tmpdir_path, 200, {"pid": 200, "label": "dead"})
    entries = list_alive_discovery_entries(
        tmpdir_path,
        pid_alive_fn=lambda pid: pid == 100,
    )
    assert len(entries) == 1
    assert entries[0]["label"] == "alive"


def test_list_skips_malformed_json(tmpdir_path: Path) -> None:
    """Files that don't parse as JSON are ignored, not raised."""
    write_discovery_file(tmpdir_path, 100, {"pid": 100, "label": "good"})
    (tmpdir_path / "999.json").write_text("{not valid json")
    entries = list_alive_discovery_entries(
        tmpdir_path, pid_alive_fn=_alive_only_above_zero
    )
    assert len(entries) == 1
    assert entries[0]["label"] == "good"


def test_list_skips_non_dict_payload(tmpdir_path: Path) -> None:
    """Files whose top-level JSON isn't an object are ignored."""
    (tmpdir_path / "1.json").write_text(json.dumps([1, 2, 3]))
    (tmpdir_path / "2.json").write_text(json.dumps("scalar"))
    write_discovery_file(tmpdir_path, 100, {"pid": 100, "label": "good"})
    entries = list_alive_discovery_entries(
        tmpdir_path, pid_alive_fn=_alive_only_above_zero
    )
    assert len(entries) == 1
    assert entries[0]["label"] == "good"


def test_list_skips_missing_or_invalid_pid_field(tmpdir_path: Path) -> None:
    """Entries with a missing or non-integer pid field are skipped."""
    (tmpdir_path / "noproc.json").write_text(json.dumps({"label": "no-pid"}))
    (tmpdir_path / "nan.json").write_text(json.dumps({"pid": "abc"}))
    write_discovery_file(tmpdir_path, 100, {"pid": 100, "label": "good"})
    entries = list_alive_discovery_entries(
        tmpdir_path, pid_alive_fn=_alive_only_above_zero
    )
    assert len(entries) == 1
    assert entries[0]["label"] == "good"


def test_list_uses_default_pid_alive_when_no_fn_supplied(
    tmpdir_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default-arg lookup of ``_process.pid_alive`` is dynamic.

    Monkey-patching the canonical location affects subsequent calls
    (lets ACP / control discovery tests stub liveness without passing
    pid_alive_fn explicitly).
    """
    write_discovery_file(tmpdir_path, 100, {"pid": 100, "label": "x"})
    monkeypatch.setattr("inspect_ai._util.process.pid_alive", lambda pid: pid == 100)
    entries = list_alive_discovery_entries(tmpdir_path)
    assert len(entries) == 1
    assert entries[0]["label"] == "x"
