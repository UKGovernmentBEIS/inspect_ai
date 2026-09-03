"""Shared repo-adoption helpers used by hydration and snapshot strategies.

``fs_copy_repo`` and ``drop_orphan_snapshots`` were extracted from
``hydrate`` so the restic snapshot strategy can reuse them for its
per-sandbox ``adopt``/``discard_orphans`` without importing the
hydration orchestrator (which imports the strategies — a cycle).
``hydrate`` still uses both for the host repo.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from logging import getLogger
from pathlib import Path

import anyio

from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.trace import trace_action
from inspect_ai.util._restic.ops import restic_env

from ._layout._paths import contained_relative

logger = getLogger(__name__)

RESTIC_REPO_FILE_RE = re.compile(
    r"config|(?:keys|index|snapshots|locks)/[0-9a-f]{64}|data/[0-9a-f]{2}/[0-9a-f]{64}"
)
"""Every file a restic repository may contain, relative to the repo root.

``locks/`` is included because a prior attempt killed mid-backup leaves
its lock file behind, and adopting the repo must not fail on it (restic
itself treats such a lock as stale)."""


def is_restic_repo_file(rel: str) -> bool:
    """Whether ``rel`` (repo-root-relative) is a file of the restic repo layout."""
    return RESTIC_REPO_FILE_RE.fullmatch(rel) is not None


def checkpoint_tag(checkpoint_id: int) -> str:
    """Format the shared per-checkpoint tag (``ckpt-NNNNN``).

    Matches the checkpoint file's ``ckpt-NNNNN`` prefix, so a strategy's
    snapshot tag/filename and a checkpoint file share the same N for the
    same checkpoint. Used as the restic ``--tag`` and as the archive
    strategy's snapshot id / file stem.
    """
    return f"ckpt-{checkpoint_id:05d}"


async def fs_copy_repo(
    old_sample_dir: str,
    subpath: str,
    new_repo: str,
    *,
    label: str,
    accept: Callable[[str], bool],
) -> list[str]:
    """Recursively copy a strategy's storage subtree from old sample dir to new.

    ``subpath`` is the per-domain path under the old sample checkpoints
    dir (``"restic/host"`` or ``"restic/sandboxes/<name>"``). ``old_sample_dir``
    may be local or remote; ``new_repo`` is always local. ``label`` is
    a short descriptor used only for the diagnostic print line.

    The resume source is untrusted — an object store yields keys
    verbatim, so a key may carry ``..`` segments or a doubled slash (an
    absolute remainder). Every entry must pass ``contained_relative``;
    one that doesn't raises ``RuntimeError`` and fails hydration, since
    it means the source is compromised or corrupt and skipping silently
    would resume from a repo of unknown shape.

    ``accept`` then scopes the copy to the caller's own storage layout:
    it is given each (contained) entry's path relative to the repo root
    and returns whether to copy it. Entries it rejects are skipped with
    a warning rather than failing hydration, because a prior attempt
    killed mid-write legitimately leaves debris in its storage area
    (restic's ``<name>-tmp-*`` temp files, the archive strategy's
    ``.<name>.partial``) that the next attempt must resume past.

    Directory-marker objects (zero-byte keys ending in ``/``, as written
    by the S3 console's "Create folder") carry no content and are
    skipped.

    Returns the list of paths written, relative to the new sample root
    (i.e. each path starts with ``subpath``). Raises if the source
    enumerated no files — S3 has no real directories, so existence is
    only knowable via "any object with this prefix?", and a valid restic
    repo always has at least one file (`config`).
    """
    async_fs = get_async_filesystem()
    src_base = f"{old_sample_dir}/{subpath}"
    new_root = Path(new_repo)
    new_root_resolved = new_root.resolve()
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
            if uri.endswith("/"):
                continue
            raw_rel = uri.rsplit(marker, 1)[-1]
            try:
                rel = contained_relative(raw_rel)
            except ValueError as exc:
                raise RuntimeError(
                    f"resume: refusing {label} repo entry {uri!r}: {exc}"
                ) from exc
            if not accept(rel.as_posix()):
                logger.warning(
                    f"resume: skipping {label} repo entry {uri!r}: "
                    f"{rel.as_posix()!r} is not part of the repo layout"
                )
                continue
            dst = new_root / rel
            # Backstop for anything the component checks above don't model
            # (e.g. a Windows drive-relative remainder): the join must land
            # under the new repo root.
            if not dst.resolve().is_relative_to(new_root_resolved):
                raise RuntimeError(
                    f"resume: refusing {label} repo entry {uri!r}: "
                    f"resolves outside {new_root}"
                )
            dst.parent.mkdir(parents=True, exist_ok=True)
            await async_fs.get_file(uri, str(dst))
            written.append(f"{subpath}/{rel.as_posix()}")
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
