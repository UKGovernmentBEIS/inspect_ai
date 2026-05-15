"""Restic resolution and sandbox injection.

The host process resolves a local restic binary via the Phase 1
resolver (see :mod:`inspect_ai.util._restic`). For each sandbox whose
state we'll snapshot, the linux binary is injected at a root-only
path so non-root processes inside the sandbox (including the agent)
cannot see, stat, or execute it.

Path: ``/opt/inspect_restic/restic`` — the parent directory is created
with mode ``0700`` owned by root so the binary is invisible to
non-root users (a stronger property than a file-level ``chmod 0700``,
since the file would still appear in ``ls`` of a world-readable
parent). See ``design/plans/checkpointing-working.md`` §4f.
"""

from __future__ import annotations

import io
import json
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Literal

import anyio
from pydantic import BaseModel, ConfigDict

from inspect_ai.util._restic._platform import Platform
from inspect_ai.util._restic._resolver import resolve_restic
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.recon import Architecture, detect_sandbox_os


class ResticBackupSummary(BaseModel):
    """Last JSON line emitted by ``restic backup --json``.

    Field semantics mirror restic's documented summary output. Forward-
    compatible: unknown fields are tolerated (``extra="allow"``) so a
    future restic version that adds keys won't break parsing.
    """

    model_config = ConfigDict(extra="allow")

    message_type: Literal["summary"]
    dry_run: bool = False
    files_new: int
    files_changed: int
    files_unmodified: int
    dirs_new: int
    dirs_changed: int
    dirs_unmodified: int
    data_blobs: int
    tree_blobs: int
    data_added: int
    """Bytes added to the repo, *before* compression — i.e. the sum of
    uncompressed blob payloads."""

    data_added_packed: int
    """Bytes actually written to pack files on disk (after restic's
    per-blob compression). The disk-truthful "incremental size" of the
    snapshot."""

    total_files_processed: int
    total_bytes_processed: int
    backup_start: datetime
    backup_end: datetime
    total_duration: float
    snapshot_id: str
    """Omitted by restic only when snapshot creation was skipped (e.g.
    dry-run); always present for our writes."""


_SANDBOX_RESTIC_DIR = "/opt/inspect-restic"
SANDBOX_RESTIC_PATH = f"{_SANDBOX_RESTIC_DIR}/restic"
_SANDBOX_RESTIC_REPO = f"{_SANDBOX_RESTIC_DIR}/repo"
_EGRESS_MANIFEST = f"{_SANDBOX_RESTIC_DIR}/egress-manifest.txt"
_EGRESS_STAGING = f"{_SANDBOX_RESTIC_DIR}/staging"

_ARCH_TO_PLATFORM: dict[Architecture, Platform] = {
    "amd64": "linux_amd64",
    "arm64": "linux_arm64",
}


async def inject_restic(env: SandboxEnvironment) -> None:
    """Inject a linux restic binary into the sandbox at the root-only path.

    Streams the binary bytes via stdin to a root ``sh`` invocation so
    the binary never lands at a non-root-readable temp path; the agent
    can't observe it in flight or after.
    """
    info = await detect_sandbox_os(env)
    platform = _ARCH_TO_PLATFORM[info["architecture"]]
    binary_path = await resolve_restic(platform)
    binary_bytes = binary_path.read_bytes()

    script = (
        "set -e; "
        f"install -d -m 0700 {_SANDBOX_RESTIC_DIR}; "
        f"cat > {SANDBOX_RESTIC_PATH}; "
        f"chmod 0700 {SANDBOX_RESTIC_PATH}"
    )
    result = await env.exec(["sh", "-c", script], input=binary_bytes, user="root")
    if not result.success:
        raise RuntimeError(f"Failed to inject restic into sandbox: {result.stderr}")


async def init_host_repo(restic: Path, repo: str, password: str) -> None:
    """Initialize a restic repo on the host (idempotent).

    Skips if the repo is already initialized — important for sample-level
    retries that re-enter the Checkpointer against the same attempt subtree.
    """
    Path(repo).mkdir(parents=True, exist_ok=True)
    if (Path(repo) / "config").exists():
        return
    await anyio.run_process(
        [str(restic), "-r", repo, "init"],
        env=_restic_env(password),
        check=True,
    )


async def run_host_backup(
    restic: Path,
    repo: str,
    password: str,
    source: str,
    checkpoint_id: int,
) -> ResticBackupSummary:
    """Run ``restic backup`` against ``source``; return the parsed summary.

    The host working dir is JSON-only and tiny. ``--compression max``
    exploits the high text-compressibility (zstd-max ≈ 5–10× vs the
    default `auto` ≈ 2–3×); ``--no-scan`` skips the up-front size-estimate
    walk since we control exactly what's in the source dir.
    """
    proc = await anyio.run_process(
        [
            str(restic),
            "-r",
            repo,
            "backup",
            source,
            "--compression",
            "max",
            "--no-scan",
            "--tag",
            f"ckpt-{checkpoint_id:05d}",
            "--json",
        ],
        env=_restic_env(password),
        check=True,
    )
    return _parse_summary(proc.stdout.decode())


async def restore_host_repo(
    restic: Path, repo: str, password: str, target: str
) -> None:
    """Restore the latest snapshot in ``repo`` into ``target``.

    The host snapshot backs up a single source directory (the sample
    working dir); restic stores files at their original absolute paths.
    Restoring with ``--target T`` plus ``--include <source>`` lands
    files at ``T/<source>/*``. To get the contents directly under ``T``,
    we read the snapshot's source path from ``restic snapshots --json``,
    restore with ``--include`` to filter to that path, then move the
    files up one level so callers see ``T/events.json`` rather than
    ``T/<deep absolute path>/events.json``.
    """
    print(f"[hydrate.restic] restore_host_repo repo={repo} target={target}")
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "snapshots", "latest", "--json"],
        env=_restic_env(password),
        check=True,
    )
    snapshots = json.loads(proc.stdout.decode())
    if not snapshots:
        raise RuntimeError(f"restic repo {repo} has no snapshots to restore")
    source_paths = snapshots[-1]["paths"]
    if len(source_paths) != 1:
        raise RuntimeError(
            f"restic snapshot in {repo} backs up {len(source_paths)} paths; "
            "expected exactly one (the sample working dir)"
        )
    source_path = source_paths[0]
    print(
        f"[hydrate.restic] snapshot id={snapshots[-1].get('short_id', '?')}"
        f" source={source_path}"
    )

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
        env=_restic_env(password),
        check=True,
    )

    # Files land at <target><source_path>/. Move them up to <target>/.
    restored_dir = Path(target + source_path)
    target_dir = Path(target)
    moved = 0
    for entry in restored_dir.iterdir():
        entry.rename(target_dir / entry.name)
        moved += 1
    # Walk back up removing now-empty intermediate dirs.
    current = restored_dir
    while current != target_dir and current.is_dir() and not any(current.iterdir()):
        parent = current.parent
        current.rmdir()
        current = parent
    print(f"[hydrate.restic] restore moved {moved} entries into {target_dir}")


async def ingress_sandbox(
    env: SandboxEnvironment, src_repo: str, password: str
) -> None:
    """Copy a host-side restic repo into the sandbox + restore from it.

    Inverse of :func:`egress_sandbox`. Used on resume:

    1. Tar the host-side ``<sample_checkpoints_dir>/sandboxes/<name>/``
       repo (whose contents were FS-copied from the prior eval's host
       side just before this call).
    2. Stream the tarball into the sandbox via root ``sh`` so the agent
       never sees the bytes in flight, extracting into the standard
       in-sandbox repo location (``/opt/inspect-restic/repo``).
    3. Run ``restic restore latest --target /`` inside the sandbox so
       restored files land at their original absolute paths, replacing
       whatever the fresh sandbox came up with.

    Egress's two-phase manifest is reseeded by writing a manifest line
    for every file in the freshly-populated repo, so the next fire's
    diff treats the inherited snapshots as already-shipped.
    """
    src = Path(src_repo)
    if not src.is_dir():
        raise RuntimeError(
            f"resume: expected sandbox repo at {src}, but it doesn't exist"
        )

    tar_bytes = _build_repo_tar(src)
    print(f"[hydrate.restic] ingress_sandbox src={src} tar_bytes={len(tar_bytes)}")

    extract_script = (
        f"set -e; "
        f"install -d -m 0700 {_SANDBOX_RESTIC_DIR}; "
        f"rm -rf {_SANDBOX_RESTIC_REPO}; "
        f"mkdir -p {_SANDBOX_RESTIC_REPO}; "
        f"tar -xf - -C {_SANDBOX_RESTIC_REPO}; "
        # Seed the manifest with every inherited file so the next
        # egress only ships forward-progress entries.
        f"mkdir -p {_EGRESS_STAGING}; "
        f"(cd {_SANDBOX_RESTIC_REPO} && "
        f"  {{ find config -type f 2>/dev/null; "
        f"     find keys -type f 2>/dev/null; "
        f"     find data -type f 2>/dev/null; "
        f"     find index -type f 2>/dev/null; "
        f"     find snapshots -type f 2>/dev/null; }} | "
        f"  LC_ALL=C sort > {_EGRESS_MANIFEST})"
    )
    result = await env.exec(["sh", "-c", extract_script], input=tar_bytes, user="root")
    if not result.success:
        raise RuntimeError(f"Failed to ingress sandbox restic repo: {result.stderr}")
    print("[hydrate.restic] ingress_sandbox extracted; running restic restore")

    restore = await env.exec(
        [
            SANDBOX_RESTIC_PATH,
            "-r",
            _SANDBOX_RESTIC_REPO,
            "restore",
            "latest",
            "--target",
            "/",
        ],
        env={"RESTIC_PASSWORD": password},
        user="root",
    )
    if not restore.success:
        raise RuntimeError(
            f"Failed to restore sandbox state from in-container repo: {restore.stderr}"
        )
    print("[hydrate.restic] ingress_sandbox restore done")


def _build_repo_tar(repo: Path) -> bytes:
    """Build an in-memory tarball of ``repo``'s contents, paths relative."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for entry in sorted(repo.rglob("*")):
            tar.add(entry, arcname=str(entry.relative_to(repo)), recursive=False)
    return buf.getvalue()


async def init_sandbox_repo(env: SandboxEnvironment, password: str) -> None:
    """Initialize a restic repo inside the sandbox (idempotent).

    Runs as root against the injected binary. Skip if the repo is
    already initialized.
    """
    check = await env.exec(
        ["test", "-e", f"{_SANDBOX_RESTIC_REPO}/config"], user="root"
    )
    if check.success:
        return
    result = await env.exec(
        [SANDBOX_RESTIC_PATH, "-r", _SANDBOX_RESTIC_REPO, "init"],
        env={"RESTIC_PASSWORD": password},
        user="root",
    )
    if not result.success:
        raise RuntimeError(f"Failed to init sandbox restic repo: {result.stderr}")


async def run_sandbox_backup(
    env: SandboxEnvironment,
    password: str,
    paths: list[str],
    checkpoint_id: int,
) -> ResticBackupSummary:
    """Run ``restic backup`` inside the sandbox; return the parsed summary.

    ``--compression max`` (zstd level 22) for parity with the host
    backup. Mixed sandbox content (text, configs, sometimes binaries)
    benefits less than pure JSON, but the per-cycle CPU cost is small
    relative to the network/IO savings on the egress path.
    """
    cmd = [
        SANDBOX_RESTIC_PATH,
        "-r",
        _SANDBOX_RESTIC_REPO,
        "backup",
        *paths,
        "--compression",
        "max",
        "--tag",
        f"ckpt-{checkpoint_id:05d}",
        "--json",
    ]
    result = await env.exec(cmd, env={"RESTIC_PASSWORD": password}, user="root")
    if not result.success:
        raise RuntimeError(f"sandbox restic backup failed: {result.stderr}")
    return _parse_summary(result.stdout)


def _parse_summary(stdout: str) -> ResticBackupSummary:
    """Parse the last line of ``restic backup --json`` output as the summary.

    Restic emits one JSON object per line — periodic `status` messages
    followed by a final `summary`. The ``message_type: Literal["summary"]``
    field on the model means a non-summary last line raises ValidationError.
    """
    lines = stdout.strip().splitlines()
    if not lines:
        raise RuntimeError("restic backup produced no output")
    return ResticBackupSummary.model_validate_json(lines[-1])


def _restic_env(password: str) -> dict[str, str]:
    return {"RESTIC_PASSWORD": password, "PATH": os.environ.get("PATH", "")}


# === Sandbox repo egress ====================================================
#
# Per Appendix B of the working doc: each cycle, ship newly-written pack
# files (and on the first cycle, `config` + `keys/*`) from the in-sandbox
# buffer to the destination repo via a manifest-based diff and a
# two-phase commit. The destination is *not* pre-initialized — the first
# cycle's tarball carries `config`+`keys/*`, which makes the destination
# a valid restic repo on extraction.


async def egress_sandbox(
    env: SandboxEnvironment,
    *,
    dest_repo: str,
    password: str,
    host_restic: Path,
    checkpoint_id: int,
    snapshot_id: str,
) -> None:
    """Ship new pack files from the in-sandbox buffer to ``dest_repo``."""
    new_files = await _build_egress_tar(env, checkpoint_id)
    if not new_files:
        return

    # TODO(checkpointing-phase-3): for very large per-cycle deltas on
    # slow providers (Proxmox, Daytona, k8s), `read_file` on a single
    # big tar can hit per-call timeouts and peaks host RAM at the
    # tarball size. If that becomes a real problem, swap to a streaming
    # primitive (`cat <tar> | exec stdout`, chunked) — same protocol,
    # different copy-out mechanism. Typical inspect deltas are small
    # enough that a one-shot read_file is the right default.
    tar_path = f"{_EGRESS_STAGING}/egress-{checkpoint_id:05d}.tar"
    tar_bytes = await env.read_file(tar_path, text=False)
    Path(dest_repo).mkdir(parents=True, exist_ok=True)
    await anyio.to_thread.run_sync(_extract_tar, tar_bytes, dest_repo)

    await _verify_destination(host_restic, dest_repo, password, snapshot_id)

    await _commit_egress(env, checkpoint_id, new_files)


async def _build_egress_tar(env: SandboxEnvironment, checkpoint_id: int) -> list[str]:
    """Phase 1 (in-sandbox): diff vs manifest, build tarball.

    Returns the list of newly-staged file paths (relative to the repo
    root). Empty list ⇒ nothing new this cycle, no tar produced.
    """
    # `comm -23` requires both inputs sorted; `find` output is sorted via
    # `LC_ALL=C sort`. `tar -T -` reads the file list from stdin in the
    # given order — the order in which the host-side extraction will
    # see them. Order: config + keys (small, only first cycle anyway),
    # then data (referenced by index/snapshots), then index, then
    # snapshots — so the destination is valid at every intermediate
    # state if extraction crashes mid-way.
    script = f"""\
set -e
cd {_SANDBOX_RESTIC_REPO}
mkdir -p {_EGRESS_STAGING}
touch {_EGRESS_MANIFEST}
# Drop any orphan tarballs from prior cycles whose phase-2 commit
# failed — their content is regenerated by this cycle's diff.
rm -f {_EGRESS_STAGING}/egress-*.tar
{{
  find config -type f 2>/dev/null
  find keys -type f 2>/dev/null
  find data -type f 2>/dev/null
  find index -type f 2>/dev/null
  find snapshots -type f 2>/dev/null
}} | LC_ALL=C sort > /tmp/egress-current.txt
LC_ALL=C comm -23 /tmp/egress-current.txt {_EGRESS_MANIFEST} > /tmp/egress-new.txt
if [ ! -s /tmp/egress-new.txt ]; then exit 0; fi
tar -cf {_EGRESS_STAGING}/egress-{checkpoint_id:05d}.tar -T /tmp/egress-new.txt
cat /tmp/egress-new.txt
"""
    result = await env.exec(["sh", "-c", script], user="root")
    if not result.success:
        raise RuntimeError(f"sandbox egress (build) failed: {result.stderr}")
    return [line for line in result.stdout.splitlines() if line]


def _extract_tar(tar_bytes: bytes, dest_repo: str) -> None:
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        tar.extractall(dest_repo)


async def _verify_destination(
    host_restic: Path, dest_repo: str, password: str, snapshot_id: str
) -> None:
    """Confirm the destination repo lists the new snapshot.

    Cheap metadata read (`restic snapshots --json`); catches torn
    extractions before we advance the in-sandbox manifest.
    """
    proc = await anyio.run_process(
        [str(host_restic), "-r", dest_repo, "snapshots", "--json"],
        env=_restic_env(password),
        check=True,
    )
    snapshots = json.loads(proc.stdout.decode())
    if snapshot_id not in {s["id"] for s in snapshots}:
        raise RuntimeError(
            f"destination repo {dest_repo} doesn't list snapshot "
            f"{snapshot_id} after egress"
        )


async def _commit_egress(
    env: SandboxEnvironment, checkpoint_id: int, new_files: list[str]
) -> None:
    """Phase 2 (in-sandbox): advance the manifest, drop the tarball."""
    script = f"""\
set -e
cat {_EGRESS_MANIFEST} - | LC_ALL=C sort -u > {_EGRESS_MANIFEST}.tmp
mv {_EGRESS_MANIFEST}.tmp {_EGRESS_MANIFEST}
rm -f {_EGRESS_STAGING}/egress-{checkpoint_id:05d}.tar
"""
    result = await env.exec(
        ["sh", "-c", script],
        input="\n".join(new_files) + "\n",
        user="root",
    )
    if not result.success:
        raise RuntimeError(f"sandbox egress (commit) failed: {result.stderr}")
