"""Shared restic repo helpers used by hydration and the restic snapshot strategy.

``drop_orphan_snapshots`` was extracted from ``hydrate`` so the restic
snapshot strategy can reuse it for its per-sandbox ``discard_orphans``
without importing the hydration orchestrator (which imports the
strategies — a cycle). ``hydrate`` still uses it for the host repo.
"""

from __future__ import annotations

import json
from pathlib import Path

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
) -> list[str]:
    """Forget restic snapshots tagged ``ckpt-NNNNN`` where NNNNN > latest_id.

    A fire that completed its restic backup but was interrupted before
    ``write_checkpoint_file`` leaves an orphan snapshot in the repo
    with no corresponding ``ckpt-NNNNN.json`` to acknowledge it. On resume we
    drop those so ``restic restore latest`` picks the committed
    snapshot — and so the next fire can write its tag without colliding
    with a stale tag of the same id. Returns the dropped snapshots'
    full ids — a snapshot object's file name is its full id, so the
    caller can mirror the drop at a remote destination by deleting
    ``snapshots/<id>`` (see ``hydrate._delete_destination_files``).
    """
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "snapshots", "--json"],
        env=restic_env(password),
        check=True,
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
        await anyio.run_process(
            [str(restic), "-r", repo, "forget", *orphan_ids],
            env=restic_env(password),
            check=True,
        )
    return orphan_ids
