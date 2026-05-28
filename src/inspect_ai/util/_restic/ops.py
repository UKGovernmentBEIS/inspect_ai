"""Restic operations: init, backup, restore.

Thin wrappers around the ``restic`` CLI invoked via ``anyio.run_process``.
Generic across use cases — callers supply the repo path, password,
source(s)/target, and tag.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import anyio

from .summary import ResticBackupSummary


async def init_repo(restic: Path, repo: str, password: str) -> None:
    """Initialize a restic repo (idempotent).

    Skips if the repo is already initialized — important for callers
    that may re-enter the same repo across retries. ``repo`` is always
    a local filesystem path; restic is never invoked against a remote
    backend (see ``design/plans/checkpointing-remote-dest.md``).
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


def restic_env(password: str) -> dict[str, str]:
    """Environment dict for invoking the restic CLI.

    Sets ``RESTIC_PASSWORD`` and forwards ``PATH`` so the binary can
    resolve its dependencies (e.g. ``sh``, ``cat``).
    """
    return {"RESTIC_PASSWORD": password, "PATH": os.environ.get("PATH", "")}
