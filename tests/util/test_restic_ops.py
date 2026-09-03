"""Tests for host-side restic ops that need no restic binary.

- ``_parse_listed_files`` parses ``restic ls`` (full snapshot tree) — used
  for the first snapshot, which has no parent.
- ``_parse_changed_files`` parses ``restic diff`` (added/changed entries
  vs the parent) — used for every later snapshot.
  Both keep files only, cap the list, and count the overflow.
- ``run_backup`` / ``restore_repo`` invocation shape (restic mocked).
- ``verify_regular_tree``: the restored-tree gate (restored repos are
  untrusted input).

Tests that drive a real restic binary live in
``tests/checkpoint/test_restore_repo.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from test_helpers.restic import SUMMARY_SNAPSHOT_ID, restic_summary_json

from inspect_ai.util._restic.ops import (
    _parse_changed_files,
    _parse_listed_files,
    _previous_id,
    restore_repo,
    run_backup,
)
from inspect_ai.util._restic.verify import (
    RestoredTreeError,
    TreeStats,
    verify_regular_tree,
)

# --- restic ls (full snapshot) -------------------------------------------

_SNAPSHOT_LINE = json.dumps(
    {
        "time": "2026-05-29T14:13:05Z",
        "paths": ["/root"],
        "id": "7349edf3",
        "short_id": "7349edf3",
        "struct_type": "snapshot",
    }
)


def _node(path: str, type: str) -> str:
    return json.dumps({"name": path.rsplit("/", 1)[-1], "type": type, "path": path})


def _ls_output(*lines: str) -> str:
    return "\n".join((_SNAPSHOT_LINE, *lines))


def test_listed_files_only_dirs_and_snapshot_dropped() -> None:
    stdout = _ls_output(
        _node("/root", "dir"),
        _node("/root/a.txt", "file"),
        _node("/root/sub", "dir"),
        _node("/root/sub/b.txt", "file"),
    )
    files, additional = _parse_listed_files(stdout, limit=100)
    assert files == ["/root/a.txt", "/root/sub/b.txt"]
    assert additional == 0


def test_listed_cap_and_overflow() -> None:
    stdout = _ls_output(*[_node(f"/root/f{i}.txt", "file") for i in range(5)])
    files, additional = _parse_listed_files(stdout, limit=2)
    assert files == ["/root/f0.txt", "/root/f1.txt"]
    assert additional == 3


def test_listed_no_files() -> None:
    assert _parse_listed_files(_ls_output(_node("/root", "dir")), limit=100) == ([], 0)


# --- restic diff (added/changed vs parent) -------------------------------

_DIFF_STATS = json.dumps(
    {"message_type": "statistics", "changed_files": 2, "added": {"files": 1}}
)


def _change(path: str, modifier: str) -> str:
    return json.dumps({"message_type": "change", "path": path, "modifier": modifier})


def _diff_output(*lines: str) -> str:
    return "\n".join((*lines, _DIFF_STATS))


def test_changed_keeps_added_and_modified_files() -> None:
    stdout = _diff_output(
        _change("/root/new.txt", "+"),
        _change("/root/edited.txt", "M"),
        _change("/root/retyped", "T"),
    )
    files, additional = _parse_changed_files(stdout, limit=100)
    assert files == ["/root/new.txt", "/root/edited.txt", "/root/retyped"]
    assert additional == 0


def test_changed_drops_removed_metadata_and_dirs() -> None:
    stdout = _diff_output(
        _change("/root/gone.txt", "-"),  # removed
        _change("/root/perms.txt", "U"),  # metadata only
        _change("/root/newdir/", "+"),  # directory
        _change("/root/keep.txt", "+"),  # the only one kept
    )
    files, additional = _parse_changed_files(stdout, limit=100)
    assert files == ["/root/keep.txt"]
    assert additional == 0


def test_changed_cap_and_overflow() -> None:
    stdout = _diff_output(*[_change(f"/root/f{i}.txt", "+") for i in range(5)])
    files, additional = _parse_changed_files(stdout, limit=2)
    assert files == ["/root/f0.txt", "/root/f1.txt"]
    assert additional == 3


def test_changed_none() -> None:
    assert _parse_changed_files(_diff_output(), limit=100) == ([], 0)


# --- _previous_id (diff base = chronologically prior snapshot) ------------

_SNAPS = [
    {"id": "cccc", "time": "2026-05-29T03:00:00Z"},
    {"id": "aaaa", "time": "2026-05-29T01:00:00Z"},
    {"id": "bbbb", "time": "2026-05-29T02:00:00Z"},
]


def test_previous_id_returns_prior_by_time() -> None:
    # unsorted input; bbbb (02:00) precedes cccc (03:00)
    assert _previous_id(_SNAPS, "cccc") == "bbbb"


def test_previous_id_none_for_earliest() -> None:
    assert _previous_id(_SNAPS, "aaaa") is None


def test_previous_id_matches_short_prefix() -> None:
    assert _previous_id(_SNAPS, "cc") == "bbbb"


def test_previous_id_absent_snapshot() -> None:
    assert _previous_id(_SNAPS, "zzzz") is None


# --- run_backup invocation (host-side) -----------------------------------


async def test_run_backup_passes_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host ``restic backup`` runs with ``--quiet``.

    Without it restic emits one JSON ``status`` line per progress tick
    (~60/s), every one of which ``from_stdout`` discards — but
    ``anyio.run_process`` first buffers the whole stream in memory,
    unbounded in backup duration. ``--quiet`` drops the status stream
    while the trailing ``summary`` line (the only line we read) survives.
    """
    captured: dict[str, list[str]] = {}

    async def fake_run_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        return SimpleNamespace(stdout=restic_summary_json().encode())

    monkeypatch.setattr(anyio, "run_process", fake_run_process)

    summary = await run_backup(Path("/usr/bin/restic"), "/repo", "pw", "/src", "tag")

    assert "--quiet" in captured["command"]
    assert summary.snapshot_id == SUMMARY_SNAPSHOT_ID  # quiet summary still parses


async def test_run_backup_absolutizes_relative_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A relative source reaches restic absolute.

    That keeps the snapshot's tree root equal to the absolute path restic
    records in ``paths``, which ``restore_repo`` restores by.
    """
    captured: dict[str, list[str]] = {}

    async def fake_run_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        return SimpleNamespace(stdout=restic_summary_json().encode())

    monkeypatch.setattr(anyio, "run_process", fake_run_process)
    monkeypatch.chdir(tmp_path)

    await run_backup(Path("/usr/bin/restic"), "/repo", "pw", "ckpts/context", "tag")

    source = captured["command"][4]
    assert os.path.isabs(source)
    assert source == os.path.abspath("ckpts/context")


# --- restore_repo invocation (restic mocked) ------------------------------

_SNAPSHOT_PATH = "/host/sample/context"
_SNAPSHOT_ID = "abc123" + "0" * 58
_ONE_SNAPSHOT: list[dict[str, object]] = [
    {"id": _SNAPSHOT_ID, "paths": [_SNAPSHOT_PATH]}
]


def _ls_node(path: str, type: str, size: int | None = 0) -> dict[str, object]:
    """One ``restic ls --json`` node; ``size=None`` omits the key (malformed file).

    Emits both record-kind keys as restic 0.17+ does (``struct_type`` is
    the deprecated pre-0.17 name).
    """
    node: dict[str, object] = {
        "name": path.rsplit("/", 1)[-1],
        "type": type,
        "path": path,
        "message_type": "node",
        "struct_type": "node",
    }
    if type == "file" and size is not None:
        node["size"] = size
    return node


def _ls_header(source_path: str = _SNAPSHOT_PATH) -> dict[str, object]:
    """The leading snapshot record of ``restic ls --json``."""
    return {
        "paths": [source_path],
        "message_type": "snapshot",
        "struct_type": "snapshot",
    }


def _ls_chain(*leaves: dict[str, object]) -> list[dict[str, object]]:
    """``restic ls --json`` records for the ``/host/sample/context`` chain + leaves."""
    return [
        _ls_header(),
        _ls_node("/host", "dir"),
        _ls_node("/host/sample", "dir"),
        _ls_node(_SNAPSHOT_PATH, "dir"),
        *leaves,
    ]


_STORE_ONLY = _ls_chain(_ls_node(f"{_SNAPSHOT_PATH}/store.json", "file", size=2))


def _fake_restic(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: list[dict[str, object]],
    listing: list[dict[str, object]],
    restore: Callable[[Path], None],
) -> list[list[str]]:
    """Stub ``anyio.run_process`` for ``snapshots``/``ls``/``restore``; return the calls."""
    calls: list[list[str]] = []

    async def fake_run_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        if "snapshots" in command:
            return SimpleNamespace(stdout=json.dumps(snapshots).encode())
        if "ls" in command:
            lines = "\n".join(json.dumps(record) for record in listing)
            return SimpleNamespace(stdout=lines.encode())
        if "restore" in command:
            restore(Path(command[command.index("--target") + 1]))
            return SimpleNamespace(stdout=b"")
        raise AssertionError(f"unexpected restic command: {command}")

    monkeypatch.setattr(anyio, "run_process", fake_run_process)
    return calls


def _write_store(target: Path) -> None:
    (target / "store.json").write_text("{}")


async def _restore(target: Path) -> None:
    await restore_repo(
        Path("/r"), "/repo", "pw", str(target), max_files=8, max_bytes=1024
    )


async def test_restore_repo_restores_known_subfolder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Restore names the snapshot's recorded path; files land directly in target."""
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, _STORE_ONLY, _write_store)
    target = tmp_path / "ctx"

    await _restore(target)

    assert [c[3] for c in calls] == ["snapshots", "ls", "restore"]
    assert calls[0][3:] == ["snapshots", "--json", "latest"]
    assert calls[1][3:] == ["ls", "--json", _SNAPSHOT_ID]
    assert calls[2][3:] == [
        "restore",
        f"{_SNAPSHOT_ID}:{_SNAPSHOT_PATH}",
        "--target",
        str(target.resolve()),
    ]
    assert [p.name for p in target.iterdir()] == ["store.json"]


async def test_restore_repo_rejects_empty_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``snapshots latest`` on an empty repo yields ``[]`` (exit 0) — not a restore."""
    calls = _fake_restic(monkeypatch, [], _STORE_ONLY, _write_store)

    with pytest.raises(RuntimeError, match="expected one latest snapshot"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots"]


async def test_restore_repo_rejects_multi_path_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A snapshot recording more than one source path never reaches restore."""
    calls = _fake_restic(
        monkeypatch,
        [{"id": _SNAPSHOT_ID, "paths": [_SNAPSHOT_PATH, "/other"]}],
        _STORE_ONLY,
        _write_store,
    )

    with pytest.raises(RuntimeError, match="exactly one source path"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots"]


@pytest.mark.parametrize("kind", ["symlink", "fifo", "socket", "chardev"])
async def test_restore_repo_rejects_non_regular_node_before_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    """A non-regular node in the listing fails before restic writes anything."""
    listing = _ls_chain(
        _ls_node(f"{_SNAPSHOT_PATH}/store.json", kind),
        _ls_node(f"{_SNAPSHOT_PATH}/events.json", "file", size=2),
    )
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, listing, _write_store)
    target = tmp_path / "ctx"

    with pytest.raises(RestoredTreeError, match=rf"{kind} node.*store\.json"):
        await _restore(target)
    assert [c[3] for c in calls] == ["snapshots", "ls"]
    assert list(target.iterdir()) == []


async def test_restore_repo_rejects_source_path_missing_from_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The recorded source path must be a listed directory, or nothing is restored."""
    listing: list[dict[str, object]] = [
        _ls_header(),
        _ls_node("/elsewhere", "dir"),
        _ls_node("/elsewhere/store.json", "file", size=2),
    ]
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, listing, _write_store)

    with pytest.raises(RuntimeError, match="not a directory in the snapshot"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots", "ls"]


async def test_restore_repo_rejects_source_path_listed_as_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    listing: list[dict[str, object]] = [
        _ls_header(),
        _ls_node("/host", "dir"),
        _ls_node("/host/sample", "dir"),
        _ls_node(_SNAPSHOT_PATH, "file", size=2),
    ]
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, listing, _write_store)

    with pytest.raises(RuntimeError, match="not a directory in the snapshot"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots", "ls"]


async def test_restore_repo_restores_legacy_relative_rooted_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A snapshot backed up from a *relative* source restores by its tree path.

    Older versions passed a relative ``checkpoints_location`` through to
    ``restic backup`` verbatim; restic recorded the absolute path in
    ``paths`` but rooted the tree at the relative components. The
    subfolder is the longest suffix of the recorded path listed as a dir.
    """
    recorded = "/tmp/run/ckpts/1__1/context"
    listing: list[dict[str, object]] = [
        _ls_header(recorded),
        _ls_node("/ckpts", "dir"),
        _ls_node("/ckpts/1__1", "dir"),
        _ls_node("/ckpts/1__1/context", "dir"),
        _ls_node("/ckpts/1__1/context/store.json", "file", size=2),
    ]
    snapshots: list[dict[str, object]] = [{"id": _SNAPSHOT_ID, "paths": [recorded]}]
    calls = _fake_restic(monkeypatch, snapshots, listing, _write_store)
    target = tmp_path / "ctx"

    await _restore(target)

    assert calls[2][4] == f"{_SNAPSHOT_ID}:/ckpts/1__1/context"
    assert [p.name for p in target.iterdir()] == ["store.json"]


def test_snapshot_subfolder_prefers_longest_listed_suffix() -> None:
    """An ancestor sharing the source's name is not mistaken for the source.

    ``checkpoints_location="context"`` (relative) yields a tree whose top
    dir and source dir are both named ``context``; only the longer match
    is the source.
    """
    from inspect_ai.util._restic.ops import _snapshot_subfolder

    recorded = "/w/context/e.checkpoints/1__1/context"
    dirs = {
        "/context",
        "/context/e.checkpoints",
        "/context/e.checkpoints/1__1",
        "/context/e.checkpoints/1__1/context",
    }
    assert _snapshot_subfolder(recorded, dirs) == "/context/e.checkpoints/1__1/context"
    assert _snapshot_subfolder(recorded, {recorded, "/context"}) == recorded
    with pytest.raises(RuntimeError, match="not a directory in the snapshot"):
        _snapshot_subfolder(recorded, {"/w", "/w/context"})


async def test_restore_repo_reads_pre_0_17_struct_type_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A listing keyed only on the deprecated ``struct_type`` still parses."""
    listing = [
        {k: v for k, v in record.items() if k != "message_type"}
        for record in _STORE_ONLY
    ]
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, listing, _write_store)

    await _restore(tmp_path / "ctx")

    assert [c[3] for c in calls] == ["snapshots", "ls", "restore"]


async def test_restore_repo_rejects_file_node_without_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A malformed listing is rejected, not coerced to size 0."""
    listing = _ls_chain(_ls_node(f"{_SNAPSHOT_PATH}/store.json", "file", size=None))
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, listing, _write_store)

    with pytest.raises(RestoredTreeError, match=r"without a size.*store\.json"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots", "ls"]


async def test_restore_repo_enforces_listing_bounds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Entry and byte bounds apply to the listing, before restore."""
    big = _ls_chain(_ls_node(f"{_SNAPSHOT_PATH}/events.json", "file", size=4096))
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, big, _write_store)
    with pytest.raises(RestoredTreeError, match="exceeds 1024 bytes"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots", "ls"]

    many = _ls_chain(
        *(_ls_node(f"{_SNAPSHOT_PATH}/f{i}.json", "file", size=1) for i in range(8))
    )
    calls = _fake_restic(monkeypatch, _ONE_SNAPSHOT, many, _write_store)
    with pytest.raises(RestoredTreeError, match="exceeds 8 entries"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots", "ls"]


async def test_restore_repo_stops_parsing_listing_past_entry_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Listing lines beyond the entry bound are never decoded.

    The lines after the bound are not valid UTF-8, let alone JSON, so
    decoding the whole buffer up front would raise ``UnicodeDecodeError``
    and parsing them ``JSONDecodeError`` rather than the bound error; an
    untrusted listing with millions of nodes must not be processed in full
    on the event loop.
    """
    over_bound = _ls_chain(
        *(_ls_node(f"{_SNAPSHOT_PATH}/f{i}.json", "file", size=1) for i in range(6))
    )
    listing = "\n".join(json.dumps(record) for record in over_bound).encode()
    listing += b"\n" + b"\xff not utf-8\n" * 1000
    calls: list[list[str]] = []

    async def fake_run_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        if "snapshots" in command:
            return SimpleNamespace(stdout=json.dumps(_ONE_SNAPSHOT).encode())
        if "ls" in command:
            return SimpleNamespace(stdout=listing)
        raise AssertionError(f"unexpected restic command: {command}")

    monkeypatch.setattr(anyio, "run_process", fake_run_process)

    with pytest.raises(RestoredTreeError, match="exceeds 8 entries"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["snapshots", "ls"]


async def test_restore_repo_rejects_symlink_in_restored_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Belt-and-braces: a symlink that slipped past the listing fails and is removed."""
    secret = tmp_path / "secret.json"
    secret.write_text('{"pwned": true}')

    def restore_symlink(target: Path) -> None:
        os.symlink(secret, target / "store.json")

    _fake_restic(monkeypatch, _ONE_SNAPSHOT, _STORE_ONLY, restore_symlink)
    target = tmp_path / "ctx"

    with pytest.raises(RestoredTreeError, match="symlink"):
        await _restore(target)
    # The rejected tree is not left behind; the caller's dir is, emptied.
    assert target.is_dir() and not any(target.iterdir())
    assert secret.read_text() == '{"pwned": true}'  # cleanup did not follow the link


async def test_restore_repo_cleans_target_when_restic_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A partial restore (restic exits non-zero) is removed, not left unverified."""

    def restore_then_fail(target: Path) -> None:
        _write_store(target)
        (target / "nested").mkdir()
        (target / "nested" / "leftover.json").write_text("{}")
        raise subprocess.CalledProcessError(1, ["restic", "restore"])

    _fake_restic(monkeypatch, _ONE_SNAPSHOT, _STORE_ONLY, restore_then_fail)
    target = tmp_path / "ctx"

    with pytest.raises(subprocess.CalledProcessError):
        await _restore(target)
    assert target.is_dir() and not any(target.iterdir())


async def test_restore_repo_cleans_target_when_cancelled_mid_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cancellation while restic is still writing leaves no unverified tree behind."""
    target = tmp_path / "ctx"

    async def fake_run_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        if "snapshots" in command:
            return SimpleNamespace(stdout=json.dumps(_ONE_SNAPSHOT).encode())
        if "ls" in command:
            lines = "\n".join(json.dumps(record) for record in _STORE_ONLY)
            return SimpleNamespace(stdout=lines.encode())
        _write_store(target)
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    monkeypatch.setattr(anyio, "run_process", fake_run_process)

    with anyio.move_on_after(0.2) as scope:
        await _restore(target)
    assert scope.cancelled_caught
    assert target.is_dir() and not any(target.iterdir())


def test_tree_path_maps_windows_drive_to_root_component() -> None:
    r"""``C:\a\b`` is stored by restic as ``/C/a/b``; POSIX paths pass through."""
    from inspect_ai.util._restic.ops import _tree_path

    assert _tree_path("/host/sample/context") == "/host/sample/context"
    assert _tree_path("C:\\Users\\me\\context") == "/C/Users/me/context"
    assert _tree_path("D:/logs/ctx/") == "/D/logs/ctx"


async def test_restore_repo_rejects_empty_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_restic(monkeypatch, _ONE_SNAPSHOT, _STORE_ONLY, lambda target: None)

    with pytest.raises(RuntimeError, match="produced no files"):
        await restore_repo(
            Path("/r"),
            "/repo",
            "pw",
            str(tmp_path / "ctx"),
            max_files=8,
            max_bytes=1024,
        )


# --- verify_regular_tree ---------------------------------------------------


def test_verify_regular_tree_accepts_files_and_dirs(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"12345")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.json").write_bytes(b"123")
    (tmp_path / "sub" / "empty").mkdir()

    assert verify_regular_tree(tmp_path, max_files=10, max_bytes=100) == TreeStats(
        files=2, bytes=8
    )


def test_verify_regular_tree_rejects_file_symlink(tmp_path: Path) -> None:
    secret = tmp_path / "outside.json"
    secret.write_text("{}")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(secret, root / "store.json")

    with pytest.raises(RestoredTreeError, match=r"symlink.*store\.json"):
        verify_regular_tree(root, max_files=10, max_bytes=100)


def test_verify_regular_tree_rejects_directory_symlink(tmp_path: Path) -> None:
    """A directory symlink is rejected, not descended into."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "host.txt").write_text("host")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "chain", target_is_directory=True)

    with pytest.raises(RestoredTreeError, match=r"symlink.*chain"):
        verify_regular_tree(root, max_files=10, max_bytes=100)


def test_verify_regular_tree_rejects_nested_dotdot_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    os.symlink("../../outside", root / "sub" / "escape")

    with pytest.raises(RestoredTreeError, match=r"symlink.*escape"):
        verify_regular_tree(root, max_files=10, max_bytes=100)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs need a POSIX platform")
def test_verify_regular_tree_rejects_fifo(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")

    with pytest.raises(RestoredTreeError, match=r"non-regular.*pipe"):
        verify_regular_tree(tmp_path, max_files=10, max_bytes=100)


def test_verify_regular_tree_enforces_entry_bound(tmp_path: Path) -> None:
    """Files and directories both count, so a forest of empty dirs is bounded."""
    for i in range(2):
        (tmp_path / f"f{i}").write_bytes(b"x")
    (tmp_path / "d").mkdir()

    with pytest.raises(RestoredTreeError, match="exceeds 2 entries"):
        verify_regular_tree(tmp_path, max_files=2, max_bytes=100)


def test_verify_regular_tree_enforces_byte_bound(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 60)
    (tmp_path / "b").write_bytes(b"x" * 60)

    with pytest.raises(RestoredTreeError, match="exceeds 100 bytes"):
        verify_regular_tree(tmp_path, max_files=10, max_bytes=100)


def test_verify_regular_tree_rejects_non_directory_root(tmp_path: Path) -> None:
    f = tmp_path / "file"
    f.write_text("x")

    with pytest.raises(RestoredTreeError, match="not a directory"):
        verify_regular_tree(f, max_files=10, max_bytes=100)
