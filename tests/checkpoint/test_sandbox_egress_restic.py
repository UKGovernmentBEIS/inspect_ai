"""Sandbox restic egress/ingress against a real restic binary.

Drives ``egress_sandbox`` end to end with the ``LocalShellSandbox`` fake:
the "in-sandbox" repo is a real restic repo under a temp dir that real
``restic backup`` invocations write into, the egress shell (find, comm,
tar, dd) runs on the host, and the host-side checks run against the
destination repo with the same binary. Covers the host-side truth
checks the egress protocol makes: a fire that captured nothing raises,
a replayed id, an unshipped reported id, or a foreign tag is rejected
and leaves the destination unchanged, an unrecorded extra snapshot (a
failed fire's leftover or a planted one) ships as an orphan, the
transfer cap binds, and resume-side orphan discard keeps exactly the
recorded snapshots and restores the recorded id. The ingress tests also
cover the host-side scope check: a snapshot reaching outside the
capture roots, or carrying a fifo or a setuid/sticky mode, is refused
before any exec, and a normal home-dir snapshot (symlinks included)
round-trips without touching anything above its root. The listing
streamer's failure paths (a rejected node mid-stream, a failing restic,
a listing with no snapshot record, an unterminated or oversized record)
run against a shell script standing in for restic, so they need neither
Docker nor the restic download.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, Callable
from unittest.mock import patch

import anyio
import pytest
from test_helpers.local_shell_sandbox import LocalShellSandbox

from inspect_ai.util._checkpoint._copy import copy_out, copy_out_partial_path
from inspect_ai.util._checkpoint._layout.schemas import SnapshotDetails
from inspect_ai.util._checkpoint._repo_ops import (
    forget_unrecorded_snapshots,
    list_snapshots,
    walk_snapshot_nodes,
)
from inspect_ai.util._checkpoint._restore_scope import (
    RestoreRoots,
    RestoreScopeError,
    remove_existing_symlinks,
    restic_node,
)
from inspect_ai.util._checkpoint._sandbox_restic.egress import (
    EgressVerificationError,
    _EgressBuild,
    _write_member,
    egress_sandbox,
    ingress_sandbox,
)
from inspect_ai.util._restic import ResticBackupSummary, resolve_restic
from inspect_ai.util._sandbox._framework_directory import FrameworkDirectoryError
from inspect_ai.util._subprocess import ExecResult

# Slow for the same reason as tests/checkpoint/test_restore_repo.py: the
# binary comes from `resolve_restic`, which downloads it on first use, and
# every test here pays a real `restic init` plus real backup and restore
# invocations. Keep anything that needs neither out of this file so it stays
# in the PR gate (see `_remove_files` in test_sandbox_egress_extract.py).
pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _rootless(rootless_sandbox_dir: None) -> None:
    """Every test here drives ingress through the shell fake (see conftest)."""


PASSWORD = "test-password"
CHUNK = 64 * 1024
CAP = 1 << 30


class _Repos:
    """A real "in-sandbox" restic repo plus an (initially empty) destination.

    ``name`` is the sandbox name: it keys the destination under the shared
    ``restic/sandboxes/`` parent, so two instances built from the same
    ``tmp_path`` model two sandboxes of one sample.
    """

    def __init__(self, tmp_path: Path, restic: Path, name: str = "default") -> None:
        self.restic = restic
        root = tmp_path / name
        root.mkdir()
        self.sandbox_dir = root / "sandbox"
        self.sandbox_dir.mkdir()
        # `ingress_sandbox` runs `<sandbox_dir>/restic`; egress never does.
        (self.sandbox_dir / "restic").symlink_to(restic)
        self.repo = self.sandbox_dir / "repo"
        self.repo.mkdir()
        self.src = root / "capture"
        self.src.mkdir()
        (self.src / "notes.txt").write_text("v1\n")
        self.dest = tmp_path / "sample" / "restic" / "sandboxes" / name
        self.env = LocalShellSandbox()
        self._run("init", "-q")

    def _run(self, *args: str) -> str:
        proc = subprocess.run(
            [str(self.restic), "-r", str(self.repo), *args],
            env={"RESTIC_PASSWORD": PASSWORD, "PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    def backup(self, tag: str | None) -> str:
        """Back up the capture dir into the sandbox repo; return the id."""
        args = ["backup", str(self.src), "--json", "--quiet"]
        if tag is not None:
            args += ["--tag", tag]
        return ResticBackupSummary.from_stdout(self._run(*args)).snapshot_id

    async def egress(self, tag: str, snapshot_id: str, **overrides: Any) -> str:
        kwargs: dict[str, Any] = dict(
            dest_repo=str(self.dest),
            password=PASSWORD,
            host_restic=self.restic,
            tag=tag,
            snapshot_id=snapshot_id,
            max_bytes=CAP,
            chunk_size=CHUNK,
            sandbox_dir=str(self.sandbox_dir),
        )
        kwargs.update(overrides)
        return await egress_sandbox(self.env, **kwargs)

    async def dest_snapshots(self) -> dict[str, list[str]]:
        snaps = await list_snapshots(self.restic, str(self.dest), PASSWORD)
        return {s["id"]: s.get("tags") or [] for s in snaps}

    def dest_files(self) -> set[str]:
        return {
            p.relative_to(self.dest).as_posix()
            for p in self.dest.rglob("*")
            if p.is_file() and p.relative_to(self.dest).parts[0] != "locks"
        }

    def repo_files(self) -> set[str]:
        return {
            p.relative_to(self.repo).as_posix()
            for p in self.repo.rglob("*")
            if p.is_file() and p.relative_to(self.repo).parts[0] != "locks"
        }

    def manifest(self) -> set[str]:
        path = self.sandbox_dir / "egress-manifest.txt"
        return set(path.read_text().split()) if path.exists() else set()


@pytest.fixture
async def repos(tmp_path: Path) -> _Repos:
    return _Repos(tmp_path, await resolve_restic())


async def test_egress_ships_deltas_and_records_host_verified_id(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    assert await repos.egress("ckpt-00001", id1) == id1
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert repos.dest_files() == repos.repo_files()
    assert repos.manifest() == repos.repo_files()

    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    assert await repos.egress("ckpt-00002", id2) == id2
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"], id2: ["ckpt-00002"]}
    assert repos.dest_files() == repos.repo_files()
    # Staging is clean after the phase-2 commit.
    assert not list((repos.sandbox_dir / "staging").glob("egress-*.tar"))
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_empty_diff_after_backup_raises(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")

    async def fake_build(*_args: object, **_kwargs: object) -> _EgressBuild:
        return _EgressBuild(new_files=[], tar_size=0)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress._build_egress_tar",
        new=fake_build,
    ):
        with pytest.raises(EgressVerificationError, match="empty diff"):
            await repos.egress("ckpt-00001", id1)
    assert repos.dest_files() == set()
    assert repos.manifest() == set()


async def test_egress_ships_unrecorded_extra_snapshot_as_orphan(repos: _Repos) -> None:
    """A snapshot no fire reported rides along and is forgotten on resume.

    The host cannot tell a container-planted snapshot from the orphan a
    failed fire leaves (see ``test_egress_recovers_after_failed_transfer``),
    so freshness accepts it: it is not recorded, and orphan discard drops it.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    (repos.src / "notes.txt").write_text("rogue\n")
    rogue = repos.backup(None)  # untagged snapshot the container planted

    assert await repos.egress("ckpt-00002", id2) == id2
    assert await repos.dest_snapshots() == {
        id1: ["ckpt-00001"],
        id2: ["ckpt-00002"],
        rogue: [],
    }

    await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.dest),
        PASSWORD,
        recorded_ids=[id1, id2],
        required_id=id2,
    )
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"], id2: ["ckpt-00002"]}


async def test_egress_rejects_unshipped_reported_id(repos: _Repos) -> None:
    """The reported id must be one of the snapshots this fire landed."""
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    manifest_after_1 = repos.manifest()
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")

    with pytest.raises(EgressVerificationError, match="not among the snapshot"):
        await repos.egress("ckpt-00002", "f" * 64)
    # Rolled back: destination and manifest exactly as after fire 1.
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert repos.dest_files() == files_after_1
    assert repos.manifest() == manifest_after_1
    assert not list(repos.dest.rglob("*.partial"))
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_recovers_after_failed_transfer(repos: _Repos) -> None:
    """A fire that fails between backup and commit does not poison later fires.

    The failed fire's snapshot stays unshipped in the sandbox repo, so the
    retry (which reuses the checkpoint id, hence the tag) ships two
    snapshot files; the retry's own id is the verified one and the other
    is an orphan that resume forgets.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    (repos.src / "notes.txt").write_text("v2\n")
    orphan = repos.backup("ckpt-00002")

    async def failing_copy_out(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("chunk copy failed: transport reset")

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress.copy_out",
        new=failing_copy_out,
    ):
        with pytest.raises(RuntimeError, match="transport reset"):
            await repos.egress("ckpt-00002", orphan)
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}

    id2 = repos.backup("ckpt-00002")  # the retried fire
    assert await repos.egress("ckpt-00002", id2) == id2
    (repos.src / "notes.txt").write_text("v3\n")
    id3 = repos.backup("ckpt-00003")
    assert await repos.egress("ckpt-00003", id3) == id3
    assert await repos.dest_snapshots() == {
        id1: ["ckpt-00001"],
        orphan: ["ckpt-00002"],
        id2: ["ckpt-00002"],
        id3: ["ckpt-00003"],
    }
    assert repos.dest_files() == repos.repo_files()

    forgotten = await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.dest),
        PASSWORD,
        recorded_ids=[id1, id2, id3],
        required_id=id3,
    )
    assert forgotten == ["ckpt-00002"]
    assert set(await repos.dest_snapshots()) == {id1, id2, id3}


async def test_egress_cancelled_during_verification_rolls_back(
    repos: _Repos,
) -> None:
    """Cancellation after extraction still removes this fire's files.

    ``_fire_once`` fans sandboxes out under one task group, so a sibling's
    verification failure cancels this egress mid-``_verify_fresh_snapshot``
    — after the members are already on disk.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    verifying = anyio.Event()

    async def stall(*_args: object, **_kwargs: object) -> str:
        verifying.set()
        await anyio.sleep_forever()
        return ""

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress._verify_fresh_snapshot",
        new=stall,
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(repos.egress, "ckpt-00002", id2)
            await verifying.wait()
            assert repos.dest_files() > files_after_1  # members extracted
            tg.cancel_scope.cancel()

    assert repos.dest_files() == files_after_1
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_rejects_unreadable_tarball(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")

    async def fake_copy_out(*_args: object, dest: Path, **_kwargs: object) -> None:
        dest.write_bytes(b"not a tar archive" * 64)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress.copy_out",
        new=fake_copy_out,
    ):
        with pytest.raises(EgressVerificationError, match="unreadable tarball"):
            await repos.egress("ckpt-00001", id1)
    assert repos.dest_files() == set()
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_sweeps_stale_scratch_files(repos: _Repos) -> None:
    """Residue a hard kill leaves (the scratch tar and copy_out's partial) is swept."""
    id1 = repos.backup("ckpt-00001")
    scratch = repos.dest.parent / ".egress-default"
    scratch.mkdir(parents=True)
    stale_tar = scratch / "ckpt-00000.tar"
    stale_partial = copy_out_partial_path(stale_tar)
    stale_tar.write_bytes(b"residue of a fire killed during extraction")
    stale_partial.write_bytes(b"residue of a fire killed mid-transfer")

    await repos.egress("ckpt-00001", id1)

    assert not stale_tar.exists()
    assert not stale_partial.exists()
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_sweep_spares_sibling_sandbox_in_flight_transfer(
    tmp_path: Path,
) -> None:
    """One sandbox's residue sweep never touches a concurrently egressing sibling.

    ``_fire_once`` egresses every sandbox concurrently and sandbox names
    may prefix one another (``a`` / ``a-b``), so ``a``'s sweep runs while
    ``a-b`` has its scratch tar or ``copy_out`` partial on disk.
    """
    restic = await resolve_restic()
    a = _Repos(tmp_path, restic, name="a")
    ab = _Repos(tmp_path, restic, name="a-b")
    id_a = a.backup("ckpt-00001")
    id_ab = ab.backup("ckpt-00001")
    ab_mid_transfer = anyio.Event()
    a_done = anyio.Event()

    async def copy_out_stalled_for_ab(
        env: LocalShellSandbox, *, dest: Path, label: str, **kwargs: Any
    ) -> None:
        if str(ab.dest) in label:
            partial = copy_out_partial_path(dest)
            partial.write_bytes(b"a-b's transfer, in flight")
            dest.write_bytes(b"a-b's landed tar, awaiting extraction")
            ab_mid_transfer.set()
            await a_done.wait()
            assert partial.exists() and dest.exists()
            partial.unlink()
            dest.unlink()
        await copy_out(env, dest=dest, label=label, **kwargs)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress.copy_out",
        new=copy_out_stalled_for_ab,
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(ab.egress, "ckpt-00001", id_ab)
            await ab_mid_transfer.wait()
            assert await a.egress("ckpt-00001", id_a) == id_a
            a_done.set()

    assert await a.dest_snapshots() == {id_a: ["ckpt-00001"]}
    assert await ab.dest_snapshots() == {id_ab: ["ckpt-00001"]}
    assert not list(a.dest.parent.glob(".egress-*"))


async def test_egress_rejects_replayed_snapshot_id(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")

    with pytest.raises(EgressVerificationError, match="replayed"):
        await repos.egress("ckpt-00002", id1)
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}


async def test_egress_rejects_snapshot_with_foreign_tag(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00099")

    with pytest.raises(EgressVerificationError, match="carries tags"):
        await repos.egress("ckpt-00002", id2)
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert repos.dest_files() == files_after_1


async def test_egress_rejects_malformed_snapshot_id(repos: _Repos) -> None:
    repos.backup("ckpt-00001")
    with pytest.raises(EgressVerificationError, match="malformed"):
        await repos.egress("ckpt-00001", "latest")


async def test_egress_refuses_oversized_delta_before_tarring(repos: _Repos) -> None:
    """A delta already over the cap is refused in-sandbox, with no tar built."""
    id1 = repos.backup("ckpt-00001")
    with pytest.raises(RuntimeError, match="nothing was tarred"):
        await repos.egress("ckpt-00001", id1, max_bytes=512)
    assert not list((repos.sandbox_dir / "staging").glob("egress-*.tar"))
    assert repos.dest_files() == set()
    assert not list(repos.dest.parent.glob(".egress-*"))
    assert repos.manifest() == set()


async def test_egress_enforces_transfer_cap(repos: _Repos) -> None:
    """The cap binds on the tar's true size, not just the summed file sizes."""
    id1 = repos.backup("ckpt-00001")
    # Headers and padding make the tar larger than its members: a cap
    # exactly at the members' total passes the pre-check and lets the
    # copy-out refuse the tar.
    members_total = sum((repos.repo / f).stat().st_size for f in repos.repo_files())
    with pytest.raises(RuntimeError, match="exceeds the max_sandbox_snapshot_bytes"):
        await repos.egress("ckpt-00001", id1, max_bytes=members_total)
    assert list((repos.sandbox_dir / "staging").glob("egress-*.tar"))
    assert repos.dest_files() == set()
    assert not list(repos.dest.parent.glob(".egress-*"))
    assert repos.manifest() == set()


async def test_egress_recovers_after_failed_commit(repos: _Repos) -> None:
    """Files re-shipped after a lost phase-2 commit are accepted as no-ops."""
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    # Simulate the phase-2 commit never landing: the manifest is empty.
    (repos.sandbox_dir / "egress-manifest.txt").write_text("")

    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    assert await repos.egress("ckpt-00002", id2) == id2
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"], id2: ["ckpt-00002"]}
    assert repos.dest_files() == repos.repo_files()
    assert repos.manifest() == repos.repo_files()


async def test_egress_reshipped_config_is_never_rewritten(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    dest_config = repos.dest / "config"
    before = dest_config.stat().st_mtime_ns
    # Force the sandbox to re-list config (as a lost phase-2 commit would):
    # the identical bytes are accepted as a no-op, the file untouched.
    manifest = repos.sandbox_dir / "egress-manifest.txt"
    manifest.write_text("\n".join(sorted(repos.manifest() - {"config"})) + "\n")
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")

    assert await repos.egress("ckpt-00002", id2) == id2
    assert dest_config.stat().st_mtime_ns == before
    assert "config" in repos.manifest()


_LAYOUT_ORDER = ["keys", "config", "data", "index", "snapshots"]


async def test_egress_first_cycle_writes_keys_before_config(repos: _Repos) -> None:
    """The first-cycle sentinel (``config``) lands after its key; snapshots last.

    A hard kill between two renames must leave the destination either
    still first-cycle (re-bootstrapped next fire) or openable; a repo
    with ``config`` and no ``keys/*`` is neither.
    """
    id1 = repos.backup("ckpt-00001")
    order: list[str] = []

    def spy(src: IO[bytes], dest_repo: str, name: str, label: str) -> None:
        order.append(name)
        _write_member(src, dest_repo, name, label)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress._write_member",
        new=spy,
    ):
        await repos.egress("ckpt-00001", id1)

    kinds = [name.split("/")[0] for name in order]
    assert kinds[:2] == ["keys", "config"]
    assert kinds[-1] == "snapshots"
    assert kinds == sorted(kinds, key=_LAYOUT_ORDER.index)


# --- resume side ------------------------------------------------------


async def test_forget_unrecorded_snapshots_keeps_only_recorded(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    (repos.src / "notes.txt").write_text("v3\n")
    repos.backup("ckpt-00003")  # captured, never committed
    (repos.src / "notes.txt").write_text("rogue\n")
    repos.backup(None)  # planted by the container

    forgotten = await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.repo),
        PASSWORD,
        recorded_ids=[id1, id2],
        required_id=id2,
    )

    assert sorted(forgotten) == ["ckpt-00003"]
    remaining = {
        s["id"] for s in await list_snapshots(repos.restic, str(repos.repo), PASSWORD)
    }
    assert remaining == {id1, id2}


async def test_forget_unrecorded_snapshots_clears_inherited_locks(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    repos.backup("ckpt-00002")
    lock = repos.repo / "locks" / ("a" * 64)
    lock.parent.mkdir(exist_ok=True)
    lock.write_bytes(b"lock residue copied from a killed attempt")

    await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.repo),
        PASSWORD,
        recorded_ids=[id1],
        required_id=id1,
    )

    assert not lock.exists()
    assert {
        s["id"] for s in await list_snapshots(repos.restic, str(repos.repo), PASSWORD)
    } == {id1}


async def test_forget_unrecorded_snapshots_requires_latest_recorded(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")

    with pytest.raises(RuntimeError, match="does not contain snapshot"):
        await forget_unrecorded_snapshots(
            repos.restic,
            str(repos.repo),
            PASSWORD,
            recorded_ids=[id1, "f" * 64],
            required_id="f" * 64,
        )
    # Nothing was forgotten before the check failed.
    assert len(await list_snapshots(repos.restic, str(repos.repo), PASSWORD)) == 2


async def test_forget_unrecorded_snapshots_rejects_malformed_ids(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    for bad in ("", "latest", "ABCDEF01"):
        with pytest.raises(RuntimeError, match="malformed"):
            await forget_unrecorded_snapshots(
                repos.restic,
                str(repos.repo),
                PASSWORD,
                recorded_ids=[id1, bad],
                required_id=id1,
            )
    assert len(await list_snapshots(repos.restic, str(repos.repo), PASSWORD)) == 1


class _FreshSandbox:
    """The resume side: an adopted host repo and a fresh in-sandbox tool dir."""

    def __init__(self, repos: _Repos, tmp_path: Path) -> None:
        self.repos = repos
        self.host_repo = tmp_path / "adopted"
        shutil.copytree(repos.repo, self.host_repo)
        self.sandbox_dir = tmp_path / "fresh-sandbox"
        # Ingress adopts the tool dir only in the private mode it requires.
        self.sandbox_dir.mkdir(mode=0o700)
        (self.sandbox_dir / "restic").symlink_to(repos.restic)
        self.env = _CountingSandbox()

    async def ingress(self, snapshot_id: str, *roots: Path) -> None:
        await ingress_sandbox(
            self.env,
            str(self.host_repo),
            PASSWORD,
            snapshot_id=snapshot_id,
            roots=RestoreRoots.from_include(
                [str(r) for r in (roots or (self.repos.src,))], label="test"
            ),
            host_restic=self.repos.restic,
            sandbox_dir=str(self.sandbox_dir),
        )


class _CountingSandbox(LocalShellSandbox):
    """Counts ``exec`` calls: a refused ingress must run none."""

    def __init__(self) -> None:
        super().__init__()
        self.execs = 0

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.execs += 1
        return await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )


async def test_ingress_restores_recorded_snapshot_not_latest(
    repos: _Repos, tmp_path: Path
) -> None:
    id1 = repos.backup("ckpt-00001")
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")
    fresh = _FreshSandbox(repos, tmp_path)

    await fresh.ingress(id1)

    # The recorded snapshot's file is back at its absolute path.
    assert (repos.src / "notes.txt").read_text() == "v1\n"
    # The manifest is reseeded with every inherited repo file.
    seeded = set((fresh.sandbox_dir / "egress-manifest.txt").read_text().split())
    assert seeded == {
        p.relative_to(fresh.host_repo).as_posix()
        for p in fresh.host_repo.rglob("*")
        if p.is_file() and p.relative_to(fresh.host_repo).parts[0] != "locks"
    }


async def test_ingress_rejects_malformed_recorded_id(
    repos: _Repos, tmp_path: Path
) -> None:
    fresh = _FreshSandbox(repos, tmp_path)
    with pytest.raises(RuntimeError, match="malformed"):
        await fresh.ingress("latest; rm -rf /")
    assert fresh.env.execs == 0


@pytest.mark.slow
async def test_ingress_restores_symlinks_and_leaves_ancestors_alone(
    repos: _Repos, tmp_path: Path
) -> None:
    """A normal home-dir snapshot round-trips: nested dirs, symlinks, modes.

    Directory sticky and setgid bits (a drop dir, a ``g+s`` shared dir)
    are legitimate content and come back as recorded. The capture root's
    parent is an ancestor node in the snapshot; the per-root restore
    form never writes it, so a mode change made after capture survives
    the restore (``--target /`` would have reset it to the recorded
    mode).
    """
    src = repos.src
    (src / "sub").mkdir()
    (src / "sub" / "deep.txt").write_text("deep\n")
    (src / "link").symlink_to("notes.txt")
    (src / "abs-link").symlink_to("/etc/hostname")
    (src / "script.sh").write_text("#!/bin/sh\n")
    (src / "script.sh").chmod(0o755)
    (src / "private").mkdir()
    (src / "private").chmod(0o700)
    (src / "drop").mkdir()
    (src / "drop").chmod(0o1777)
    (src / "shared").mkdir()
    (src / "shared").chmod(0o2775)
    parent = src.parent
    parent.chmod(0o750)
    id1 = repos.backup("ckpt-00001")
    fresh = _FreshSandbox(repos, tmp_path)
    shutil.rmtree(src)
    src.mkdir()
    (src / "post-capture.txt").write_text("fresh sandbox file\n")
    parent.chmod(0o755)

    await fresh.ingress(id1)

    assert (src / "notes.txt").read_text() == "v1\n"
    assert (src / "sub" / "deep.txt").read_text() == "deep\n"
    assert os.readlink(src / "link") == "notes.txt"
    assert os.readlink(src / "abs-link") == "/etc/hostname"
    assert (src / "script.sh").stat().st_mode & 0o777 == 0o755
    assert (src / "private").stat().st_mode & 0o777 == 0o700
    assert (src / "drop").stat().st_mode & 0o7777 == 0o1777
    assert (src / "shared").stat().st_mode & 0o7777 == 0o2775
    # Files the fresh sandbox had are left alone, as before.
    assert (src / "post-capture.txt").exists()
    # The ancestor keeps its post-capture mode: nothing above the root was written.
    assert parent.stat().st_mode & 0o777 == 0o755


def _hostile_snapshots() -> dict[str, tuple[Callable[[_Repos, Path], list[str]], str]]:
    """Name → (prepare capture, substring the refusal must contain).

    ``prepare`` mutates the capture tree and returns the paths to back
    up; the second element is the offending path (or its diagnostic) the
    error must name.
    """

    def outside(repos: _Repos, other: Path) -> list[str]:
        other.mkdir()
        (other / "planted.txt").write_text("planted\n")
        return [str(repos.src), str(other)]

    def etc(repos: _Repos, other: Path) -> list[str]:
        # A file every host running the tests has (Linux and macOS).
        return [str(repos.src), "/etc/hosts"]

    def setuid(repos: _Repos, other: Path) -> list[str]:
        (repos.src / "sh").write_text("#!/bin/sh\n")
        (repos.src / "sh").chmod(0o4755)
        return [str(repos.src)]

    def setgid(repos: _Repos, other: Path) -> list[str]:
        (repos.src / "gsh").write_text("#!/bin/sh\n")
        (repos.src / "gsh").chmod(0o2755)
        return [str(repos.src)]

    def fifo(repos: _Repos, other: Path) -> list[str]:
        os.mkfifo(repos.src / "pipe")
        return [str(repos.src)]

    # Restic lists a source's ancestors first, so the node named is the
    # first one outside the scope: the planted dir / `/etc` itself.
    return {
        "outside_root": (outside, "/other lies outside"),
        "etc_hosts": (etc, "/etc lies outside"),
        "setuid_under_root": (setuid, "sh is a regular file with mode 4755"),
        "setgid_file_under_root": (setgid, "gsh is a regular file with mode 2755"),
        "fifo_under_root": (fifo, "pipe is a fifo"),
    }


@pytest.mark.slow
@pytest.mark.parametrize("violation", sorted(_hostile_snapshots()))
async def test_ingress_refuses_snapshot_reaching_outside_scope(
    repos: _Repos, tmp_path: Path, violation: str
) -> None:
    """A crafted snapshot is refused on the host before any exec, naming the path.

    The repo is otherwise valid and the snapshot id is the recorded one;
    only the listing check stands between it and a root ``restic
    restore`` in the sandbox.
    """
    prepare, expected = _hostile_snapshots()[violation]
    other = tmp_path / "default" / "other"
    sources = prepare(repos, other)
    proc = subprocess.run(
        [str(repos.restic), "-r", str(repos.repo), "backup", *sources, "--json", "-q"],
        env={"RESTIC_PASSWORD": PASSWORD, "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=True,
    )
    snapshot_id = ResticBackupSummary.from_stdout(proc.stdout).snapshot_id
    fresh = _FreshSandbox(repos, tmp_path)
    (repos.src / "notes.txt").write_text("fresh sandbox\n")

    with pytest.raises(RestoreScopeError, match=re.escape(expected)):
        await fresh.ingress(snapshot_id)

    assert fresh.env.execs == 0
    assert (repos.src / "notes.txt").read_text() == "fresh sandbox\n"
    assert not (fresh.sandbox_dir / "repo").exists()


@pytest.mark.slow
async def test_ingress_never_writes_through_an_image_symlink(
    repos: _Repos, tmp_path: Path
) -> None:
    """A symlink the fresh image ships under the root is deleted before restic writes.

    The snapshot holds a directory ``l`` with a file; the fresh sandbox
    has ``l`` as a symlink to a directory outside the root. The core's
    pre-``setup`` pass (run here as ``_hydrate_sandbox`` would) deletes
    the link, and the restore leaves that directory untouched and puts
    the file in a real ``l`` (restic 0.18 replaces the mismatched node
    itself; the pass makes the invariant independent of that). A link
    the snapshot never held is gone afterwards.
    """
    src = repos.src
    (src / "l").mkdir()
    (src / "l" / "shadow").write_text("captured\n")
    id1 = repos.backup("ckpt-00001")
    fresh = _FreshSandbox(repos, tmp_path)
    shutil.rmtree(src)
    src.mkdir()
    outside = src.parent / "etc"
    outside.mkdir()
    (outside / "passwd").write_text("root:x:0:0\n")
    (src / "l").symlink_to("../etc")
    (src / "stale").symlink_to("/etc")

    await remove_existing_symlinks(
        fresh.env, RestoreRoots.from_include([str(src)], label="test"), label="test"
    )
    await fresh.ingress(id1)

    assert not (outside / "shadow").exists()
    assert (src / "l").is_dir() and not (src / "l").is_symlink()
    assert (src / "l" / "shadow").read_text() == "captured\n"
    assert not (src / "stale").is_symlink()
    assert (src / "notes.txt").read_text() == "v1\n"


@pytest.mark.slow
async def test_ingress_restores_root_with_glob_characters_literally(
    repos: _Repos, tmp_path: Path
) -> None:
    """A root name holding glob metacharacters selects exactly itself."""
    parent = repos.src.parent
    root = parent / "da[t]a*?"
    decoy = parent / "data"
    root.mkdir()
    decoy.mkdir()
    (root / "keep.txt").write_text("keep\n")
    (decoy / "decoy.txt").write_text("decoy\n")
    proc = subprocess.run(
        [str(repos.restic), "-r", str(repos.repo), "backup", str(root), "--json", "-q"],
        env={"RESTIC_PASSWORD": PASSWORD, "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=True,
    )
    snapshot_id = ResticBackupSummary.from_stdout(proc.stdout).snapshot_id
    fresh = _FreshSandbox(repos, tmp_path)
    shutil.rmtree(root)
    shutil.rmtree(decoy)

    await fresh.ingress(snapshot_id, root)

    assert (root / "keep.txt").read_text() == "keep\n"
    assert not decoy.exists()


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("setfacl") is None, reason="needs setfacl")
async def test_ingress_restores_only_user_xattrs(repos: _Repos, tmp_path: Path) -> None:
    """A recorded ACL (``system.posix_acl_access``) is not reapplied; ``user.*`` is.

    The listing cannot see extended attributes, and restic as root would
    otherwise reapply a recorded ``security.capability`` the same way it
    reapplies this ACL.
    """
    if sys.platform != "linux":
        pytest.skip("Linux extended attributes")
    target = repos.src / "notes.txt"
    subprocess.run(["setfacl", "-m", "u:nobody:r", str(target)], check=True)
    os.setxattr(target, "user.note", b"kept")
    assert "system.posix_acl_access" in os.listxattr(target)
    id1 = repos.backup("ckpt-00001")
    fresh = _FreshSandbox(repos, tmp_path)
    target.unlink()

    await fresh.ingress(id1)

    assert target.read_text() == "v1\n"
    assert os.listxattr(target) == ["user.note"]


@pytest.mark.slow
async def test_ingress_reports_unknown_snapshot_with_restic_error(
    repos: _Repos, tmp_path: Path
) -> None:
    repos.backup("ckpt-00001")
    fresh = _FreshSandbox(repos, tmp_path)
    with pytest.raises(RuntimeError, match="restic ls failed"):
        await fresh.ingress("f" * 64)
    assert fresh.env.execs == 0


@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform != "linux",
    reason="the directory verification script needs GNU/BusyBox stat",
)
async def test_ingress_refuses_untrusted_sandbox_dir(
    repos: _Repos, tmp_path: Path
) -> None:
    """A tool dir that fails the root-only contract is refused before the repo lands.

    The host-side scope check passes (it is the recorded snapshot), so the
    directory check is the first and only exec: nothing is extracted into
    the wider-than-0700 directory and no restore runs.
    """
    id1 = repos.backup("ckpt-00001")
    fresh = _FreshSandbox(repos, tmp_path)
    fresh.sandbox_dir.chmod(0o755)
    (repos.src / "notes.txt").unlink()

    with pytest.raises(FrameworkDirectoryError, match="mode 755"):
        await fresh.ingress(id1)
    assert fresh.env.execs == 1
    assert not (fresh.sandbox_dir / "repo").exists()
    assert not (repos.src / "notes.txt").exists()


@pytest.mark.slow
async def test_ingress_refuses_snapshot_missing_a_root(
    repos: _Repos, tmp_path: Path
) -> None:
    id1 = repos.backup("ckpt-00001")
    fresh = _FreshSandbox(repos, tmp_path)
    other = tmp_path / "default" / "other"
    with pytest.raises(RestoreScopeError, match=rf"no node at capture root.*{other}"):
        await fresh.ingress(id1, repos.src, other)
    assert fresh.env.execs == 0


async def test_restic_strategy_rejects_recorded_roots_mismatch(tmp_path: Path) -> None:
    """The strategy refuses a record captured from other roots before touching anything."""
    from inspect_ai.util._checkpoint._snapshot import ResticIncrementalStrategy
    from inspect_ai.util._checkpoint._snapshot.types import SnapshotContext
    from inspect_ai.util._checkpoint.sandbox_paths import SandboxBackupPaths

    env = _CountingSandbox()
    ctx = SnapshotContext(
        sandbox_name="default",
        storage_dir=str(tmp_path / "nowhere"),
        storage_subpath="restic/sandboxes/default",
        secret=PASSWORD,
        resuming=True,
    )
    details = SnapshotDetails.model_validate(
        dict(snapshot_id="a" * 64, size_bytes=1, duration_ms=1, roots=["/data"])
    )
    with pytest.raises(RestoreScopeError, match=r"\['/data'\].*\['/home/agent'\]"):
        await ResticIncrementalStrategy().restore(
            env, SandboxBackupPaths(include=["/home/agent"]), details, ctx
        )
    assert env.execs == 0


# --- listing streamer (fake restic) ------------------------------------
#
# `walk_snapshot_nodes` streams `restic ls --json` off the process pipe.
# Its failure paths need only a process that writes the right bytes, so
# a shell script standing in for restic covers them in the fast suite
# without Docker or the restic download.

_FAKE_ID = "c" * 64
_SNAPSHOT_RECORD = json.dumps({"message_type": "snapshot", "id": _FAKE_ID})


def _node_record(path: str, kind: str = "file") -> str:
    return json.dumps({"message_type": "node", "path": path, "type": kind, "mode": 420})


def _fake_restic(tmp_path: Path, body: str) -> Path:
    """An executable ``sh`` script that ignores its arguments and runs ``body``."""
    script = tmp_path / "fake-restic"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


async def _walk(restic: Path, visit: Callable[[dict[str, Any]], None]) -> str:
    return await walk_snapshot_nodes(restic, "repo", PASSWORD, _FAKE_ID, visit)


async def test_walk_snapshot_nodes_kills_restic_on_a_rejected_node(
    tmp_path: Path,
) -> None:
    # An endless listing whose second node is out of scope: the walker's
    # error propagates at once (not wrapped in an ExceptionGroup) and the
    # still-writing process is killed rather than drained.
    pid_file = tmp_path / "pid"
    restic = _fake_restic(
        tmp_path,
        f"echo $$ > {pid_file}\n"
        f"echo '{_SNAPSHOT_RECORD}'\n"
        f"echo '{_node_record('/home/user', 'dir')}'\n"
        f"echo '{_node_record('/etc/passwd')}'\n"
        f"while :; do echo '{_node_record('/home/user/x')}'; done",
    )
    walk = RestoreRoots.from_include(["/home/user"], label="test").walker(label="test")
    visited: list[str] = []

    def visit(record: dict[str, Any]) -> None:
        visited.append(record["path"])
        walk.visit(restic_node(record, label="test"))

    with anyio.fail_after(30):
        with pytest.raises(RestoreScopeError, match="/etc/passwd"):
            await _walk(restic, visit)
    assert visited == ["/home/user", "/etc/passwd"]
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_walk_snapshot_nodes_reports_restic_stderr_on_failure(
    tmp_path: Path,
) -> None:
    restic = _fake_restic(
        tmp_path, "echo 'Fatal: unable to open repository' >&2\nexit 1"
    )
    with pytest.raises(RuntimeError, match=r"exit 1.*unable to open repository"):
        await _walk(restic, lambda _record: None)


@pytest.mark.parametrize("line", ["Fatal: not json", "[1, 2]"])
async def test_walk_snapshot_nodes_labels_a_non_json_listing_line(
    tmp_path: Path, line: str
) -> None:
    """A stdout line that is not a JSON object fails with the repo named, not a bare decode error."""
    restic = _fake_restic(tmp_path, f"echo '{_SNAPSHOT_RECORD}'\necho '{line}'")
    with pytest.raises(RuntimeError, match=rf"restic ls on repo: .*{re.escape(line)}"):
        await _walk(restic, lambda _record: None)


async def test_walk_snapshot_nodes_requires_a_snapshot_record(tmp_path: Path) -> None:
    restic = _fake_restic(tmp_path, f"echo '{_node_record('/home/user', 'dir')}'")
    visited: list[str] = []
    with pytest.raises(RuntimeError, match="no well-formed snapshot record"):
        await _walk(restic, lambda record: visited.append(record["path"]))
    assert visited == ["/home/user"]


async def test_walk_snapshot_nodes_parses_an_unterminated_final_line(
    tmp_path: Path,
) -> None:
    restic = _fake_restic(
        tmp_path,
        f"echo '{_SNAPSHOT_RECORD}'\nprintf '%s' '{_node_record('/home/user/x')}'",
    )
    visited: list[str] = []
    full_id = await _walk(restic, lambda record: visited.append(record["path"]))
    assert full_id == _FAKE_ID
    assert visited == ["/home/user/x"]


async def test_walk_snapshot_nodes_refuses_an_oversized_record(tmp_path: Path) -> None:
    # A 2 MiB "path" exceeds the per-record cap; refused with the size
    # message rather than buffered.
    head = json.dumps({"message_type": "node", "type": "file"})[:-1] + ',"path":"/'
    restic = _fake_restic(
        tmp_path,
        f"echo '{_SNAPSHOT_RECORD}'\n"
        f"printf '%s' '{head}'\n"
        "head -c 2097152 /dev/zero | tr '\\0' a\n"
        "echo '\"}'",
    )
    with pytest.raises(RuntimeError, match="exceeds .* bytes"):
        await _walk(restic, lambda _record: None)
