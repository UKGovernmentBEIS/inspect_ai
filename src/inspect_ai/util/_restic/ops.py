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

import anyio

from .summary import ResticBackupSummary, _parse_summary


async def init_repo(restic: Path, repo: str, password: str) -> None:
    """Initialize a restic repo (idempotent).

    Skips if the repo is already initialized — important for callers
    that may re-enter the same repo across retries.
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
    return _parse_summary(proc.stdout.decode())


async def restore_repo(restic: Path, repo: str, password: str, target: str) -> None:
    """Restore the latest snapshot in ``repo`` into ``target``.

    Restic stores files at their original absolute paths. Restoring with
    ``--target T`` plus ``--include <source>`` lands files at
    ``T/<source>/*``. To get the contents directly under ``T``, we read
    the snapshot's source path from ``restic snapshots --json``, restore
    with ``--include`` to filter to that path, then move the files up
    one level so callers see ``T/<file>`` rather than
    ``T/<deep absolute path>/<file>``. Assumes the latest snapshot backed
    up exactly one source directory.
    """
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "snapshots", "latest", "--json"],
        env=restic_env(password),
        check=True,
    )
    snapshots = json.loads(proc.stdout.decode())
    if not snapshots:
        raise RuntimeError(f"restic repo {repo} has no snapshots to restore")
    source_paths = snapshots[-1]["paths"]
    if len(source_paths) != 1:
        raise RuntimeError(
            f"restic snapshot in {repo} backs up {len(source_paths)} paths; "
            "expected exactly one"
        )
    source_path = source_paths[0]

    await anyio.run_process(
        [
            str(restic),
            "-r",
            repo,
            "restore",
            "latest",
            "--target",
            target,
            "--include",
            source_path,
        ],
        env=restic_env(password),
        check=True,
    )

    # Files land at <target><source_path>/. Move them up to <target>/.
    restored_dir = Path(target + source_path)
    target_dir = Path(target)
    for entry in restored_dir.iterdir():
        entry.rename(target_dir / entry.name)
    # Walk back up removing now-empty intermediate dirs.
    current = restored_dir
    while current != target_dir and current.is_dir() and not any(current.iterdir()):
        parent = current.parent
        current.rmdir()
        current = parent


def restic_env(password: str) -> dict[str, str]:
    """Environment dict for invoking the restic CLI.

    Sets ``RESTIC_PASSWORD`` and forwards ``PATH`` so the binary can
    resolve its dependencies (e.g. ``sh``, ``cat``).
    """
    return {"RESTIC_PASSWORD": password, "PATH": os.environ.get("PATH", "")}
