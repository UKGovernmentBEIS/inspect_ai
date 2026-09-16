"""Harness: hard-kill a real sandbox egress at a chosen publication boundary.

Run as a script by ``test_sandbox_egress_restic.py``'s kill tests::

    python egress_kill_harness.py <workdir> <boundary>

It builds a real per-sandbox restic repo pair (``LocalShellSandbox`` + the
real restic binary, no Docker), commits checkpoint A, then runs checkpoint
B's egress with a hook that ``SIGKILL``s this process at ``<boundary>``:

- ``validation``      — during ``restic check``/``ls`` of the view, before any
  file is merged into the accepted repo.
- ``after_packs``     — after the packs are linked, before indexes.
- ``after_indexes``   — after the indexes are linked, before snapshots.
- ``after_snapshots`` — after the snapshot files are linked (merge complete),
  before the fire returns and its checkpoint file is written.
- ``first_cycle``     — during the *first* fire's merge, after the key is
  linked but before ``config`` (no prior A).
- ``first_cycle_after_config`` — during the *first* fire's merge, after the
  key and ``config`` are linked but before any data (an initialized but empty
  repository; no prior A).

A real ``SIGKILL`` runs no ``finally`` cleanup, so the on-disk state is
exactly what the boundary left. The parent process asserts that the earlier
checkpoint still restores and that a subsequent fire recovers. The harness is
also imported by the parent, which calls :func:`recover` in-process to run
that subsequent fire against the killed repo.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from test_helpers.local_shell_sandbox import LocalShellSandbox

import inspect_ai.util._checkpoint._sandbox_restic.egress as egress
from inspect_ai._util import asyncfiles
from inspect_ai.util._checkpoint._sandbox_restic.egress import egress_sandbox
from inspect_ai.util._restic import ResticBackupSummary, resolve_restic

PASSWORD = "test-password"
CAP = 1 << 30
NO_LINKS_ENV = "EGRESS_KILL_NO_LINKS"
"""Set in the child's environment to run the fire without hard links."""

# boundary name -> the highest merge rank to link before the kill fires
# (see egress._merge_rank: keys 1, config 2, data 3, index 4, snapshots 5).
_MERGE_KILL_RANK = {
    "first_cycle": 1,
    "first_cycle_after_config": 2,
    "after_packs": 3,
    "after_indexes": 4,
    "after_snapshots": 5,
}


@dataclass
class _State:
    restic: Path
    sandbox_dir: Path
    repo: Path
    src: Path
    dest: Path
    env: LocalShellSandbox


def _restic_env() -> dict[str, str]:
    return {"RESTIC_PASSWORD": PASSWORD, "PATH": os.environ["PATH"]}


async def _setup(workdir: Path, restic: Path) -> _State:
    sandbox_dir = workdir / "sandbox"
    sandbox_dir.mkdir(parents=True)
    (sandbox_dir / "restic").symlink_to(restic)
    repo = sandbox_dir / "repo"
    repo.mkdir()
    src = workdir / "capture"
    src.mkdir()
    (src / "notes.txt").write_text("v1\n")
    dest = workdir / "sample" / "restic" / "sandboxes" / "default"
    subprocess.run(
        [str(restic), "-r", str(repo), "init", "-q"],
        env=_restic_env(),
        check=True,
        capture_output=True,
    )
    return _State(restic, sandbox_dir, repo, src, dest, LocalShellSandbox())


def _backup(state: _State, tag: str, content: str) -> str:
    (state.src / "notes.txt").write_text(content)
    proc = subprocess.run(
        [
            str(state.restic),
            "-r",
            str(state.repo),
            "backup",
            str(state.src),
            "--json",
            "--quiet",
            "--tag",
            tag,
        ],
        env=_restic_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    return ResticBackupSummary.from_stdout(proc.stdout).snapshot_id


async def _egress(state: _State, tag: str, snapshot_id: str) -> str:
    return await egress_sandbox(
        state.env,
        dest_repo=str(state.dest),
        password=PASSWORD,
        host_restic=state.restic,
        tag=tag,
        snapshot_id=snapshot_id,
        max_bytes=CAP,
        sandbox_dir=str(state.sandbox_dir),
    )


def _install_validation_kill() -> None:
    async def _kill(*_a: Any, **_k: Any) -> None:
        os.kill(os.getpid(), signal.SIGKILL)

    egress._run_view_restic = _kill


def _install_merge_kill(boundary: str) -> None:
    target = _MERGE_KILL_RANK[boundary]
    real_merge = egress._merge_into_repo
    real_publish = egress._publish_into

    def wrapped_merge(dest_repo: str, staging: Path, written: Any) -> None:
        ordered = sorted(written, key=lambda n: (egress._merge_rank(n), n))
        kill_after = sum(1 for n in ordered if egress._merge_rank(n) <= target)
        assert kill_after >= 1, f"nothing to link at or below rank {target}"
        counter = {"n": 0}

        def counting(src: Path, dst: Path) -> None:
            real_publish(src, dst)
            counter["n"] += 1
            if counter["n"] >= kill_after:
                os.kill(os.getpid(), signal.SIGKILL)

        egress._publish_into = counting
        real_merge(dest_repo, staging, written)

    egress._merge_into_repo = wrapped_merge


def _no_link(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
    """Stand in for ``os.link`` on a filesystem without hard links."""
    raise OSError(errno.EPERM, "Operation not permitted (no hard links)")


def _write_info(workdir: Path, state: _State, id_a: str | None) -> None:
    (workdir / "info.json").write_text(
        json.dumps(
            {
                "restic": str(state.restic),
                "sandbox_dir": str(state.sandbox_dir),
                "repo": str(state.repo),
                "src": str(state.src),
                "dest": str(state.dest),
                "id_a": id_a,
            }
        )
    )


def _reopen(info: dict[str, str]) -> _State:
    return _State(
        restic=Path(info["restic"]),
        sandbox_dir=Path(info["sandbox_dir"]),
        repo=Path(info["repo"]),
        src=Path(info["src"]),
        dest=Path(info["dest"]),
        env=LocalShellSandbox(),
    )


async def _run(workdir: Path, boundary: str) -> None:
    fs = asyncfiles.AsyncFilesystem()
    asyncfiles._current_async_fs.set(fs)
    if os.environ.get(NO_LINKS_ENV):
        # Model a destination filesystem that refuses hard links, so the
        # kill lands on the copy-and-rename publication path instead.
        os.link = _no_link
    restic = await resolve_restic()
    state = await _setup(workdir, restic)
    if boundary.startswith("first_cycle"):
        _write_info(workdir, state, None)
        id1 = _backup(state, "ckpt-00001", "v1\n")
        _install_merge_kill(boundary)
        await _egress(state, "ckpt-00001", id1)
    else:
        id_a = await _egress(state, "ckpt-00001", _backup(state, "ckpt-00001", "v1\n"))
        _write_info(workdir, state, id_a)
        id_b = _backup(state, "ckpt-00002", "v2\n")
        if boundary == "validation":
            _install_validation_kill()
        else:
            _install_merge_kill(boundary)
        await _egress(state, "ckpt-00002", id_b)
    # The hook must have killed us before here.
    print("HOOK NEVER FIRED", file=sys.stderr)
    sys.exit(17)


async def recover(workdir: str, *, no_links: bool = False) -> dict[str, str]:
    """Run a fresh fire against the killed repo; return the verified id.

    Called in-process by the parent test. Proves the accepted repo is not
    wedged: a new checkpoint commits, absorbing any orphan the kill left.
    With ``no_links`` the fire runs on the copy-and-rename publication
    path, as the killed child did.
    """
    fs = asyncfiles.AsyncFilesystem()
    asyncfiles._current_async_fs.set(fs)
    state = _reopen(json.loads((Path(workdir) / "info.json").read_text()))
    id_next = _backup(state, "ckpt-00003", "v3\n")
    if no_links:
        from unittest.mock import patch

        with patch.object(os, "link", _no_link):
            verified = await _egress(state, "ckpt-00003", id_next)
    else:
        verified = await _egress(state, "ckpt-00003", id_next)
    return {"verified": verified, "expected": id_next}


if __name__ == "__main__":
    anyio.run(_run, Path(sys.argv[1]), sys.argv[2])
