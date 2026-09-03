"""Restic operations: init, backup, restore.

Thin wrappers around the ``restic`` CLI invoked via ``anyio.run_process``.
Generic across use cases — callers supply the repo path, password,
source(s)/target, and tag.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any

import anyio

from .summary import ResticBackupSummary
from .verify import RestoredTreeError, verify_regular_tree


async def init_repo(restic: Path, repo: str, password: str) -> None:
    """Initialize a restic repo (idempotent).

    Skips if the repo is already initialized — important for callers
    that may re-enter the same repo across retries. ``repo`` is always
    a local filesystem path; restic is never invoked against a remote
    backend (remote destinations are reached via host egress instead).
    """
    Path(repo).mkdir(parents=True, exist_ok=True)
    if (Path(repo) / "config").exists():
        return
    await anyio.run_process(
        [str(restic), "-r", repo, "init"],
        env=restic_env(password),
        check=True,
    )


async def run_backup(
    restic: Path,
    repo: str,
    password: str,
    source: str | Sequence[str],
    tag: str,
) -> ResticBackupSummary:
    """Run ``restic backup`` against ``source``; return the parsed summary.

    Accepts a single source path or a sequence of paths, mirroring
    ``restic backup PATH1 [PATH2 ...]``. Sources are passed to restic as
    absolute paths: restic records the absolute path in the snapshot's
    ``paths`` either way, but roots the tree at the argument *as given*,
    so a relative source would leave the two disagreeing (see
    :func:`_snapshot_subfolder`, which :func:`restore_repo` relies on).
    The resulting snapshot is tagged with ``tag``.
    ``--compression max`` exploits high text-compressibility
    (zstd-max ≈ 5–10× vs the default `auto` ≈ 2–3×) for JSON-heavy sources;
    ``--no-scan`` skips the up-front size-estimate walk. ``--quiet`` drops
    restic's periodic ``status`` JSON lines (one per progress tick): only
    the trailing ``summary`` line is read by ``from_stdout``, so the status
    stream is buffered to no purpose (here in ``anyio.run_process``'s
    in-memory pipe rather than against the sandbox output cap).
    """
    sources = [source] if isinstance(source, str) else list(source)
    sources = [os.path.abspath(s) for s in sources]
    proc = await anyio.run_process(
        [
            str(restic),
            "-r",
            repo,
            "backup",
            *sources,
            "--compression",
            "max",
            "--no-scan",
            "--tag",
            tag,
            "--json",
            "--quiet",
        ],
        env=restic_env(password),
        check=True,
    )
    return ResticBackupSummary.from_stdout(proc.stdout.decode())


async def restore_repo(
    restic: Path,
    repo: str,
    password: str,
    target: str,
    *,
    max_files: int,
    max_bytes: int,
) -> None:
    """Restore the latest snapshot's single source directory into ``target``.

    The repo is untrusted input on resume (see :mod:`.verify`), so the
    restored layout is never interpreted. The latest snapshot's recorded
    source path is read from ``restic snapshots --json latest`` (exactly
    one is required) and its node listing from ``restic ls --json``; the
    listing is checked *before* restic writes anything — every node must
    be a ``dir`` or ``file`` and the entry count / total size must fit
    ``max_files`` / ``max_bytes`` — then that directory is restored with
    restic's ``<snapshot>:<subfolder>`` syntax, which places its contents
    directly in ``target`` with no intermediate path chain to walk or
    rename. The restored tree is re-checked with
    :func:`verify_regular_tree` as belt-and-braces — the listing's sizes
    are the repo's own claims, so only the on-disk check is authoritative
    for bytes. Whatever restic wrote is removed from ``target`` if the
    restore fails, is cancelled, or fails the on-disk check.

    Raises:
        RestoredTreeError: the snapshot holds something other than regular
            files and directories, or exceeds the bounds.
        RuntimeError: the snapshot has no/several source paths, its source
            path is not a directory in the listing, or restore produced no
            files.
    """
    target_dir = Path(target).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    snapshot = await _latest_snapshot(restic, repo, password)
    paths = snapshot.get("paths") or []
    if len(paths) != 1:
        raise RuntimeError(
            f"restic restore: expected the latest snapshot in {repo} to record "
            f"exactly one source path, found {paths}"
        )
    nodes = await _snapshot_nodes(
        restic, repo, password, snapshot["id"], max_nodes=max_files
    )
    subfolder = _check_snapshot_nodes(
        nodes, paths[0], max_files=max_files, max_bytes=max_bytes
    )
    try:
        await anyio.run_process(
            [
                str(restic),
                "-r",
                repo,
                "restore",
                f"{snapshot['id']}:{subfolder}",
                "--target",
                str(target_dir),
            ],
            env=restic_env(password),
            check=True,
        )
        stats = await anyio.to_thread.run_sync(
            partial(
                verify_regular_tree,
                target_dir,
                max_files=max_files,
                max_bytes=max_bytes,
            )
        )
        if stats.files == 0:
            raise RuntimeError(f"restic restore produced no files under {target_dir}")
    except BaseException:
        # Cancellation included: never leave an unverified tree behind.
        shutil.rmtree(target_dir, ignore_errors=True)
        raise


async def _latest_snapshot(restic: Path, repo: str, password: str) -> dict[str, Any]:
    """The latest snapshot record in ``repo`` (``restic snapshots --json latest``).

    Delegating "latest" to restic keeps the selection identical to what
    ``restic restore latest`` would pick, rather than re-deriving it from
    timestamps here. An empty repo yields ``[]`` (exit status 0).
    """
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "snapshots", "--json", "latest"],
        env=restic_env(password),
        check=True,
    )
    snapshots: list[dict[str, Any]] = json.loads(proc.stdout.decode())
    if len(snapshots) != 1:
        raise RuntimeError(
            f"restic restore: expected one latest snapshot in {repo}, "
            f"found {len(snapshots)}"
        )
    return snapshots[0]


async def _snapshot_nodes(
    restic: Path, repo: str, password: str, snapshot_id: str, *, max_nodes: int
) -> list[dict[str, Any]]:
    """Node records of ``snapshot_id`` per ``restic ls --json`` (header dropped).

    Parsing stops after ``max_nodes + 1`` node records. The listing is
    untrusted and is decoded synchronously on the event loop, so an
    oversized one is cut off at the first record that already puts it over
    the bound — enough for :func:`_check_snapshot_nodes` to reject it —
    instead of stalling every other running sample while millions of lines
    are parsed.
    """
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "ls", "--json", snapshot_id],
        env=restic_env(password),
        check=True,
    )
    nodes: list[dict[str, Any]] = []
    for line in proc.stdout.decode().splitlines():
        if not line:
            continue
        record = json.loads(line)
        # restic 0.17+ emits ``message_type``; ``struct_type`` is the pre-0.17 key.
        if record.get("message_type", record.get("struct_type")) != "node":
            continue
        nodes.append(record)
        if len(nodes) > max_nodes:
            break
    return nodes


def _check_snapshot_nodes(
    nodes: list[dict[str, Any]], source_path: str, *, max_files: int, max_bytes: int
) -> str:
    """Validate a snapshot listing before restore; return the subfolder to restore.

    Every node must be a ``dir`` or ``file`` — a symlink, fifo, socket, or
    device node is rejected here, before restic materializes anything.
    The node count (including the source path's ancestor directories,
    which restic lists too) is bounded by ``max_files`` and the summed
    file sizes by ``max_bytes``; a file node without an integer ``size``
    is malformed and rejected. The returned subfolder is the listed
    ``dir`` node holding ``source_path``'s contents
    (:func:`_snapshot_subfolder`); a snapshot without that directory is
    rejected rather than guessed at.
    """
    entries = 0
    total = 0
    dirs: set[str] = set()
    for node in nodes:
        kind, path = node.get("type"), node.get("path")
        if kind == "dir":
            dirs.add(str(path))
        elif kind == "file":
            size = node.get("size")
            if not isinstance(size, int):
                raise RestoredTreeError(f"snapshot file node without a size: {path}")
            total += size
        else:
            raise RestoredTreeError(f"snapshot contains a {kind} node: {path}")
        entries += 1
        if entries > max_files:
            raise RestoredTreeError(f"snapshot exceeds {max_files} entries")
        if total > max_bytes:
            raise RestoredTreeError(f"snapshot exceeds {max_bytes} bytes")
    return _snapshot_subfolder(source_path, dirs)


def _snapshot_subfolder(source_path: str, dirs: set[str]) -> str:
    """The listed directory holding the recorded ``source_path``'s contents.

    Restic records the *absolute* source path in a snapshot's ``paths``
    but roots the tree at the backup argument as given. For an absolute
    source (every snapshot :func:`run_backup` writes) the tree path is
    the recorded path itself. Snapshots written by earlier versions from a
    relative source (a relative ``checkpoints_location``) are rooted at
    the relative components instead, so their tree path is a trailing run
    of the recorded path's components: ``/tmp/x/ckpts/context`` is listed
    as ``/ckpts/context``. The longest suffix listed as a ``dir`` wins —
    the honest tree has only ancestors above the source and files below
    it, so a shorter match can only be an ancestor that happens to share
    the source's name. No suffix matching is an error, not a guess.
    """
    tree_path = _tree_path(source_path)
    parts = tree_path.strip("/").split("/")
    for start in range(len(parts)):
        candidate = "/" + "/".join(parts[start:])
        if candidate in dirs:
            return candidate
    raise RuntimeError(
        f"restic restore: snapshot source path {source_path} (tree path "
        f"{tree_path}) is not a directory in the snapshot"
    )


_WINDOWS_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def _tree_path(source_path: str) -> str:
    r"""Map a snapshot's recorded source path to restic's in-tree path.

    POSIX paths are stored verbatim. Restic stores a Windows source
    ``C:\a\b`` under a root component named for the drive, ``/C/a/b``,
    which is also the form ``ls`` prints and ``restore <id>:<subfolder>``
    expects. ``_check_snapshot_nodes`` confirms the result against the
    listing, so a mismatch fails loudly instead of restoring the wrong
    thing.
    """
    match = _WINDOWS_DRIVE_PATH.match(source_path)
    if match is None:
        return source_path
    drive, rest = match.groups()
    return f"/{drive}/{rest.replace(chr(92), '/')}".rstrip("/")


def _cap(paths: list[str], limit: int) -> tuple[list[str], int]:
    """First ``limit`` paths plus the count beyond ``limit``."""
    return paths[:limit], max(0, len(paths) - limit)


def _parse_listed_files(stdout: str, limit: int) -> tuple[list[str], int]:
    """Parse ``restic ls <id> --json`` output into (files, overflow).

    ``restic ls --json`` emits one JSON object per line: a leading
    snapshot object then one node per entry. Filter to file nodes
    (``type == "file"``) and collect their ``path``; the snapshot object
    and dir/symlink nodes have no ``"file"`` type so they fall out.
    """
    nodes = (json.loads(line) for line in stdout.splitlines() if line)
    return _cap([node["path"] for node in nodes if node.get("type") == "file"], limit)


def _parse_changed_files(stdout: str, limit: int) -> tuple[list[str], int]:
    """Parse ``restic diff <parent> <id> --json`` into (changed files, overflow).

    ``restic diff --json`` emits one ``{"message_type": "change", ...}``
    object per changed path plus a trailing ``statistics`` object. Keep
    file paths that were added or whose content/type changed (``modifier``
    contains ``+``, ``M``, or ``T``); drop removals (``-``), pure-metadata
    changes (``U``), and directories (paths ending in ``/``).
    """
    changed: list[str] = []
    for line in stdout.splitlines():
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("message_type") != "change":
            continue
        path, modifier = obj.get("path", ""), obj.get("modifier", "")
        if not path.endswith("/") and any(m in modifier for m in "+MT"):
            changed.append(path)
    return _cap(changed, limit)


def _previous_id(snapshots: list[dict[str, Any]], snapshot_id: str) -> str | None:
    """Id of the snapshot chronologically before ``snapshot_id``.

    ``None`` if ``snapshot_id`` is the earliest (or absent). Used as the
    diff base instead of restic's own ``parent`` field, which is selected
    per-hostname — and the hostname changes across a resume (new
    container), so the auto-parent would be lost there. The repo holds only
    one source's snapshots in time order, so the prior entry is the right
    base regardless of hostname.
    """
    ordered = sorted(snapshots, key=lambda s: s["time"])
    idx = next(
        (
            i
            for i, s in enumerate(ordered)
            if s["id"] == snapshot_id or s["id"].startswith(snapshot_id)
        ),
        None,
    )
    return ordered[idx - 1]["id"] if idx else None


async def list_changed_files(
    restic: Path, repo: str, password: str, snapshot_id: str, limit: int
) -> tuple[list[str], int]:
    """Files added or changed in ``snapshot_id``, capped, plus overflow count.

    Diffs the snapshot against the chronologically prior snapshot in the
    repo (``restic diff``) so the result is the snapshot's own
    contribution, not the full repo tree. The earliest snapshot has no
    predecessor — everything in it is new — so it falls back to listing the
    whole snapshot (``restic ls``). Host-side invocation (unlimited output);
    the diff output is bounded by the number of changes, not the total file
    count.
    """
    snapshots = await anyio.run_process(
        [str(restic), "-r", repo, "snapshots", "--json"],
        env=restic_env(password),
        check=True,
    )
    parent = _previous_id(json.loads(snapshots.stdout.decode()), snapshot_id)
    if parent is None:
        proc = await anyio.run_process(
            [str(restic), "-r", repo, "ls", snapshot_id, "--json"],
            env=restic_env(password),
            check=True,
        )
        return _parse_listed_files(proc.stdout.decode(), limit)
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "diff", parent, snapshot_id, "--json"],
        env=restic_env(password),
        check=True,
    )
    return _parse_changed_files(proc.stdout.decode(), limit)


def restic_env(password: str) -> dict[str, str]:
    """Environment dict for invoking the restic CLI.

    Sets ``RESTIC_PASSWORD`` and forwards ``PATH`` so the binary can
    resolve its dependencies (e.g. ``sh``, ``cat``).
    """
    return {"RESTIC_PASSWORD": password, "PATH": os.environ.get("PATH", "")}
