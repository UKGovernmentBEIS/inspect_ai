"""Tests for host-side restic ops that need no restic binary.

- ``_parse_listed_files`` parses ``restic ls`` (full snapshot tree) — used
  for the first snapshot, which has no parent.
- ``_parse_changed_files`` parses ``restic diff`` (added/changed entries
  vs the parent) — used for every later snapshot.
  Both keep files only, cap the list, and count the overflow.
- ``run_backup`` / ``restore_repo`` invocation shape (restic mocked): the
  snapshot listing check, target handling, and the restore call.

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
    RestoredTreeError,
    _parse_changed_files,
    _parse_listed_files,
    _previous_id,
    restore_repo,
    run_backup,
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
_NO_SNAPSHOT_STDERR = (
    b'{"message_type":"exit_error","code":1,"message":"snapshot filter '
    b'(Paths:[] Tags:[] Hosts:[]): no snapshot found"}'
)


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


def _ls_header(
    source_path: str = _SNAPSHOT_PATH, *, paths: list[str] | None = None
) -> dict[str, object]:
    """The leading snapshot record of ``restic ls --json`` (``id`` + ``paths``)."""
    return {
        "id": _SNAPSHOT_ID,
        "short_id": _SNAPSHOT_ID[:8],
        "paths": [source_path] if paths is None else paths,
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
    listing: list[dict[str, object]] | bytes | None,
    restore: Callable[[Path], None],
) -> list[list[str]]:
    """Stub ``anyio.run_process`` for ``ls``/``restore``; return the calls.

    ``listing`` is the ``ls --json latest`` output: records, raw bytes, or
    ``None`` for a repo with no snapshot (restic exits 1 there).
    """
    calls: list[list[str]] = []

    async def fake_run_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        if "ls" in command:
            if listing is None:
                raise subprocess.CalledProcessError(
                    1, command, output=b"", stderr=_NO_SNAPSHOT_STDERR
                )
            if isinstance(listing, bytes):
                return SimpleNamespace(stdout=listing)
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
    """One ``ls`` supplies snapshot and listing; restore names the recorded path."""
    calls = _fake_restic(monkeypatch, _STORE_ONLY, _write_store)
    target = tmp_path / "ctx"

    await _restore(target)

    assert [c[3] for c in calls] == ["ls", "restore"]
    assert calls[0][3:] == ["ls", "--json", "latest"]
    assert calls[1][3:] == [
        "restore",
        f"{_SNAPSHOT_ID}:{_SNAPSHOT_PATH}",
        "--target",
        str(target),
        "--verify",
    ]
    assert [p.name for p in target.iterdir()] == ["store.json"]


async def test_restore_repo_rejects_empty_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ls latest`` on a repo with no snapshot exits 1 — reported, not restored."""
    calls = _fake_restic(monkeypatch, None, _write_store)

    with pytest.raises(RuntimeError, match="no snapshot"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


async def test_restore_repo_rejects_listing_without_snapshot_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_restic(monkeypatch, _STORE_ONLY[1:], _write_store)

    with pytest.raises(RuntimeError, match="no snapshot record"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


async def test_restore_repo_rejects_multi_path_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A snapshot recording more than one source path never reaches restore."""
    listing = [_ls_header(paths=[_SNAPSHOT_PATH, "/other"]), *_STORE_ONLY[1:]]
    calls = _fake_restic(monkeypatch, listing, _write_store)

    with pytest.raises(RuntimeError, match="exactly one source path"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


@pytest.mark.parametrize("kind", ["symlink", "fifo", "socket", "chardev"])
async def test_restore_repo_rejects_non_regular_node_before_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    """A non-regular node in the listing fails before restic writes anything."""
    listing = _ls_chain(
        _ls_node(f"{_SNAPSHOT_PATH}/store.json", kind),
        _ls_node(f"{_SNAPSHOT_PATH}/events.json", "file", size=2),
    )
    calls = _fake_restic(monkeypatch, listing, _write_store)
    target = tmp_path / "ctx"

    with pytest.raises(RestoredTreeError, match=rf"{kind} node.*store\.json"):
        await _restore(target)
    assert [c[3] for c in calls] == ["ls"]
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
    calls = _fake_restic(monkeypatch, listing, _write_store)

    with pytest.raises(RuntimeError, match="not a directory in the snapshot"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


async def test_restore_repo_rejects_source_path_listed_as_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    listing: list[dict[str, object]] = [
        _ls_header(),
        _ls_node("/host", "dir"),
        _ls_node("/host/sample", "dir"),
        _ls_node(_SNAPSHOT_PATH, "file", size=2),
    ]
    calls = _fake_restic(monkeypatch, listing, _write_store)

    with pytest.raises(RuntimeError, match="not a directory in the snapshot"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


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
    calls = _fake_restic(monkeypatch, listing, _write_store)
    target = tmp_path / "ctx"

    await _restore(target)

    assert calls[1][4] == f"{_SNAPSHOT_ID}:/ckpts/1__1/context"
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
    calls = _fake_restic(monkeypatch, listing, _write_store)

    await _restore(tmp_path / "ctx")

    assert [c[3] for c in calls] == ["ls", "restore"]


async def test_restore_repo_rejects_file_node_without_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A malformed listing is rejected, not coerced to size 0."""
    listing = _ls_chain(_ls_node(f"{_SNAPSHOT_PATH}/store.json", "file", size=None))
    calls = _fake_restic(monkeypatch, listing, _write_store)

    with pytest.raises(RestoredTreeError, match=r"without a size.*store\.json"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


async def test_restore_repo_enforces_listing_bounds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Entry and byte bounds apply to the listing, before restore."""
    big = _ls_chain(_ls_node(f"{_SNAPSHOT_PATH}/events.json", "file", size=4096))
    calls = _fake_restic(monkeypatch, big, _write_store)
    with pytest.raises(RestoredTreeError, match="exceeds 1024 bytes"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]

    many = _ls_chain(
        *(_ls_node(f"{_SNAPSHOT_PATH}/f{i}.json", "file", size=1) for i in range(8))
    )
    calls = _fake_restic(monkeypatch, many, _write_store)
    with pytest.raises(RestoredTreeError, match="exceeds 8 entries"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


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
    calls = _fake_restic(monkeypatch, listing, _write_store)

    with pytest.raises(RestoredTreeError, match="exceeds 8 entries"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


async def test_restore_repo_empties_target_before_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Stale entries in the target are removed before restic runs.

    Restic overwrites the snapshot's members but leaves other names alone,
    so files an interrupted fire left in ``context/`` would otherwise
    survive as state newer than the committed checkpoint. Stale symlinks
    are unlinked, not followed.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("host file")
    target = tmp_path / "ctx"
    target.mkdir()
    (target / "store.json").write_text('{"uncommitted": true}')
    (target / "agent_state.json").write_text("{}")
    (target / "nested").mkdir()
    (target / "nested" / "x.tmp").write_text("x")
    os.symlink(elsewhere, target / "link", target_is_directory=True)
    seen_at_restore: list[list[str]] = []

    def restore(path: Path) -> None:
        seen_at_restore.append(sorted(p.name for p in path.iterdir()))
        _write_store(path)

    _fake_restic(monkeypatch, _STORE_ONLY, restore)

    await _restore(target)

    assert seen_at_restore == [[]]
    assert [p.name for p in target.iterdir()] == ["store.json"]
    assert (target / "store.json").read_text() == "{}"
    assert (elsewhere / "keep.txt").read_text() == "host file"


async def test_restore_repo_leaves_target_alone_when_listing_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The target is emptied only once the snapshot has passed the listing check."""
    listing = _ls_chain(_ls_node(f"{_SNAPSHOT_PATH}/store.json", "symlink"))
    _fake_restic(monkeypatch, listing, _write_store)
    target = tmp_path / "ctx"
    target.mkdir()
    (target / "store.json").write_text('{"prior": true}')

    with pytest.raises(RestoredTreeError, match="symlink"):
        await _restore(target)
    assert (target / "store.json").read_text() == '{"prior": true}'


async def test_restore_repo_rejects_symlinked_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A target that is a symlink is refused before restic runs; nothing is followed."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("host file")
    target = tmp_path / "ctx"
    os.symlink(elsewhere, target, target_is_directory=True)
    calls = _fake_restic(monkeypatch, _STORE_ONLY, _write_store)

    with pytest.raises(RuntimeError, match="target is a symlink"):
        await _restore(target)
    assert calls == []
    assert target.is_symlink()
    assert [p.name for p in elsewhere.iterdir()] == ["keep.txt"]


async def test_restore_repo_rejects_non_directory_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "ctx"
    target.write_text("not a dir")
    calls = _fake_restic(monkeypatch, _STORE_ONLY, _write_store)

    with pytest.raises(RuntimeError, match="not a directory"):
        await _restore(target)
    assert calls == []
    assert target.read_text() == "not a dir"


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="root ignores directory permissions",
)
async def test_restore_repo_surfaces_target_emptying_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale entry that cannot be removed fails the restore instead of being skipped."""
    target = tmp_path / "ctx"
    locked = target / "locked"
    locked.mkdir(parents=True)
    (locked / "x").write_text("x")
    locked.chmod(0)
    calls = _fake_restic(monkeypatch, _STORE_ONLY, _write_store)

    try:
        with pytest.raises(PermissionError):
            await _restore(target)
    finally:
        locked.chmod(0o700)
    assert [c[3] for c in calls] == ["ls"]


async def test_restore_repo_propagates_restic_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed restore propagates and leaves its partial tree; the next restore empties it."""
    target = tmp_path / "ctx"

    def fail_midway(path: Path) -> None:
        (path / "partial.json").write_text("{")
        raise subprocess.CalledProcessError(1, ["restic", "restore"])

    _fake_restic(monkeypatch, _STORE_ONLY, fail_midway)
    with pytest.raises(subprocess.CalledProcessError):
        await _restore(target)
    assert [p.name for p in target.iterdir()] == ["partial.json"]

    _fake_restic(monkeypatch, _STORE_ONLY, _write_store)
    await _restore(target)
    assert [p.name for p in target.iterdir()] == ["store.json"]


async def test_restore_repo_cancelled_mid_restore_then_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cancellation while restic writes propagates; the retry starts from an empty target."""
    target = tmp_path / "ctx"

    async def fake_run_process(command: list[str], **kwargs: object) -> SimpleNamespace:
        if "ls" in command:
            lines = "\n".join(json.dumps(record) for record in _STORE_ONLY)
            return SimpleNamespace(stdout=lines.encode())
        (target / "partial.json").write_text("{")
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    monkeypatch.setattr(anyio, "run_process", fake_run_process)
    with anyio.move_on_after(0.2) as scope:
        await _restore(target)
    assert scope.cancelled_caught
    assert [p.name for p in target.iterdir()] == ["partial.json"]

    seen_at_restore: list[list[str]] = []

    def restore(path: Path) -> None:
        seen_at_restore.append(sorted(p.name for p in path.iterdir()))
        _write_store(path)

    _fake_restic(monkeypatch, _STORE_ONLY, restore)
    await _restore(target)
    assert seen_at_restore == [[]]
    assert [p.name for p in target.iterdir()] == ["store.json"]


def test_tree_path_maps_windows_drive_to_root_component() -> None:
    r"""``C:\a\b`` is stored by restic as ``/C/a/b``; POSIX paths pass through."""
    from inspect_ai.util._restic.ops import _tree_path

    assert _tree_path("/host/sample/context") == "/host/sample/context"
    assert _tree_path("C:\\Users\\me\\context") == "/C/Users/me/context"
    assert _tree_path("D:/logs/ctx/") == "/D/logs/ctx"


def test_tree_path_refuses_unc_and_extended_length_paths() -> None:
    r"""``\\server\share`` and ``\\?\`` sources have no verified tree form."""
    from inspect_ai.util._restic.ops import _tree_path

    with pytest.raises(RuntimeError, match="UNC"):
        _tree_path("\\\\server\\share\\ckpts\\context")
    with pytest.raises(RuntimeError, match="UNC"):
        _tree_path("\\\\?\\C:\\ckpts\\context")
