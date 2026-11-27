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

import errno
import inspect
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from test_helpers.restic import SUMMARY_SNAPSHOT_ID, restic_summary_json

from inspect_ai.util._restic.ops import (
    RestoredTreeError,
    _normalize_restored_tree,
    _parse_changed_files,
    _parse_listed_files,
    _previous_id,
    list_changed_files,
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


@pytest.mark.parametrize("parent", [None, "--password-command=echo parent"])
async def test_list_changed_files_terminates_options(parent: str | None) -> None:
    snapshot_id = "--password-command=echo snapshot"
    snapshots = [{"id": snapshot_id, "time": "2026-01-02"}]
    if parent is not None:
        snapshots.append({"id": parent, "time": "2026-01-01"})
    run = AsyncMock(
        side_effect=[
            SimpleNamespace(stdout=json.dumps(snapshots).encode()),
            SimpleNamespace(stdout=b""),
        ]
    )
    with patch("anyio.run_process", run):
        assert await list_changed_files(Path("/r"), "/repo", "pw", snapshot_id, 10) == (
            [],
            0,
        )
    operands = [snapshot_id] if parent is None else [parent, snapshot_id]
    assert run.call_args.args[0] == [
        "/r",
        "-r",
        "/repo",
        "ls" if parent is None else "diff",
        "--json",
        "--",
        *operands,
    ]


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


_GO_MODE_DIR = 1 << 31
_GO_MODE_SETUID = 1 << 23
_GO_MODE_SETGID = 1 << 22
_GO_MODE_STICKY = 1 << 20
"""Go ``os.FileMode`` bits, the layout ``restic ls --json`` uses for ``mode``."""

posix_modes = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX permission bits"
)


def _ls_node(
    path: str, type: str, size: int | None = 0, *, mode: object = None
) -> dict[str, object]:
    """One ``restic ls --json`` node; ``size=None`` omits the key (malformed file).

    ``mode=None`` omits ``mode``, as restic does for a zero mode. Emits
    both record-kind keys as restic 0.17+ does (``struct_type`` is the
    deprecated pre-0.17 name).
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
    if mode is not None:
        node["mode"] = mode
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
    assert calls[0][3:] == ["ls", "--json", "--", "latest"]
    restore_dir = Path(calls[1][calls[1].index("--target") + 1])
    assert restore_dir == _restore_dir(target, during=restore_dir)
    assert calls[1][3:] == [
        "restore",
        "--target",
        str(restore_dir),
        "--verify",
        "--exclude-xattr",
        "*",
        "--",
        f"{_SNAPSHOT_ID}:{_SNAPSHOT_PATH}",
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


@pytest.mark.parametrize(
    "mode",
    [
        _GO_MODE_SETUID | 0o755,
        _GO_MODE_SETGID | 0o755,
        _GO_MODE_STICKY | 0o644,
        _GO_MODE_SETUID | _GO_MODE_SETGID | 0o777,
        _GO_MODE_DIR | 0o755,
    ],
)
async def test_restore_repo_rejects_file_node_with_non_permission_mode_bit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int
) -> None:
    """A file recording setuid, setgid, sticky or a type bit fails before restore."""
    listing = _ls_chain(
        _ls_node(f"{_SNAPSHOT_PATH}/store.json", "file", size=2, mode=mode)
    )
    calls = _fake_restic(monkeypatch, listing, _write_store)
    target = tmp_path / "ctx"

    with pytest.raises(RestoredTreeError, match=r"mode bit.*store\.json"):
        await _restore(target)
    assert [c[3] for c in calls] == ["ls"]
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("mode", ["0644", True, 420.0, [420]])
async def test_restore_repo_rejects_file_node_with_non_integer_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: object
) -> None:
    """A malformed mode is rejected, not coerced."""
    listing = _ls_chain(
        _ls_node(f"{_SNAPSHOT_PATH}/store.json", "file", size=2, mode=mode)
    )
    calls = _fake_restic(monkeypatch, listing, _write_store)

    with pytest.raises(RestoredTreeError, match=r"non-integer mode.*store\.json"):
        await _restore(tmp_path / "ctx")
    assert [c[3] for c in calls] == ["ls"]


@pytest.mark.parametrize("mode", [None, 0o600, 0o644, 0o666, 0o777])
async def test_restore_repo_accepts_file_node_with_permission_bits_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int | None
) -> None:
    """Any plain permission mode restores; an absent ``mode`` is restic's zero mode."""
    listing = _ls_chain(
        _ls_node(f"{_SNAPSHOT_PATH}/store.json", "file", size=2, mode=mode)
    )
    calls = _fake_restic(monkeypatch, listing, _write_store)

    await _restore(tmp_path / "ctx")

    assert [c[3] for c in calls] == ["ls", "restore"]


async def test_restore_repo_accepts_special_mode_bits_on_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sticky and setgid ancestors or source dirs are honest: ``/tmp``, a ``g+s`` log dir."""
    listing: list[dict[str, object]] = [
        _ls_header(),
        _ls_node("/host", "dir", mode=_GO_MODE_DIR | _GO_MODE_STICKY | 0o777),
        _ls_node("/host/sample", "dir", mode=_GO_MODE_DIR | _GO_MODE_SETGID | 0o775),
        _ls_node(_SNAPSHOT_PATH, "dir", mode=_GO_MODE_DIR | _GO_MODE_SETGID | 0o775),
        _ls_node(f"{_SNAPSHOT_PATH}/store.json", "file", size=2, mode=0o600),
    ]
    calls = _fake_restic(monkeypatch, listing, _write_store)

    await _restore(tmp_path / "ctx")

    assert [c[3] for c in calls] == ["ls", "restore"]


@pytest.mark.parametrize(
    "kinds", [("file", "dir"), ("dir", "file"), ("file", "file"), ("dir", "dir")]
)
async def test_restore_repo_rejects_path_listed_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kinds: tuple[str, str]
) -> None:
    """Two nodes at one path fail before restore, whatever their kinds or order."""
    path = f"{_SNAPSHOT_PATH}/store.json"
    listing = _ls_chain(*(_ls_node(path, kind, size=2) for kind in kinds))
    calls = _fake_restic(monkeypatch, listing, _write_store)
    target = tmp_path / "ctx"

    with pytest.raises(RestoredTreeError, match=r"more than once.*store\.json"):
        await _restore(target)
    assert [c[3] for c in calls] == ["ls"]
    assert list(target.iterdir()) == []


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def _is_scratch(path: Path) -> bool:
    return path.name.startswith(".restore-")


def _restore_dir(target: Path, *, during: Path | None = None) -> Path:
    """Where restic writes for ``target``: its scratch dir, or ``target`` itself in place.

    ``during`` is the directory restic was given; after a failed restore the
    scratch dir is found in ``target`` instead.
    """
    if during is not None:
        assert during == target or (during.parent == target and _is_scratch(during))
        return during
    scratch = [p for p in target.iterdir() if _is_scratch(p)]
    assert len(scratch) <= 1
    return scratch[0] if scratch else target


def _beside_scratch(restore_dir: Path) -> list[str]:
    """Names already in the target when restic starts, other than its scratch dir."""
    if not _is_scratch(restore_dir):
        return sorted(p.name for p in restore_dir.iterdir())
    return sorted(p.name for p in restore_dir.parent.iterdir() if p != restore_dir)


@posix_modes
async def test_restore_repo_replaces_restored_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What lands in the target has host-chosen modes, whatever the listing said.

    The listing here is clean while the restore leaves special and
    group/other bits behind, as restic can on a case-insensitive
    filesystem where two listed paths are one file. Restic writes into a
    scratch dir inside the target that only its owner can enter (it
    inherits the target's setgid bit, which grants nothing), and the
    target's own mode is kept.
    """
    target = tmp_path / "ctx"
    target.mkdir()
    target.chmod(0o2775)
    target_mode = _mode(target)
    scratch_at_restore: list[Path] = []
    scratch_mode_at_restore: list[int] = []

    def restore(path: Path) -> None:
        scratch_at_restore.append(path)
        scratch_mode_at_restore.append(_mode(path) & 0o777)
        _write_store(path)
        (path / "store.json").chmod(0o4777)
        (path / "events.json").write_text("[]")
        (path / "events.json").chmod(0o2666)
        shared = path / "shared"
        shared.mkdir()
        (shared / "x.json").write_text("{}")
        (shared / "x.json").chmod(0o666)
        shared.chmod(0o1777)
        locked = path / "locked"
        locked.mkdir()
        (locked / "y.json").write_text("{}")
        locked.chmod(0)

    _fake_restic(monkeypatch, _STORE_ONLY, restore)

    try:
        await _restore(target)
        assert _mode(target / "locked") == 0o700
    finally:
        for parent in (target, *scratch_at_restore):
            if (parent / "locked").exists():
                (parent / "locked").chmod(0o700)

    assert [p.parent for p in scratch_at_restore] == [target]
    assert scratch_mode_at_restore == [0o700]
    assert _mode(target) == target_mode
    assert sorted(p.name for p in target.iterdir()) == [
        "events.json",
        "locked",
        "shared",
        "store.json",
    ]
    assert _mode(target / "shared") == 0o700
    for name in ("store.json", "events.json", "shared/x.json", "locked/y.json"):
        assert _mode(target / name) == 0o600, name
    assert (target / "store.json").read_text() == "{}"


@posix_modes
def test_normalize_restored_tree_does_not_recurse(tmp_path: Path) -> None:
    """The listing bounds entries, not depth, so the mode walk must not recurse.

    The tree is far deeper than the recursion budget left for the call.
    """
    leaf = tmp_path.joinpath(*["d"] * 200)
    leaf.mkdir(parents=True)
    (leaf / "store.json").write_text("{}")
    (leaf / "store.json").chmod(0o666)

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + 50)
    try:
        _normalize_restored_tree(tmp_path)
    finally:
        sys.setrecursionlimit(limit)

    assert _mode(leaf / "store.json") == 0o600
    assert _mode(leaf) == 0o700


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
@posix_modes
async def test_restore_repo_rejects_non_regular_entry_in_restored_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    """A non-regular entry on disk after restore raises; it is neither chmodded nor adopted."""
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    outside.chmod(0o644)
    target = tmp_path / "ctx"

    def restore(path: Path) -> None:
        if kind == "symlink":
            os.symlink(outside, path / "store.json")
        else:
            os.mkfifo(path / "store.json")

    _fake_restic(monkeypatch, _STORE_ONLY, restore)

    with pytest.raises(RestoredTreeError, match=r"non-regular entry.*store\.json"):
        await _restore(target)
    assert _mode(outside) == 0o644
    (scratch,) = target.iterdir()
    assert scratch.name.startswith(".restore-")


@posix_modes
async def test_restore_repo_failure_keeps_recorded_modes_inside_scratch_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed restore's partial tree is only reachable through the 0700 scratch dir."""
    target = tmp_path / "ctx"
    target.mkdir()
    target.chmod(0o775)

    def fail_midway(path: Path) -> None:
        (path / "partial.json").write_text("{")
        (path / "partial.json").chmod(0o4777)
        raise subprocess.CalledProcessError(1, ["restic", "restore"])

    _fake_restic(monkeypatch, _STORE_ONLY, fail_midway)

    with pytest.raises(subprocess.CalledProcessError):
        await _restore(target)

    (scratch,) = target.iterdir()
    assert [p.name for p in scratch.iterdir()] == ["partial.json"]
    assert _mode(scratch) & 0o777 == 0o700
    assert _mode(target) == 0o775


@posix_modes
async def test_restore_repo_leaves_target_mode_alone_when_listing_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A refused snapshot changes nothing about the target, its mode included."""
    listing = _ls_chain(_ls_node(f"{_SNAPSHOT_PATH}/store.json", "symlink"))
    _fake_restic(monkeypatch, listing, _write_store)
    target = tmp_path / "ctx"
    target.mkdir()
    target.chmod(0o770)

    with pytest.raises(RestoredTreeError, match="symlink"):
        await _restore(target)

    assert _mode(target) == 0o770
    assert list(target.iterdir()) == []


async def test_restore_repo_restores_in_place_without_posix_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Where there are no POSIX modes to reset (Windows), restic writes into the target itself."""
    from inspect_ai.util._restic import ops

    def no_chmod(path: str, mode: int, **kwargs: bool) -> None:
        raise AssertionError(f"unexpected chmod of {path}")

    target = tmp_path / "ctx"
    calls = _fake_restic(monkeypatch, _STORE_ONLY, _write_store)
    monkeypatch.setattr(ops, "_RESTORE_VIA_SCRATCH_DIR", False)
    monkeypatch.setattr(os, "chmod", no_chmod)

    await _restore(target)

    assert calls[1][calls[1].index("--target") + 1] == str(target)
    assert [p.name for p in target.iterdir()] == ["store.json"]


def _refuse_chmod(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    """Make ``os.chmod`` fail with ``code`` for the restored ``store.json`` only."""
    real_chmod = os.chmod

    def chmod(path: str, mode: int, **kwargs: bool) -> None:
        if str(path).endswith("store.json"):
            raise OSError(code, os.strerror(code), str(path))
        real_chmod(path, mode, **kwargs)

    monkeypatch.setattr(os, "chmod", chmod)


@pytest.mark.parametrize(
    ("code", "euid"), [(errno.ENOTSUP, 0), (errno.ENOTSUP, 1000), (errno.EPERM, 1000)]
)
@posix_modes
def test_normalize_restored_tree_tolerates_chmod_errors_restic_ignores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int, euid: int
) -> None:
    """``ENOTSUP``, and ``EPERM`` when not root: restic applied no recorded mode either."""
    _write_store(tmp_path)
    _refuse_chmod(monkeypatch, code)
    monkeypatch.setattr(os, "geteuid", lambda: euid)

    _normalize_restored_tree(tmp_path)


@pytest.mark.parametrize("chmod_outcome", ["tolerated error", "no effect"])
@pytest.mark.parametrize("mode", [0o4755, 0o2755, 0o1644])
@posix_modes
async def test_restore_repo_never_adopts_file_left_with_special_mode_bit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int, chmod_outcome: str
) -> None:
    """A file whose special bit survives the mode reset fails the restore.

    The reset can be refused with an error that is otherwise tolerated, or
    report success and change nothing, on a filesystem that assigns modes
    itself. Either way the file stays in the scratch dir.
    """
    target = tmp_path / "ctx"
    real_chmod = os.chmod
    probe = tmp_path / "probe"
    probe.write_text("")
    try:
        probe.chmod(mode)
    except OSError as ex:
        pytest.skip(f"cannot set mode {mode:04o} on a regular file: {ex}")
    if _mode(probe) != mode:
        pytest.skip(f"filesystem did not keep mode {mode:04o} on a regular file")

    def restore(path: Path) -> None:
        _write_store(path)
        real_chmod(path / "store.json", mode)

    def chmod(path: str, mode: int, **kwargs: bool) -> None:
        if not str(path).endswith("store.json"):
            real_chmod(path, mode, **kwargs)
        elif chmod_outcome == "tolerated error":
            raise OSError(errno.ENOTSUP, os.strerror(errno.ENOTSUP), str(path))

    _fake_restic(monkeypatch, _STORE_ONLY, restore)
    monkeypatch.setattr(os, "chmod", chmod)

    with pytest.raises(RestoredTreeError, match=r"sticky bit.*store\.json"):
        await _restore(target)

    (scratch,) = target.iterdir()
    assert [p.name for p in scratch.iterdir()] == ["store.json"]


@pytest.mark.parametrize(("code", "euid"), [(errno.EPERM, 0), (errno.EIO, 1000)])
@posix_modes
def test_normalize_restored_tree_fails_when_a_mode_cannot_be_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int, euid: int
) -> None:
    """Any other chmod failure propagates, which fails the restore."""
    _write_store(tmp_path)
    _refuse_chmod(monkeypatch, code)
    monkeypatch.setattr(os, "geteuid", lambda: euid)

    with pytest.raises(OSError, match=r"store\.json"):
        _normalize_restored_tree(tmp_path)


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

    assert calls[1][-1] == f"{_SNAPSHOT_ID}:/ckpts/1__1/context"
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
        seen_at_restore.append(_beside_scratch(path))
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
    """A failed restore leaves its partial tree in the scratch dir; the next restore empties it."""
    target = tmp_path / "ctx"

    def fail_midway(path: Path) -> None:
        (path / "partial.json").write_text("{")
        raise subprocess.CalledProcessError(1, ["restic", "restore"])

    _fake_restic(monkeypatch, _STORE_ONLY, fail_midway)
    with pytest.raises(subprocess.CalledProcessError):
        await _restore(target)
    assert [p.name for p in _restore_dir(target).iterdir()] == ["partial.json"]

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
        scratch = Path(command[command.index("--target") + 1])
        (scratch / "partial.json").write_text("{")
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    monkeypatch.setattr(anyio, "run_process", fake_run_process)
    with anyio.move_on_after(0.2) as scope:
        await _restore(target)
    assert scope.cancelled_caught
    assert [p.name for p in _restore_dir(target).iterdir()] == ["partial.json"]

    seen_at_restore: list[list[str]] = []

    def restore(path: Path) -> None:
        seen_at_restore.append(_beside_scratch(path))
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
