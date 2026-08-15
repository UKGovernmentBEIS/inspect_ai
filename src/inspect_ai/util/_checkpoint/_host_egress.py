"""Host egress: ship sample staging dir → remote sample checkpoints dir.

Runs when the resolved sample checkpoints dir is remote: at the end of
each fire, and once at the end of resume hydration (shipping the resume
payload to the new attempt's destination — with no manifest yet, every
staged file is "new"). Mirrors the in-sandbox egress protocol: manifest
of files already shipped, diff against the live staging dir, ship new
files in a safe order, then atomically update the manifest.

The ``context/`` subdir (restic source — host context files restic
backs up) and the manifest file itself are excluded from shipping.
Everything else under the staging dir lands at the destination with
the same relative path.

Safe upload order — destination is valid at every intermediate state:

1. ``restic/host/config``, ``restic/sandboxes/<name>/config``
   (first cycle for each repo)
2. ``restic/**/keys/*`` (first cycle for each repo)
3. ``restic/**/data/**`` (immutable, content-addressed)
4. ``restic/**/index/**`` (immutable; occasional consolidation)
5. ``restic/**/snapshots/**`` (references indexes / data)
6. ``restic/restic-config.json`` (first cycle; password file)
7. ``ckpt-NNNNN.json`` last (commit point at the destination)

Within each tier, files are shipped in lexicographic order. The
manifest write at the end is the commit point for the local "I've
shipped these"; a crash between ship and manifest-replace leaves the
destination ahead of the manifest, and the next fire's diff re-ships
the in-flight files (idempotent because restic content is
content-addressed and checkpoint files overwrite cleanly).
"""

from __future__ import annotations

import os
import re
from logging import getLogger
from pathlib import Path

from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.trace import trace_action

from ._async_fs import async_mkdir
from ._layout.schemas import Checkpoint

logger = getLogger(__name__)

MANIFEST_FILENAME = ".egress-manifest.txt"

# Names that are never shipped from the staging dir to the destination.
# ``context/`` is restic's local backup source — its contents are
# captured inside the restic repos and not part of the checkpoint
# state at the destination. The manifest itself is host-local
# bookkeeping.
_EXCLUDED_TOP_LEVEL: frozenset[str] = frozenset({"context", MANIFEST_FILENAME})

# Tier ordering: (priority, regex matching the path's relative form).
# A new file's tier is the lowest-priority matching pattern, defaulting
# to a catch-all bucket if none match (which shouldn't happen for
# well-formed restic content).
_CHECKPOINT_FILE_RE = re.compile(r"^ckpt-\d+\.json$")
_RESTIC_CONFIG = "restic/restic-config.json"


async def host_egress(*, staging_dir: str, destination_dir: str) -> None:
    """Ship newly-written staging files to ``destination_dir``.

    No-op when there are no new files. Uses ``AsyncFilesystem`` for
    all destination I/O, so remote schemes (`s3://`, etc.) honor the
    standard credential resolution.
    """
    staging = Path(staging_dir)
    manifest_path = staging / MANIFEST_FILENAME
    shipped = _read_manifest(manifest_path)
    new_files = [
        rel
        for rel in _scan_new_files(staging, shipped)
        if _committed_checkpoint_or_other(staging, rel)
    ]
    if not new_files:
        return
    ordered = _safe_order(new_files)
    # Wrap the per-file upload loop so a stalled remote write (the prime
    # stall site for remote destinations) shows up in `inspect trace
    # anomalies` and the in-progress egress is observable live.
    with trace_action(
        logger, "Checkpoint Egress", f"host {staging_dir} -> {destination_dir}"
    ):
        async_fs = get_async_filesystem()
        for rel in ordered:
            src = staging / rel
            dst = f"{destination_dir}/{rel}"
            await async_mkdir(_parent_of(dst))
            with open(src, "rb") as f:
                await async_fs.write_file_streaming(dst, f)
    _write_manifest(manifest_path, shipped | set(ordered))


def _read_manifest(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {line for line in path.read_text().splitlines() if line}


def _write_manifest(path: Path, files: set[str]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(sorted(files)) + "\n")
    os.replace(tmp, path)


def _scan_new_files(staging: Path, shipped: set[str]) -> list[str]:
    new: list[str] = []
    for entry in staging.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(staging)
        top = rel.parts[0]
        if top in _EXCLUDED_TOP_LEVEL:
            continue
        rel_s = rel.as_posix()
        if rel_s in shipped:
            continue
        new.append(rel_s)
    return new


def _committed_checkpoint_or_other(staging: Path, rel: str) -> bool:
    if not _CHECKPOINT_FILE_RE.match(Path(rel).name):
        return True
    try:
        Checkpoint.model_validate_json((staging / rel).read_bytes())
    except Exception:
        return False
    return True


def _safe_order(files: list[str]) -> list[str]:
    """Sort new files into the safe upload tiers (see module docstring)."""
    config_keys: list[str] = []
    data: list[str] = []
    index: list[str] = []
    snapshots: list[str] = []
    restic_config: list[str] = []
    checkpoint_files: list[str] = []
    other: list[str] = []
    for f in files:
        parts = f.split("/")
        if f == _RESTIC_CONFIG:
            restic_config.append(f)
        elif _CHECKPOINT_FILE_RE.match(parts[-1]):
            checkpoint_files.append(f)
        elif "data" in parts:
            data.append(f)
        elif "index" in parts:
            index.append(f)
        elif "snapshots" in parts:
            snapshots.append(f)
        elif parts[-1] == "config" or "keys" in parts:
            config_keys.append(f)
        else:
            other.append(f)
    return (
        sorted(config_keys)
        + sorted(data)
        + sorted(index)
        + sorted(snapshots)
        + sorted(other)
        + sorted(restic_config)
        + sorted(checkpoint_files)
    )


def _parent_of(path: str) -> str:
    """Return the parent directory of ``path`` for arbitrary URIs."""
    idx = path.rfind("/")
    return path[:idx] if idx > 0 else path
