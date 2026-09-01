"""Shared repo-adoption helpers used by hydration and snapshot strategies.

``fs_copy_repo`` and ``drop_orphan_snapshots`` were extracted from
``hydrate`` so the restic snapshot strategy can reuse them for its
per-sandbox ``adopt``/``discard_orphans`` without importing the
hydration orchestrator (which imports the strategies — a cycle).
``hydrate`` still uses both for the host repo.
"""

from __future__ import annotations

import json
from logging import getLogger
from pathlib import Path

import anyio

from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.trace import trace_action
from inspect_ai.util._restic.ops import restic_env

logger = getLogger(__name__)


def checkpoint_tag(checkpoint_id: int) -> str:
    """Format the shared per-checkpoint tag (``ckpt-NNNNN``).

    Matches the checkpoint file's ``ckpt-NNNNN`` prefix, so a strategy's
    snapshot tag/filename and a checkpoint file share the same N for the
    same checkpoint. Used as the restic ``--tag`` and as the archive
    strategy's snapshot id / file stem.
    """
    return f"ckpt-{checkpoint_id:05d}"


async def fs_copy_repo(
    old_sample_dir: str, subpath: str, new_repo: str, *, label: str
) -> list[str]:
    """Recursively copy a restic repo subtree from old sample dir to new.

    ``subpath`` is the per-domain path under the old sample checkpoints
    dir (``"restic/host"`` or ``"restic/sandboxes/<name>"``). ``old_sample_dir``
    may be local or remote; ``new_repo`` is always local. ``label`` is
    a short descriptor used only for the diagnostic print line.

    Returns the list of paths written, relative to the new sample root
    (i.e. each path starts with ``subpath``). Raises if the source
    enumerated no files — S3 has no real directories, so existence is
    only knowable via "any object with this prefix?", and a valid restic
    repo always has at least one file (`config`).
    """
    async_fs = get_async_filesystem()
    src_base = f"{old_sample_dir}/{subpath}"
    new_root = Path(new_repo)
    written: list[str] = []
    # `iter_files` yields URIs verbatim-prefixed by `src_base` for S3, but
    # fsspec-normalized (absolute) for local sources — so slicing by
    # `len(src_base)` mangles local relative sources. Relativize against the
    # `/<subpath>/` repo-root boundary instead: it's the last such marker in
    # the URI (a restic repo's own tree never contains `<subpath>`), so this
    # is correct regardless of how the backend normalizes the prefix.
    marker = f"/{subpath}/"
    with trace_action(logger, "Checkpoint Hydrate", f"fs-copy {label}"):
        async for uri in async_fs.iter_files(src_base, recursive=True):
            rel = uri.rsplit(marker, 1)[-1]
            dst = new_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            await async_fs.get_file(uri, str(dst))
            written.append(f"{subpath}/{rel}")
        if not written:
            raise RuntimeError(
                f"resume: expected {label} repo at {src_base}, but no files were found"
            )
    return written


async def drop_orphan_snapshots(
    restic: Path, repo: str, password: str, latest_id: int
) -> list[str]:
    """Forget restic snapshots tagged ``ckpt-NNNNN`` where NNNNN > latest_id.

    A fire that completed its restic backup but was interrupted before
    ``write_checkpoint_file`` leaves an orphan snapshot in the repo
    with no corresponding ``ckpt-NNNNN.json`` to acknowledge it. On resume we
    drop those so ``restic restore latest`` picks the committed
    snapshot — and so the next fire can write its tag without colliding
    with a stale tag of the same id. Returns the list of dropped tag
    names for logging.
    """
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "snapshots", "--json"],
        env=restic_env(password),
        check=True,
    )
    snapshots = json.loads(proc.stdout.decode())
    orphan_ids: list[str] = []
    orphan_tags: list[str] = []
    for snap in snapshots:
        for tag in snap.get("tags") or []:
            if not tag.startswith("ckpt-"):
                continue
            try:
                n = int(tag.removeprefix("ckpt-"))
            except ValueError:
                continue
            if n > latest_id:
                orphan_ids.append(snap["short_id"])
                orphan_tags.append(tag)
                break
    if orphan_ids:
        await anyio.run_process(
            [str(restic), "-r", repo, "forget", *orphan_ids],
            env=restic_env(password),
            check=True,
        )
    return orphan_tags
