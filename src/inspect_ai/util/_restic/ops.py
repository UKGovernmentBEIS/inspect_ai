"""Restic operations: init, backup, restore.

Thin wrappers around the ``restic`` CLI invoked via ``anyio.run_process``.
Generic across use cases — callers supply the repo path, password,
source(s)/target, and tag.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
from collections.abc import Sequence
from pathlib import Path
from subprocess import CalledProcessError
from typing import Any

import anyio

from .summary import ResticBackupSummary


class RestoredTreeError(RuntimeError):
    """A snapshot to be restored holds non-regular nodes or exceeds the bounds."""


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

    The repo is untrusted input on resume: it is copied byte-for-byte from
    whatever the resume source holds, and a repo that opens cleanly says
    nothing about who wrote it. So the snapshot is checked before restic
    writes anything and the restored layout is never interpreted. One
    ``restic ls --json latest`` call yields the snapshot record and its
    node listing (:func:`_list_latest_snapshot`); the snapshot must record
    exactly one source path, every node must be a ``dir`` or ``file``, and
    the entry count / summed sizes must fit ``max_files`` / ``max_bytes``
    (:func:`_check_snapshot_nodes`). The source directory is then restored
    with restic's ``<snapshot>:<subfolder>`` syntax, which places its
    contents directly in ``target`` with no path chain to walk or rename.
    The listing's sizes are the repo's own claims, so the restore runs with
    ``--verify``: restic reads each restored file back and fails if its
    size or content disagrees with the node, which is what makes the byte
    bound hold for what actually lands on disk.

    ``target`` must be a directory or absent; a symlink is refused without
    being followed (:func:`_prepare_target`). It is emptied before restic
    runs: restic overwrites the snapshot's members but leaves other names
    alone, so files an interrupted fire left in the same directory would
    otherwise survive as state newer than the committed checkpoint. A
    failed or cancelled restore leaves its partial tree in ``target``; the
    exception propagates so nothing reads it, and the next restore into
    the directory empties it first.

    Raises:
        RestoredTreeError: the snapshot holds something other than regular
            files and directories, or exceeds the bounds.
        RuntimeError: ``target`` is a symlink or not a directory, the repo
            has no snapshot, the snapshot records no/several source paths,
            or its source path is not a directory in the listing.
        OSError: ``target`` could not be created or emptied.
        subprocess.CalledProcessError: ``restic restore`` failed, including
            a ``--verify`` mismatch.
    """
    target_dir = _prepare_target(target)
    snapshot, nodes = await _list_latest_snapshot(
        restic, repo, password, max_nodes=max_files
    )
    paths = snapshot.get("paths") or []
    if len(paths) != 1:
        raise RuntimeError(
            f"restic restore: expected the latest snapshot in {repo} to record "
            f"exactly one source path, found {paths}"
        )
    subfolder = _check_snapshot_nodes(
        nodes, paths[0], max_files=max_files, max_bytes=max_bytes
    )
    _empty_dir(target_dir)
    await anyio.run_process(
        [
            str(restic),
            "-r",
            repo,
            "restore",
            f"{snapshot['id']}:{subfolder}",
            "--target",
            str(target_dir),
            "--verify",
        ],
        env=restic_env(password),
        check=True,
    )


def _prepare_target(target: str) -> Path:
    """``target`` as an absolute path, created if absent.

    Checked with ``lstat`` before anything resolves the path: the
    ``mkdir(exist_ok=True)`` that creates the context dir on the caller's
    side (``ensure_context_dir``) accepts a symlink to an existing
    directory, and resolving one would redirect both the restore and the
    pre-restore emptying at wherever it points on the host. A symlink or a
    non-directory at ``target`` is refused.
    """
    path = Path(os.path.abspath(target))
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        path.mkdir(parents=True)
        return path
    if stat.S_ISLNK(st.st_mode):
        raise RuntimeError(
            f"restic restore: target is a symlink; refusing to follow it: {path}"
        )
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(f"restic restore: target is not a directory: {path}")
    return path


def _empty_dir(path: Path) -> None:
    """Remove every entry of ``path`` without following symlinks.

    Symlink entries are unlinked, not descended, so a link to a directory
    elsewhere on the host is never emptied. Nothing is suppressed: an entry
    that cannot be removed (say a directory an earlier restore of a hostile
    snapshot left unreadable) fails the restore rather than leaving stale
    state beside the restored files.
    """
    with os.scandir(path) as scan:
        entries = list(scan)
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
        else:
            os.unlink(entry.path)


async def _list_latest_snapshot(
    restic: Path, repo: str, password: str, *, max_nodes: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The latest snapshot's record and node records, from ``restic ls --json latest``.

    The first record ``ls --json`` prints is the snapshot itself (``id``,
    ``paths``, ...), so no separate ``snapshots`` call is needed; each
    restic invocation re-derives the repo key, which costs about half a
    second. Restic exits non-zero when the repo has no snapshot; that is
    reported as ``RuntimeError`` carrying restic's message.

    Node parsing stops after ``max_nodes + 1`` node records. The listing
    is untrusted and is decoded synchronously on the event loop, so the
    buffered stdout is iterated line by line and an oversized listing is
    cut off at the first record that already puts it over the bound —
    enough for :func:`_check_snapshot_nodes` to reject it — leaving the
    remaining lines neither decoded nor parsed. (``anyio.run_process`` has
    already buffered the whole listing in memory; only that residual cost
    remains.)
    """
    try:
        proc = await anyio.run_process(
            [str(restic), "-r", repo, "ls", "--json", "latest"],
            env=restic_env(password),
            check=True,
        )
    except CalledProcessError as ex:
        stderr = ex.stderr.decode(errors="replace").strip() if ex.stderr else ""
        detail = "no snapshot to restore" if "no snapshot found" in stderr else "failed"
        raise RuntimeError(
            f"restic restore: listing the latest snapshot in {repo} {detail}: {stderr}"
        ) from ex
    snapshot: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] = []
    for raw in io.BytesIO(proc.stdout):
        line = raw.decode().strip()
        if not line:
            continue
        record = json.loads(line)
        # restic 0.17+ emits ``message_type``; ``struct_type`` is the pre-0.17 key.
        kind = record.get("message_type", record.get("struct_type"))
        if kind == "snapshot" and snapshot is None:
            snapshot = record
        elif kind == "node":
            nodes.append(record)
            if len(nodes) > max_nodes:
                break
    if snapshot is None or not isinstance(snapshot.get("id"), str):
        raise RuntimeError(
            f"restic restore: `restic ls --json latest` on {repo} produced no "
            "snapshot record"
        )
    return snapshot, nodes


def _check_snapshot_nodes(
    nodes: list[dict[str, Any]], source_path: str, *, max_files: int, max_bytes: int
) -> str:
    """Check a snapshot listing before restore; return the subfolder to restore.

    Every node must be a ``dir`` or ``file`` — a symlink, fifo, socket, or
    device node is rejected here, before restic materializes anything.
    ``ls`` and ``restore`` read the same tree blobs, so the nodes restic
    goes on to write are the ones listed here (restic itself refuses
    malformed node names such as ``..``).
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
        if not isinstance(path, str):
            raise RestoredTreeError(f"snapshot node without a path: {node}")
        if kind == "dir":
            dirs.add(path)
        elif kind == "file":
            size = node.get("size")
            if not isinstance(size, int) or isinstance(size, bool):
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
    thing. Windows UNC (``\\server\share\...``) and extended-length
    (``\\?\...``) sources have no verified tree form and are refused
    explicitly rather than failing the listing match with a misleading
    "not a directory" error.
    """
    if source_path.startswith(chr(92) * 2):
        raise RuntimeError(
            "restic restore: UNC and extended-length Windows source paths are "
            f"not supported for checkpoint resume: {source_path}"
        )
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
