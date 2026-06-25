"""Restic operations: init, backup, restore.

Thin wrappers around the ``restic`` CLI invoked via ``anyio.run_process``.
Generic across use cases — callers supply the repo path, password,
source(s)/target, and tag.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import anyio

from .summary import ResticBackupSummary


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
    ``restic backup PATH1 [PATH2 ...]``. The resulting snapshot is tagged
    with ``tag``. ``--compression max`` exploits high text-compressibility
    (zstd-max ≈ 5–10× vs the default `auto` ≈ 2–3×) for JSON-heavy sources;
    ``--no-scan`` skips the up-front size-estimate walk.
    """
    sources = [source] if isinstance(source, str) else list(source)
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
        ],
        env=restic_env(password),
        check=True,
    )
    return ResticBackupSummary.from_stdout(proc.stdout.decode())


async def restore_repo(restic: Path, repo: str, password: str, target: str) -> None:
    """Restore the latest snapshot in ``repo`` into ``target``.

    Restic preserves the source's directory structure under ``--target``
    — exactly where the restored files land within that structure has
    varied across restic versions and `--include` flag combinations.
    Rather than try to predict the leaf path, we restore everything,
    then walk down the single-child directory chain from ``target``
    until we hit the leaf containing actual files, and move them up to
    ``target`` so callers see the files directly. Assumes the latest
    snapshot backed up exactly one source directory (the chain has
    exactly one descent path).
    """
    target_dir = Path(target).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    await anyio.run_process(
        [str(restic), "-r", repo, "restore", "latest", "--target", str(target_dir)],
        env=restic_env(password),
        check=True,
    )

    # Walk down through any single-child intermediate directories restic
    # created to mirror the source path; stop when we find files.
    leaf = target_dir
    while True:
        entries = list(leaf.iterdir())
        if not entries:
            raise RuntimeError(f"restic restore produced no files under {target_dir}")
        if any(e.is_file() for e in entries):
            break  # leaf reached
        if len(entries) == 1 and entries[0].is_dir():
            leaf = entries[0]
            continue
        raise RuntimeError(
            f"restic restore: ambiguous layout under {target_dir} "
            f"(expected single-child dir chain to file leaf, found "
            f"{len(entries)} children at {leaf})"
        )

    if leaf != target_dir:
        for entry in leaf.iterdir():
            entry.rename(target_dir / entry.name)
        # Walk back up removing the now-empty intermediate dirs.
        current = leaf
        while current != target_dir and current.is_dir() and not any(current.iterdir()):
            parent = current.parent
            current.rmdir()
            current = parent


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
