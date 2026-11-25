"""Real-restic tests for the host-side ``restore_repo`` resume path.

On resume the host repo is copied byte-for-byte from the resume source and
restored into the new attempt's ``context/`` dir — the repo is untrusted
input. These tests build actual restic repos (binary via ``resolve_restic``,
downloaded and cached on first use) and check that ``restore_repo`` lands
legitimate context files directly in the target, refuses a snapshot
whose tree would redirect reads or renames at host files, and keeps none
of the snapshot's recorded modes or extended attributes.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import anyio
import pytest

from inspect_ai.util._restic import (
    RestoredTreeError,
    init_repo,
    resolve_restic,
    restic_env,
    restore_repo,
    run_backup,
)

pytestmark = pytest.mark.slow

posix_modes = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX permission bits"
)

PASSWORD = "pw"
MAX_FILES = 64
MAX_BYTES = 1024**3


async def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    restic = await resolve_restic()
    repo = str(tmp_path / "repo")
    await init_repo(restic, repo, PASSWORD)
    return restic, repo


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


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


async def test_restore_handles_relative_backup_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative ``checkpoints_location`` makes the backup source relative.

    ``run_backup`` absolutizes it, so the snapshot's recorded path and
    tree root agree and the restore lands the files directly in target.
    """
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "ckpts" / "1__1" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text('{"rel": true}')
    monkeypatch.chdir(tmp_path)
    await run_backup(restic, repo, PASSWORD, "ckpts/1__1/context", "ckpt-00001")

    target = tmp_path / "restored"
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert _tree(target) == {"store.json": '{"rel": true}'}


async def test_restore_handles_legacy_relative_rooted_snapshot(tmp_path: Path) -> None:
    """Snapshots older versions wrote from a relative source still restore.

    Restic given a relative source records the absolute path in ``paths``
    but roots the tree at the relative components; the restore must find
    the source dir by that tree path, not fail on the recorded one.
    """
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "ckpts" / "1__1" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text('{"legacy": true}')
    # Invoke restic directly: the pre-fix run_backup passed the source verbatim.
    await anyio.run_process(
        [str(restic), "-r", repo, "backup", "ckpts/1__1/context", "--tag", "ckpt-1"],
        env=restic_env(PASSWORD),
        cwd=str(tmp_path),
        check=True,
    )

    target = tmp_path / "restored"
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert _tree(target) == {"store.json": '{"legacy": true}'}


async def test_restore_refuses_snapshot_with_symlinks(tmp_path: Path) -> None:
    """A snapshot carrying ``store.json`` → host file and a dir symlink chain fails.

    The snapshot listing check rejects it before restic writes anything,
    so the target stays empty; nothing outside the target is read, moved,
    or created — the host files the symlinks point at are still in place
    and unchanged afterwards.
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


@pytest.mark.parametrize("mode", [0o4755, 0o2755, 0o1644])
@posix_modes
async def test_restore_refuses_snapshot_with_special_mode_file(
    tmp_path: Path, mode: int
) -> None:
    """A regular file recorded setuid, setgid or sticky fails before restic writes."""
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text("{}")
    (source / "tool").write_text("#!/bin/sh\n")
    try:
        (source / "tool").chmod(mode)
    except OSError as ex:
        pytest.skip(f"cannot set mode {mode:04o} on a regular file: {ex}")
    if _mode(source / "tool") != mode:
        pytest.skip(f"filesystem did not keep mode {mode:04o} on a regular file")
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    target = tmp_path / "restored"
    with pytest.raises(RestoredTreeError, match="mode bit.*tool"):
        await restore_repo(
            restic,
            repo,
            PASSWORD,
            str(target),
            max_files=MAX_FILES,
            max_bytes=MAX_BYTES,
        )

    assert list(target.iterdir()) == []


@posix_modes
async def test_restore_replaces_recorded_modes(tmp_path: Path) -> None:
    """Restored files land 0600 and directories 0700, whatever the snapshot recorded.

    The source dir itself is setgid here, as a context dir created under a
    ``g+s`` log directory is; that must not refuse the restore. The
    target's own mode is not changed.
    """
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text('{"k": 1}')
    (source / "store.json").chmod(0o666)
    (source / "events.json").write_text("[]")
    (source / "events.json").chmod(0o755)
    shared = source / "shared"
    shared.mkdir()
    (shared / "x.json").write_text("{}")
    (shared / "x.json").chmod(0o664)
    shared.chmod(0o3777)
    source.chmod(0o2775)
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    target = tmp_path / "restored"
    target.mkdir()
    target.chmod(0o777)
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert _tree(target) == {
        "store.json": '{"k": 1}',
        "events.json": "[]",
        "shared": None,
        "shared/x.json": "{}",
    }
    assert _mode(target) == 0o777
    assert _mode(target / "shared") == 0o700
    for name in ("store.json", "events.json", "shared/x.json"):
        assert _mode(target / name) == 0o600, name


@posix_modes
async def test_restic_leaves_scratch_dir_mode_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restic does not change the mode of the directory it restores into.

    The scratch dir's 0700 is what keeps recorded modes out of reach until
    they are reset, so a restic that applied the source dir's recorded mode
    (0777 here) to its target would undo that.
    """
    from inspect_ai.util._restic import ops

    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text("{}")
    source.chmod(0o777)
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    scratch_modes: list[int] = []
    adopt = ops._adopt_restored_tree

    def record_then_adopt(scratch: Path, target: Path) -> None:
        scratch_modes.append(_mode(scratch) & 0o777)
        adopt(scratch, target)

    monkeypatch.setattr(ops, "_adopt_restored_tree", record_then_adopt)
    target = tmp_path / "restored"
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert scratch_modes == [0o700]
    assert _tree(target) == {"store.json": "{}"}


@pytest.mark.skipif(sys.platform != "linux", reason="os.setxattr is Linux-only")
async def test_restore_does_not_reapply_extended_attributes(tmp_path: Path) -> None:
    """An extended attribute the snapshot recorded is not set on the restored file.

    A plain ``restic restore`` of the same snapshot does set it, which shows
    the snapshot carries the attribute and the exclusion is what drops it.
    The control restores the source dir alone, so it does not depend on
    restic being able to reapply the metadata of the dirs above it.
    """
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text("{}")
    try:
        os.setxattr(source / "store.json", "user.inspect_test", b"1")
    except OSError as ex:
        pytest.skip(f"filesystem does not support user extended attributes: {ex}")
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    plain = tmp_path / "plain"
    await anyio.run_process(
        [
            str(restic),
            "-r",
            repo,
            "restore",
            "--target",
            str(plain),
            "--",
            f"latest:{source}",
        ],
        env=restic_env(PASSWORD),
        check=True,
    )
    assert "user.inspect_test" in os.listxattr(plain / "store.json")

    target = tmp_path / "restored"
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert (target / "store.json").read_text() == "{}"
    assert "user.inspect_test" not in os.listxattr(target / "store.json")


async def test_restore_empties_target_before_restoring(tmp_path: Path) -> None:
    """Files already in the target that the snapshot lacks do not survive.

    Restic overwrites the snapshot's members but leaves other names alone,
    so a file an interrupted fire left in ``context/`` (the requeue path
    restores into the same dir) would otherwise outlive the restore as
    state newer than the committed checkpoint.
    """
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text('{"committed": true}')
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    target = tmp_path / "restored"
    target.mkdir()
    (target / "store.json").write_text('{"uncommitted": true}')
    (target / "agent_state.json").write_text('{"newer": true}')
    (target / "leftover").mkdir()
    (target / "leftover" / "x.tmp").write_text("x")
    await restore_repo(
        restic, repo, PASSWORD, str(target), max_files=MAX_FILES, max_bytes=MAX_BYTES
    )

    assert _tree(target) == {"store.json": '{"committed": true}'}


async def test_restore_refuses_symlinked_target(tmp_path: Path) -> None:
    """A ``context/`` replaced by a symlink is refused, not followed.

    Nothing is written into, or removed from, the directory it points at.
    """
    restic, repo = await _init_repo(tmp_path)
    source = tmp_path / "sample" / "context"
    source.mkdir(parents=True)
    (source / "store.json").write_text('{"k": 1}')
    await run_backup(restic, repo, PASSWORD, str(source), "ckpt-00001")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("host file")
    target = tmp_path / "restored"
    os.symlink(elsewhere, target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="target is a symlink"):
        await restore_repo(
            restic,
            repo,
            PASSWORD,
            str(target),
            max_files=MAX_FILES,
            max_bytes=MAX_BYTES,
        )

    assert target.is_symlink()
    assert _tree(elsewhere) == {"keep.txt": "host file"}


async def test_restore_rejects_empty_repo(tmp_path: Path) -> None:
    """``restic ls latest`` exits non-zero on a repo with no snapshot."""
    restic, repo = await _init_repo(tmp_path)

    with pytest.raises(RuntimeError, match="no snapshot"):
        await restore_repo(
            restic,
            repo,
            PASSWORD,
            str(tmp_path / "restored"),
            max_files=MAX_FILES,
            max_bytes=MAX_BYTES,
        )


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
