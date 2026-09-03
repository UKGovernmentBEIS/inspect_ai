"""Real-restic tests for the host-side ``restore_repo`` resume path.

On resume the host repo is copied byte-for-byte from the resume source and
restored into the new attempt's ``context/`` dir — the repo is untrusted
input. These tests build actual restic repos (binary via ``resolve_restic``,
downloaded and cached on first use) and check that ``restore_repo`` lands
legitimate context files directly in the target and refuses a snapshot
whose tree would redirect reads or renames at host files.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from inspect_ai.util._restic import (
    RestoredTreeError,
    init_repo,
    resolve_restic,
    restore_repo,
    run_backup,
)

pytestmark = pytest.mark.slow

PASSWORD = "pw"
MAX_FILES = 64
MAX_BYTES = 1024**3


async def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    restic = await resolve_restic()
    repo = str(tmp_path / "repo")
    await init_repo(restic, repo, PASSWORD)
    return restic, repo


def _tree(root: Path) -> dict[str, str | None]:
    """Relative path → contents (``None`` for dirs/symlinks) for every entry."""
    out: dict[str, str | None] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root))
            out[rel] = p.read_text() if p.is_file() and not p.is_symlink() else None
    return out


async def test_restore_lands_context_files_directly_in_target(tmp_path: Path) -> None:
    """The snapshot's source dir is restored flat into target — no path chain."""
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text('{"k": 1}')
    (source / "events.json").write_text("[]")
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    target = tmp_path / "restored"
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert _tree(target) == {"store.json": '{"k": 1}', "events.json": "[]"}


async def test_restore_picks_latest_snapshot(tmp_path: Path) -> None:
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text('{"fire": 1}')
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")
    (source / "store.json").write_text('{"fire": 2}')
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00002")

    target = tmp_path / "restored"
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert (target / "store.json").read_text() == '{"fire": 2}'


async def test_restore_follows_source_path_across_attempts(tmp_path: Path) -> None:
    """Resume shape: the repo holds snapshots recorded from *different* source dirs.

    A retry FS-copies the prior attempt's repo (its snapshots record the
    old attempt's ``context`` path) and later fires add snapshots of the
    new attempt's ``context`` path. ``latest`` must resolve to exactly one
    snapshot across that path change, and the restore must use *its*
    recorded path.
    """
    restic, repo = await _init_repo(tmp_path)
    old_context = tmp_path / "attempt-1" / "context"
    new_context = tmp_path / "attempt-2" / "context"
    old_context.mkdir(parents=True)
    new_context.mkdir(parents=True)
    (old_context / "store.json").write_text('{"attempt": 1}')
    await run_backup(restic, repo, PASSWORD, str(old_context), "ckpt-00001")
    (new_context / "store.json").write_text('{"attempt": 2}')
    await run_backup(restic, repo, PASSWORD, str(new_context), "ckpt-00002")

    target = tmp_path / "restored"
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert _tree(target) == {"store.json": '{"attempt": 2}'}


async def test_restore_refuses_snapshot_with_symlinks(tmp_path: Path) -> None:
    """A snapshot carrying ``store.json`` → host file and a dir symlink chain fails.

    The listing gate rejects it before restic writes anything, so the
    target stays empty; nothing outside the target is read, moved, or
    created — the host files the symlinks point at are still in place and
    unchanged afterwards.
    """
    restic, repo = await _init_repo(tmp_path)
    host = tmp_path / "host"
    (host / "dir").mkdir(parents=True)
    (host / "secret.json").write_text('{"pwned": true}')
    (host / "dir" / "file.txt").write_text("host file")
    host_before = _tree(host)

    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    os.symlink(host / "secret.json", source / "store.json")
    os.symlink(host / "dir", source / "chain", target_is_directory=True)
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    target = tmp_path / "restored"
    siblings_before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(RestoredTreeError, match="symlink"):
        await restore_repo(
            restic,
            repo,
            PASSWORD,
            str(target),
            max_files=MAX_FILES,
            max_bytes=MAX_BYTES,
        )

    assert _tree(host) == host_before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [*siblings_before, "restored"]
    )
    assert list(target.iterdir()) == []


async def test_restore_refuses_multi_path_snapshot(tmp_path: Path) -> None:
    restic, repo = await _init_repo(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "a.json").write_text("{}")
    (second / "b.json").write_text("{}")
    await run_backup(restic, repo, PASSWORD, [str(first), str(second)], "ckpt-00001")

    with pytest.raises(RuntimeError, match="exactly one source path"):
        await restore_repo(
            restic,
            repo,
            PASSWORD,
            str(tmp_path / "restored"),
            max_files=MAX_FILES,
            max_bytes=MAX_BYTES,
        )
