"""Sandbox restic egress/ingress against a real restic binary.

Drives ``egress_sandbox`` end to end with the ``LocalShellSandbox`` fake:
the "in-sandbox" repo is a real restic repo under a temp dir that real
``restic backup`` invocations write into, the egress shell (find, comm,
tar, dd) runs on the host, and the host-side checks run against the
destination repo with the same binary. Covers the host-side truth
checks the egress protocol makes: a fire that captured nothing raises,
an injected extra snapshot fails the freshness check and leaves the
destination unchanged, a replayed id or foreign tag is rejected, the
transfer cap binds, and resume-side orphan discard keeps exactly the
recorded snapshots and restores the recorded id.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anyio
import pytest
from test_helpers.local_shell_sandbox import LocalShellSandbox

from inspect_ai.util._checkpoint._copy import copy_out_partial_path
from inspect_ai.util._checkpoint._repo_ops import (
    forget_unrecorded_snapshots,
    list_snapshots,
)
from inspect_ai.util._checkpoint._sandbox_restic.egress import (
    EgressVerificationError,
    _EgressBuild,
    egress_sandbox,
    ingress_sandbox,
)
from inspect_ai.util._restic import ResticBackupSummary, resolve_restic

PASSWORD = "test-password"
CHUNK = 64 * 1024
CAP = 1 << 30


class _Repos:
    """A real "in-sandbox" restic repo plus an (initially empty) destination."""

    def __init__(self, tmp_path: Path, restic: Path) -> None:
        self.restic = restic
        self.sandbox_dir = tmp_path / "sandbox"
        self.sandbox_dir.mkdir()
        # `ingress_sandbox` runs `<sandbox_dir>/restic`; egress never does.
        (self.sandbox_dir / "restic").symlink_to(restic)
        self.repo = self.sandbox_dir / "repo"
        self.repo.mkdir()
        self.src = tmp_path / "capture"
        self.src.mkdir()
        (self.src / "notes.txt").write_text("v1\n")
        self.dest = tmp_path / "sample" / "restic" / "sandboxes" / "default"
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
        return {s["id"]: s["tags"] for s in snaps}

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


async def test_egress_rejects_injected_extra_snapshot(repos: _Repos) -> None:
    """A tar carrying a snapshot no backup of this fire produced fails freshness."""
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    manifest_after_1 = repos.manifest()

    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    (repos.src / "notes.txt").write_text("rogue\n")
    repos.backup(None)  # untagged snapshot the container planted

    with pytest.raises(EgressVerificationError, match="exactly one snapshot"):
        await repos.egress("ckpt-00002", id2)
    # Rolled back: destination and manifest exactly as after fire 1.
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert repos.dest_files() == files_after_1
    assert repos.manifest() == manifest_after_1
    assert not list(repos.dest.rglob("*.partial"))
    assert not list(repos.dest.parent.glob(".egress-*"))


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
    repos.dest.parent.mkdir(parents=True, exist_ok=True)
    stale_tar = repos.dest.parent / ".egress-default-ckpt-00000.tar"
    stale_partial = copy_out_partial_path(stale_tar)
    stale_tar.write_bytes(b"residue of a fire killed during extraction")
    stale_partial.write_bytes(b"residue of a fire killed mid-transfer")

    await repos.egress("ckpt-00001", id1)

    assert not stale_tar.exists()
    assert not stale_partial.exists()
    assert not list(repos.dest.parent.glob(".egress-*"))
    assert not list(repos.dest.parent.glob("..egress-*"))


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


async def test_egress_enforces_transfer_cap(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    with pytest.raises(RuntimeError, match="max_sandbox_snapshot_bytes"):
        await repos.egress("ckpt-00001", id1, max_bytes=512)
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


async def test_ingress_restores_recorded_snapshot_not_latest(
    repos: _Repos, tmp_path: Path
) -> None:
    id1 = repos.backup("ckpt-00001")
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")
    # Adopt the sandbox repo as the host-side copy a resume would ingress.
    host_repo = tmp_path / "adopted"
    shutil.copytree(repos.repo, host_repo)
    fresh_sandbox = tmp_path / "fresh-sandbox"
    fresh_sandbox.mkdir()
    (fresh_sandbox / "restic").symlink_to(repos.restic)

    await ingress_sandbox(
        repos.env,
        str(host_repo),
        PASSWORD,
        snapshot_id=id1,
        sandbox_dir=str(fresh_sandbox),
    )

    # `restic restore --target /` puts the file back at its absolute path.
    assert (repos.src / "notes.txt").read_text() == "v1\n"
    # The manifest is reseeded with every inherited repo file.
    seeded = set((fresh_sandbox / "egress-manifest.txt").read_text().split())
    assert seeded == {
        p.relative_to(host_repo).as_posix()
        for p in host_repo.rglob("*")
        if p.is_file() and p.relative_to(host_repo).parts[0] != "locks"
    }


async def test_ingress_rejects_malformed_recorded_id(
    repos: _Repos, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="malformed"):
        await ingress_sandbox(
            repos.env,
            str(repos.repo),
            PASSWORD,
            snapshot_id="latest; rm -rf /",
            sandbox_dir=str(tmp_path / "fresh"),
        )
