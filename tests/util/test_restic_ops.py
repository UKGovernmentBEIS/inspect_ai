"""Tests for restic output parsing used by snapshot file listing.

- ``_parse_listed_files`` parses ``restic ls`` (full snapshot tree) — used
  for the first snapshot, which has no parent.
- ``_parse_changed_files`` parses ``restic diff`` (added/changed entries
  vs the parent) — used for every later snapshot.
Both keep files only, cap the list, and count the overflow.
"""

from __future__ import annotations

import json

from inspect_ai.util._restic.ops import (
    _parse_changed_files,
    _parse_listed_files,
    _previous_id,
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
