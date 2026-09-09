"""Shared restic repo helpers used by hydration and the restic snapshot strategy.

``drop_orphan_snapshots`` was extracted from ``hydrate`` so the restic
snapshot strategy can reuse it for its per-sandbox ``discard_orphans``
without importing the hydration orchestrator (which imports the
strategies — a cycle). ``hydrate`` still uses it for the host repo.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Collection
from pathlib import Path
from typing import Any

import anyio

from inspect_ai.util._restic.ops import restic_env


def checkpoint_tag(checkpoint_id: int) -> str:
    """Format the shared per-checkpoint tag (``ckpt-NNNNN``).

    Matches the checkpoint file's ``ckpt-NNNNN`` prefix, so a strategy's
    snapshot tag/filename and a checkpoint file share the same N for the
    same checkpoint. Used as the restic ``--tag`` and as the archive
    strategy's snapshot id / file stem.
    """
    return f"ckpt-{checkpoint_id:05d}"


async def drop_orphan_snapshots(
    restic: Path, repo: str, password: str, latest_id: int
) -> None:
    """Prepare a copied repo for resume: clear locks, forget orphan snapshots.

    Runs once per repo at resume, before anything else touches it. Any
    ``locks/`` entry is process state a killed restic left behind (a
    dead parent closes its output pipe mid-operation) — no process can
    legitimately hold a lock on a repo this attempt has just copied or
    is about to restore from — and left in place it makes the exclusive
    ``forget`` below fail. Orphan snapshots are those tagged
    ``ckpt-NNNNN`` with NNNNN > ``latest_id``: a fire that completed its
    backup but was interrupted before ``write_checkpoint_file``. Dropping
    them makes ``restic restore latest`` pick the committed snapshot and
    lets the next fire write its tag without colliding with a stale one.
    """
    await _run_restic(
        [str(restic), "-r", repo, "unlock", "--remove-all"], password=password
    )
    proc = await _run_restic(
        [str(restic), "-r", repo, "snapshots", "--json"], password=password
    )
    snapshots = json.loads(proc.stdout.decode())
    orphan_ids: list[str] = []
    for snap in snapshots:
        for tag in snap.get("tags") or []:
            if not tag.startswith("ckpt-"):
                continue
            try:
                n = int(tag.removeprefix("ckpt-"))
            except ValueError:
                continue
            if n > latest_id:
                orphan_ids.append(snap["id"])
                break
    if orphan_ids:
        await _run_restic(
            [str(restic), "-r", repo, "forget", *orphan_ids], password=password
        )


async def _run_restic(
    command: list[str], *, password: str
) -> subprocess.CompletedProcess[bytes]:
    """Run a restic command; a non-zero exit raises with restic's stderr.

    ``anyio.run_process(check=True)`` raises ``CalledProcessError`` whose
    message carries only the command and exit status — restic's reason
    ("repository is already locked by ...", "repository does not exist")
    is on stderr, and without it a failed resume is undiagnosable.
    """
    proc = await anyio.run_process(command, env=restic_env(password), check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"restic {command[3]} failed (exit {proc.returncode}) on {command[2]}: "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    return proc


SNAPSHOT_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")
"""A restic snapshot id as reported by ``restic backup`` (full 64-hex in
practice; a unique prefix is accepted the way restic's CLI accepts one)."""


async def list_snapshots(
    restic: Path, repo: str, password: str
) -> list[dict[str, Any]]:
    """``restic snapshots --json`` on ``repo`` (host-side metadata read).

    ``--no-lock``: a metadata read needs no repository lock, and a lock
    file left by a killed listing would otherwise ride along to the
    destination and block ``forget`` on a resume from another host.
    """
    proc = await _run_restic(
        [str(restic), "-r", repo, "snapshots", "--json", "--no-lock"],
        password=password,
    )
    snapshots: list[dict[str, Any]] = json.loads(proc.stdout.decode())
    return snapshots


def match_snapshot_id(full_ids: Collection[str], recorded: str) -> str | None:
    """The one full id in ``full_ids`` that ``recorded`` names, else ``None``.

    Records hold what restic reported — a full 64-hex id in practice, but
    a unique prefix is accepted the way restic's own CLI accepts one. An
    ambiguous prefix, or a ``recorded`` value that is not a snapshot id
    at all (see ``SNAPSHOT_ID_RE``), names nothing.
    """
    if not SNAPSHOT_ID_RE.fullmatch(recorded):
        return None
    matches = [f for f in full_ids if f.startswith(recorded)]
    return matches[0] if len(matches) == 1 else None


async def forget_unrecorded_snapshots(
    restic: Path,
    repo: str,
    password: str,
    *,
    recorded_ids: Collection[str],
    required_id: str,
) -> list[str]:
    """Remove snapshots that no committed checkpoint file records.

    ``repo`` is the host-side restic repository copied from the previous
    attempt for resume. Extra snapshots may be leftovers from interrupted
    attempts or deliberately supplied by the sandbox. The host does not
    distinguish these cases: a snapshot is unrecorded when no committed
    checkpoint file names it. Remove these snapshots before restoring
    the sandbox.

    ``recorded_ids`` contains the snapshot ids from committed checkpoint
    files. ``required_id`` identifies the snapshot resume will restore.
    Check that this required snapshot exists before forgetting snapshots;
    if it is missing, raise an error.

    Inherited locks are cleared first: the copied repository has no live
    owner from the previous attempt. Return the tags of snapshots removed.
    """
    malformed = [
        i for i in {*recorded_ids, required_id} if not SNAPSHOT_ID_RE.fullmatch(i)
    ]
    if malformed:
        raise RuntimeError(
            f"resume: committed checkpoint(s) record malformed sandbox snapshot "
            f"id(s) {sorted(malformed)!r} for repo {repo}"
        )
    # The retry startup copy owns this repo; inherited locks have no live owner.
    await _run_restic(
        [str(restic), "-r", repo, "unlock", "--remove-all"], password=password
    )
    snapshots = await list_snapshots(restic, repo, password)
    full_ids = [snap["id"] for snap in snapshots]
    if match_snapshot_id(full_ids, required_id) is None:
        raise RuntimeError(
            f"resume: repo {repo} does not contain snapshot {required_id}, the "
            f"latest committed checkpoint's recorded snapshot"
        )
    keep = {
        full
        for recorded in recorded_ids
        if (full := match_snapshot_id(full_ids, recorded)) is not None
    }
    orphans = [snap for snap in snapshots if snap["id"] not in keep]
    if orphans:
        await _run_restic(
            [str(restic), "-r", repo, "forget", *(snap["id"] for snap in orphans)],
            password=password,
        )
    return [tag for snap in orphans for tag in (snap.get("tags") or [])]
