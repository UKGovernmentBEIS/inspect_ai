"""Sandbox→host restic repo egress + host→sandbox ingress.

Per Appendix B of the working doc: each cycle, ship newly-written pack
files (and on the first cycle, ``config`` + ``keys/*``) from the in-sandbox
buffer to the destination repo via a manifest-based diff and a two-phase
commit. The destination is *not* pre-initialized — the first cycle's
tarball carries ``config``+``keys/*``, which makes the destination a
valid restic repo on extraction.

Ingress is the inverse: on resume, copy a host-side repo back into the
sandbox and restic-restore the files at their original absolute paths.

Layout under the same ``/root/.cache/inspect/`` root as :mod:`.repo`:
- ``./egress-manifest.txt`` — sorted list of files already shipped
- ``./staging/`` — per-cycle tarballs awaiting host-side extraction
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

import anyio

from inspect_ai.util._restic.ops import restic_env
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.limits import override_max_read_file_size

from .._async_fs import async_mkdir
from .repo import _SANDBOX_RESTIC_DIR, _SANDBOX_RESTIC_PATH, _SANDBOX_RESTIC_REPO

_EGRESS_MANIFEST = f"{_SANDBOX_RESTIC_DIR}/egress-manifest.txt"
_EGRESS_STAGING = f"{_SANDBOX_RESTIC_DIR}/staging"


async def ingress_sandbox(
    env: SandboxEnvironment, src_repo: str, password: str
) -> None:
    """Copy a host-side restic repo into the sandbox + restore from it.

    Inverse of :func:`egress_sandbox`. Used on resume:

    1. Tar the host-side repo dir (whose contents were FS-copied from
       the prior eval's host side just before this call).
    2. Stream the tarball into the sandbox via root ``sh`` so the agent
       never sees the bytes in flight, extracting into the standard
       in-sandbox repo location (``/root/.cache/inspect/repo``).
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

    restore = await env.exec(
        [
            _SANDBOX_RESTIC_PATH,
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


def _build_repo_tar(repo: Path) -> bytes:
    """Build an in-memory tarball of ``repo``'s contents, paths relative."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for entry in sorted(repo.rglob("*")):
            tar.add(entry, arcname=str(entry.relative_to(repo)), recursive=False)
    return buf.getvalue()


async def egress_sandbox(
    env: SandboxEnvironment,
    *,
    dest_repo: str,
    password: str,
    host_restic: Path,
    tag: str,
    snapshot_id: str,
) -> None:
    """Ship new pack files from the in-sandbox buffer to ``dest_repo``.

    ``tag`` names the per-cycle staging tarball and must be unique per
    cycle; ``snapshot_id`` is the restic snapshot id produced by the
    backup that immediately preceded this call, used to verify the
    destination accepted the new snapshot before advancing the manifest.
    """
    new_files = await _build_egress_tar(env, tag)
    if not new_files:
        return

    # TODO(checkpointing-phase-3): for very large per-cycle deltas on
    # slow providers (Proxmox, Daytona, k8s), `read_file` on a single
    # big tar can hit per-call timeouts and peaks host RAM at the
    # tarball size. If that becomes a real problem, swap to a streaming
    # primitive (`cat <tar> | exec stdout`, chunked) — same protocol,
    # different copy-out mechanism. Typical inspect deltas are small
    # enough that a one-shot read_file is the right default.
    tar_path = f"{_EGRESS_STAGING}/egress-{tag}.tar"
    # The tarball carries the full initial pack set and can
    # legitimately exceed the default read cap.
    with override_max_read_file_size(sys.maxsize):
        tar_bytes = await env.read_file(tar_path, text=False)
    await async_mkdir(dest_repo)
    await anyio.to_thread.run_sync(_extract_tar, tar_bytes, dest_repo)

    await _verify_destination(host_restic, dest_repo, password, snapshot_id)

    await _commit_egress(env, tag, new_files)


async def _build_egress_tar(env: SandboxEnvironment, tag: str) -> list[str]:
    """Phase 1 (in-sandbox): diff vs manifest, build tarball.

    Returns the list of newly-staged file paths (relative to the repo
    root). Empty list ⇒ nothing new this cycle, no tar produced.

    The scratch listings live in the root-only staging dir rather than
    ``/tmp``, where they would be world-readable and advertise the
    repo's existence to the agent.
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
}} | LC_ALL=C sort > {_EGRESS_STAGING}/current.txt
LC_ALL=C comm -23 {_EGRESS_STAGING}/current.txt {_EGRESS_MANIFEST} > {_EGRESS_STAGING}/new.txt
if [ ! -s {_EGRESS_STAGING}/new.txt ]; then exit 0; fi
tar -cf {_EGRESS_STAGING}/egress-{tag}.tar -T {_EGRESS_STAGING}/new.txt
cat {_EGRESS_STAGING}/new.txt
"""
    result = await env.exec(["sh", "-c", script], user="root")
    if not result.success:
        raise RuntimeError(f"sandbox egress (build) failed: {result.stderr}")
    return [line for line in result.stdout.splitlines() if line]


def _extract_tar(tar_bytes: bytes, dest_repo: str) -> None:
    # The tarball bytes originate inside the sandbox (read via `read_file`),
    # so they are untrusted: a sandboxed agent can plant a malicious tar at
    # the egress staging path. `filter="data"` rejects absolute paths, `..`
    # traversal, and outside-pointing links, preventing host-side writes
    # outside `dest_repo` (CVE-2007-4559 class). See PEP 706.
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        tar.extractall(dest_repo, filter="data")


async def _verify_destination(
    host_restic: Path, dest_repo: str, password: str, snapshot_id: str
) -> None:
    """Confirm the destination repo lists the new snapshot.

    Cheap metadata read (`restic snapshots --json`); catches torn
    extractions before we advance the in-sandbox manifest.
    """
    proc = await anyio.run_process(
        [str(host_restic), "-r", dest_repo, "snapshots", "--json"],
        env=restic_env(password),
        check=True,
    )
    snapshots = json.loads(proc.stdout.decode())
    if snapshot_id not in {s["id"] for s in snapshots}:
        raise RuntimeError(
            f"destination repo {dest_repo} doesn't list snapshot "
            f"{snapshot_id} after egress"
        )


async def _commit_egress(
    env: SandboxEnvironment, tag: str, new_files: list[str]
) -> None:
    """Phase 2 (in-sandbox): advance the manifest, drop the tarball."""
    script = f"""\
set -e
cat {_EGRESS_MANIFEST} - | LC_ALL=C sort -u > {_EGRESS_MANIFEST}.tmp
mv {_EGRESS_MANIFEST}.tmp {_EGRESS_MANIFEST}
rm -f {_EGRESS_STAGING}/egress-{tag}.tar
"""
    result = await env.exec(
        ["sh", "-c", script],
        input="\n".join(new_files) + "\n",
        user="root",
    )
    if not result.success:
        raise RuntimeError(f"sandbox egress (commit) failed: {result.stderr}")
