"""Sandbox→host restic repo egress + host→sandbox ingress.

Per Appendix B of the working doc: each cycle, ship newly-written pack
files (and on the first cycle, ``config`` + ``keys/*``) from the in-sandbox
buffer to the destination repo via a manifest-based diff and a two-phase
commit. The destination is *not* pre-initialized — the first cycle's
tarball carries ``config``+``keys/*``, which makes the destination a
valid restic repo on extraction.

The sandbox controls the state it supplies, including repository files
and metadata. These checks limit what a transfer can write on the host,
prevent replacement of previously accepted repository files, and tie
resume to a recorded snapshot. They do not establish that a snapshot
faithfully captures the sandbox, that its contents are recent, or that
those contents are truthful. Root-only staging does not prevent an
agent controlling sandbox root from modifying the transfer.

Each checkpoint sends a tar archive containing new restic repository
files. The host checks those files before accepting the checkpoint:

Host protections:

- **Previously accepted files cannot change.** Restic names its data,
  index, snapshot, and key files by the SHA-256 hash of their contents.
  The host checks that each incoming file's contents hash to its name.
  If the file already exists, both copies must hash to that name, and
  the existing file is left untouched. This lets retries resend files
  safely. The configuration file has no hash in its name, so a resent
  copy must match the existing contents. New configuration and key
  files are accepted only before the destination has a configuration.
- **Host writes stay within the restic layout.** Archive entries must
  be regular files with allowed repository paths and pass tarfile's
  path-safety checks. Links and paths outside that layout are rejected.
- **Transfers have a size limit.** The host limits both the bytes copied
  out of the sandbox (see :mod:`.._copy`) and the bytes extracted from
  the archive. The file list is bounded by the transfer cap and limits
  the number of archive entries accepted. The sandbox also checks size
  before building the archive to avoid wasted work, but the host
  enforces the limit independently.
- **A transfer is validated before it reaches the accepted repo.** New
  files are received into a staging area beside the accepted repo, and a
  throwaway view — the accepted repo (hard links) plus the additions — is
  checked with ``restic check --read-data`` and ``restic ls`` before any
  file is merged. Content addressing already prevents *changing* an
  accepted file, but a later transfer could otherwise *add* a
  correctly-named file (a malformed index, or a valid index that maps a
  blob to an attacker-supplied pack) that leaves an earlier checkpoint
  unrestorable or silently corrupt. Validation rejects such additions on
  the copy, so the accepted repo is never touched by a transfer that
  would break it. Only then are the additions linked in — packs, then
  indexes, then snapshots — so even a hard kill mid-merge leaves every
  earlier checkpoint restorable. Passing validation is not authenticity:
  the sandbox still shapes its own captures, which it controls anyway.

Transfer protocol checks reject inconsistent transfers. A compromised
sandbox can satisfy them while supplying fabricated state:

- **The archive must contain exactly the files the sandbox listed.**
  The host rejects missing files, extra files, and duplicates. The
  list itself is untrusted; this check ensures the transfer matches it.
- **The checkpoint must name a newly received snapshot.** The host
  compares the destination's snapshots before and after extraction.
  Every added snapshot must correspond to a file the host just wrote.
  The snapshot reported by the sandbox must be one of those additions
  and carry exactly this checkpoint's tag; an old snapshot cannot be
  presented as a new one. Other snapshots may arrive alongside it,
  either left by failed attempts or deliberately supplied by the
  sandbox. Failed attempts can reuse checkpoint numbers and tags.
  These extras are not
  recorded as committed checkpoints and are forgotten on resume by
  ``forget_unrecorded_snapshots``. The host returns the full id of the
  newly received snapshot for the strategy to record.
- **An empty transfer is an error.** Even when the captured files have
  not changed, a restic backup creates a new snapshot file. A sandbox
  claiming there is nothing to send has violated the protocol.

Recovery behavior:

Extraction and validation happen on the throwaway view in a per-sandbox
scratch directory that is removed on every exit path. A transfer that
fails validation, or is cancelled before the merge begins, never reaches
the accepted repo, which is left exactly as it was found. The merge then
links the validated additions into the accepted repo, packs before
indexes before snapshots, so an interruption once it has begun — a hard
kill, or a cancellation between the merge and the manifest commit — leaves
at most a safe prefix or a merged-but-unrecorded snapshot: every earlier
checkpoint stays restorable, and the leftover is dropped on resume by
``forget_unrecorded_snapshots`` or re-sent idempotently by the next fire
(content-addressed files). Only after the additions are merged does the
host tell the sandbox to mark the accepted files as shipped; if that
acknowledgment fails, the next attempt can safely resend them.

Ingress is the inverse: on resume, list the recorded snapshot on the
host and refuse one that reaches outside this attempt's capture roots
or carries special nodes or mode bits, then copy the host-side repo
back into the sandbox and restic-restore each root at its original
absolute path (see :func:`ingress_sandbox`).

Layout under the same ``/root/.cache/inspect/`` root as :mod:`.repo`:
- ``./egress-manifest.txt`` — sorted list of files already shipped
- ``./staging/`` — per-cycle tarballs awaiting host-side extraction
"""

from __future__ import annotations

import errno
import hashlib
import io
import os
import re
import shutil
import subprocess
import tarfile
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from functools import partial
from itertools import islice
from pathlib import Path
from typing import IO, Any, NamedTuple

import anyio

from inspect_ai.util._restic.ops import restic_env
from inspect_ai.util._sandbox._privileged import privileged_exec, privileged_shell
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._async_fs import async_mkdir
from .._copy import DEFAULT_COPY_CHUNK_SIZE, copy_out
from .._repo_ops import (
    SNAPSHOT_ID_RE,
    _kill,
    list_snapshots,
    match_snapshot_id,
    walk_snapshot_nodes,
)
from .._restore_scope import (
    RESTORED_XATTRS,
    RestoreRoots,
    restic_node,
    restic_restore_args,
)
from .repo import _SANDBOX_RESTIC_DIR

_HEX64 = r"[0-9a-f]{64}"
_MEMBER_RE = re.compile(
    rf"^(?:config|keys/{_HEX64}|data/[0-9a-f]{{2}}/{_HEX64}|index/{_HEX64}"
    rf"|snapshots/{_HEX64})$"
)
"""The restic repo layout: the only member names egress accepts."""

_FIRST_CYCLE_ONLY = ("config", "keys/")
_HASH_CHUNK = 1024 * 1024
_MAX_TAR_METADATA_BYTES = 64 * 1024
_MAX_VIEW_STDERR_BYTES = 64 * 1024
"""Most of a validation command's stderr kept for the error: the view is
built from sandbox-supplied bytes, so restic's diagnostics are attacker-shaped
and can dwarf the input (one forged index can produce megabytes)."""
_VIEW_LINK_BATCH = 256
"""Hard links attempted per worker-thread call while building the validation
view (~0.25 ms each), bounding how long a cancellation waits on the link
path however many files the repository holds."""
_VIEW_COPY_BLOCK = 8 * 1024 * 1024
"""Bytes copied per worker-thread call when the view must be copied (a
filesystem without hard links), bounding how long a cancellation waits within
one file however large it is — a staged file can be as large as the transfer
cap."""


class EgressVerificationError(RuntimeError):
    """A sandbox egress failed one of the host-side verification checks."""


class _SandboxPaths(NamedTuple):
    """In-sandbox paths the egress/ingress protocol uses, under one root."""

    restic: str
    repo: str
    manifest: str
    staging: str


def _sandbox_paths(sandbox_dir: str) -> _SandboxPaths:
    return _SandboxPaths(
        restic=f"{sandbox_dir}/restic",
        repo=f"{sandbox_dir}/repo",
        manifest=f"{sandbox_dir}/egress-manifest.txt",
        staging=f"{sandbox_dir}/staging",
    )


async def ingress_sandbox(
    env: SandboxEnvironment,
    src_repo: str,
    password: str,
    snapshot_id: str,
    *,
    roots: RestoreRoots,
    host_restic: Path,
    sandbox_dir: str = _SANDBOX_RESTIC_DIR,
) -> None:
    """Copy a host-side restic repo into the sandbox + restore from it.

    Inverse of :func:`egress_sandbox`. Used on resume:

    1. List ``snapshot_id`` on the host (``restic ls --json`` against
       the adopted repo, which the host already opens for ``snapshots``)
       and check every node against ``roots`` — this attempt's capture
       set — before any byte enters the sandbox: nothing outside a root,
       no device/fifo/socket nodes, no setuid/setgid/sticky bits (see
       ``_restore_scope``). A snapshot that fails is refused with the
       offending path and the sandbox is left untouched.
    2. Tar the host-side repo dir (put in place by the retry startup
       copy, or by the prior run of this sample on an in-eval requeue).
    3. Stream the tarball into the sandbox via root ``sh`` so the agent
       never sees the bytes in flight, extracting into the standard
       in-sandbox repo location (``/root/.cache/inspect/repo``).
    4. For each root, ``restic restore <id>:<parent> --target <parent>
       --include /<name> --include-xattr user.*`` inside the sandbox, so
       the root lands at its original absolute path and nothing above
       it is written (restic would otherwise restore the recorded
       metadata of every ancestor directory on the way to a selected
       node). Only ``user.*`` extended attributes are restored: the
       listing cannot see xattrs, and restic running as root would
       otherwise reapply a recorded ``security.capability`` — a setuid
       bit by another name — or a ``system.posix_acl_*`` grant.

    ``snapshot_id`` is the latest committed checkpoint's recorded id;
    the caller resolves it, there is no ``latest`` fallback. The caller
    has also already deleted every symlink the fresh image ships under a
    root (``_restore_scope.remove_existing_symlinks``, run by the core
    before the strategy's ``setup`` injected restic), so neither the repo
    extracted in step 3 nor a snapshot node is written through one.

    Egress's two-phase manifest is reseeded by writing a manifest line
    for every file in the freshly-populated repo, so the next fire's
    diff treats the inherited snapshots as already-shipped.
    """
    src = Path(src_repo)
    if not src.is_dir():
        raise RuntimeError(
            f"resume: expected sandbox repo at {src}, but it doesn't exist"
        )
    if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise RuntimeError(
            f"resume: checkpoint record has malformed sandbox snapshot id "
            f"{snapshot_id!r}"
        )
    paths = _sandbox_paths(sandbox_dir)
    label = f"resume: sandbox snapshot {snapshot_id[:8]} from {src}"
    full_id = await _check_snapshot_scope(
        host_restic, src_repo, password, snapshot_id, roots, label=label
    )

    tar_bytes = _build_repo_tar(src)

    extract_script = (
        f"set -e; "
        f"install -d -m 0700 {sandbox_dir}; "
        f"rm -rf {paths.repo}; "
        f"mkdir -p {paths.repo}; "
        f"tar -xf - -C {paths.repo}; "
        # Seed the manifest with every inherited file so the next
        # egress only ships forward-progress entries.
        f"mkdir -p {paths.staging}; "
        f"(cd {paths.repo} && "
        f"  {{ find config -type f 2>/dev/null; "
        f"     find keys -type f 2>/dev/null; "
        f"     find data -type f 2>/dev/null; "
        f"     find index -type f 2>/dev/null; "
        f"     find snapshots -type f 2>/dev/null; }} | "
        f"  LC_ALL=C sort > {paths.manifest})"
    )
    result = await privileged_shell(env, extract_script, input=tar_bytes, user="root")
    if not result.success:
        raise RuntimeError(f"Failed to ingress sandbox restic repo: {result.stderr}")

    for root in roots.roots:
        args = restic_restore_args(full_id, root)
        restore = await privileged_exec(
            env,
            [
                paths.restic,
                "-r",
                paths.repo,
                "restore",
                args.snapshot_spec,
                "--target",
                args.target,
                "--include",
                args.include,
                "--include-xattr",
                RESTORED_XATTRS,
            ],
            env={"RESTIC_PASSWORD": password},
            user="root",
        )
        if not restore.success:
            raise RuntimeError(
                f"Failed to restore sandbox state under {root} from in-container "
                f"repo: {restore.stderr}"
            )


async def _check_snapshot_scope(
    host_restic: Path,
    repo: str,
    password: str,
    snapshot_id: str,
    roots: RestoreRoots,
    *,
    label: str,
) -> str:
    """Host-side listing check of the snapshot about to be restored; return its full id.

    Every node must pass the :class:`RestoreWalk` and every root must be
    present in the snapshot. Nothing has been sent to the sandbox when
    this runs, so a refused snapshot leaves it untouched.
    """
    walk = roots.walker(label=label)

    def visit(record: dict[str, Any]) -> None:
        walk.visit(restic_node(record, label=label))

    full_id = await walk_snapshot_nodes(host_restic, repo, password, snapshot_id, visit)
    walk.finish()
    return full_id


def _build_repo_tar(repo: Path) -> bytes:
    """Build an in-memory tarball of ``repo``'s contents, paths relative."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for entry in sorted(repo.rglob("*")):
            tar.add(entry, arcname=str(entry.relative_to(repo)), recursive=False)
    return buf.getvalue()


def _scratch_dir(dest_repo: str) -> Path:
    """This sandbox's host scratch directory: ``.egress-<name>`` beside the repo.

    Keyed by the destination repo's name (the sandbox name), which is
    unique per sample, so no two sandboxes share a scratch directory.
    """
    dest_path = Path(dest_repo)
    return dest_path.parent / f".egress-{dest_path.name}"


def _reset_scratch_dir(scratch: Path) -> None:
    """Recreate ``scratch`` empty, sweeping residue from a killed fire.

    Only a hard kill (SIGKILL, OOM) leaves anything here: the scratch tar
    or ``copy_out``'s ``.partial`` beside it. Swept before this fire's
    copy so it never rides along with the next host egress to a remote
    destination. Failures propagate: a sweep that silently fails would
    ship the residue.
    """
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()


async def egress_sandbox(
    env: SandboxEnvironment,
    *,
    dest_repo: str,
    password: str,
    host_restic: Path,
    tag: str,
    snapshot_id: str,
    max_bytes: int,
    chunk_size: int = DEFAULT_COPY_CHUNK_SIZE,
    dd_fullblock: bool = False,
    sandbox_dir: str = _SANDBOX_RESTIC_DIR,
) -> str:
    """Ship new pack files from the in-sandbox buffer to ``dest_repo``.

    ``tag`` names the per-cycle staging tarball and must be unique per
    cycle; it is also the tag the backup that immediately preceded this
    call carried, and ``snapshot_id`` is the id that backup reported.
    The host checks that the reported id names a newly received snapshot
    with exactly the expected tag, then returns its full id for the
    caller to record. These checks do not authenticate the captured
    state. ``max_bytes`` caps the tarball transfer and the bytes
    extracted; ``chunk_size``/``dd_fullblock`` tune the chunked
    copy-out (see :func:`.._copy.copy_out`).

    Raises :class:`EgressVerificationError` when a check fails (the
    destination is left unchanged) and ``RuntimeError`` for transport
    or in-sandbox failures.
    """
    if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise EgressVerificationError(
            f"sandbox reported a malformed snapshot id {snapshot_id!r}"
        )
    paths = _sandbox_paths(sandbox_dir)
    label = f"sandbox egress {tag} -> {dest_repo}"

    await async_mkdir(dest_repo)
    before_files = await anyio.to_thread.run_sync(_scan_repo_files, dest_repo)
    first_cycle = "config" not in before_files
    before_ids: dict[str, list[str]] = (
        {} if first_cycle else await _snapshot_tags(host_restic, dest_repo, password)
    )
    if match_snapshot_id(before_ids, snapshot_id) is not None:
        raise EgressVerificationError(
            f"{label}: reported snapshot {snapshot_id} already exists in the "
            f"destination (replayed id)"
        )

    build = await _build_egress_tar(env, tag, paths, max_bytes=max_bytes)
    if not build.new_files:
        raise EgressVerificationError(
            f"{label}: sandbox reported an empty diff after a backup; a restic "
            f"backup always writes a new snapshot file, so nothing to ship is a "
            f"protocol violation, not a no-op"
        )

    # This fire's new repo files are received, validated, and merged
    # entirely beside (never inside) the accepted repo, so no failure path
    # can leave a poisoned file where a restore of an earlier checkpoint
    # would load it:
    #
    #   1. the tarball is copied out and extracted into a staging dir;
    #   2. a throwaway *view* — the accepted repo (hard links) plus the
    #      staged additions — is validated with `restic check --read-data`
    #      and `ls`, so a malformed or conflicting index is caught on the
    #      copy, before the accepted repo is touched;
    #   3. only then are the staged files linked into the accepted repo,
    #      packs before indexes before snapshots, so even a hard kill
    #      mid-merge leaves every earlier checkpoint restorable.
    #
    # The scratch dir lives in a per-sandbox directory beside the repo, so
    # nothing partial ever sits where restic would see it. Sandboxes
    # egress concurrently and one name may prefix another (`web` /
    # `web-db`), so the residue sweep is scoped to this sandbox's
    # directory, not a name glob over the shared parent.
    scratch = _scratch_dir(dest_repo)
    await anyio.to_thread.run_sync(_reset_scratch_dir, scratch)
    tar_host = scratch / f"{tag}.tar"
    staging = scratch / "staging"
    view = scratch / "view"
    try:
        await copy_out(
            env,
            src=f"{paths.staging}/egress-{tag}.tar",
            chunk_path=f"{paths.staging}/chunk",
            size=build.tar_size,
            dest=tar_host,
            max_bytes=max_bytes,
            label=label,
            chunk_size=chunk_size,
            dd_fullblock=dd_fullblock,
        )
        extracted = await anyio.to_thread.run_sync(
            partial(
                _extract_verified,
                tar_host,
                str(staging),
                existing_repo=dest_repo,
                new_files=build.new_files,
                existing=before_files,
                first_cycle=first_cycle,
                max_bytes=max_bytes,
                label=label,
            )
        )
        await _build_validation_view(
            view,
            existing_repo=dest_repo,
            existing=before_files,
            staging=staging,
            written=extracted.written,
        )
        verified_id = await _validate_view(
            host_restic,
            view,
            password,
            before_ids=before_ids,
            written=extracted.written,
            snapshot_id=snapshot_id,
            tag=tag,
            label=label,
        )
        await anyio.to_thread.run_sync(
            partial(_merge_into_repo, dest_repo, staging, extracted.written)
        )
    finally:
        # Threaded: the scratch dir holds the tarball (up to `max_bytes`),
        # the staging copy, and the hard-linked view, and unlinking is not
        # free. Shielded: this `finally` also runs under cancellation,
        # where an unshielded await would abort.
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(
                partial(shutil.rmtree, scratch, ignore_errors=True)
            )

    await _commit_egress(env, tag, extracted.members, paths)
    return verified_id


class _EgressBuild(NamedTuple):
    """Sandbox-reported file list and size, subject to host transfer checks."""

    new_files: list[str]
    """Repo-relative paths the sandbox staged into this cycle's tarball."""

    tar_size: int
    """The tarball's size in bytes as the sandbox reports it."""


_OVERSIZE_MARKER = "oversize"
"""First stdout line of the build script when the delta exceeds the cap."""


async def _build_egress_tar(
    env: SandboxEnvironment, tag: str, paths: _SandboxPaths, *, max_bytes: int
) -> _EgressBuild:
    """Phase 1 (in-sandbox): diff vs manifest, build tarball.

    Returns the sandbox-reported list of newly-staged file paths
    (relative to the repo root) and tarball size. An empty list means
    the sandbox produced no tar — which, after a backup, the caller
    treats as an error.

    A delta whose files already total more than ``max_bytes`` is refused
    before any tarring (``RuntimeError``): the tarball can only be
    larger, ``copy_out`` would refuse it anyway, and — since a refused
    egress never advances the manifest — the same oversized delta would
    otherwise be re-tarred in the sandbox on every later fire. The tar's
    true size is still what the copy-out cap binds on.

    The scratch listings live in the root-only staging dir rather than
    ``/tmp``, where they would be world-readable and advertise the
    repo's existence to the agent.
    """
    # `comm -23` requires both inputs sorted (`LC_ALL=C sort`), so the diff
    # list is then re-ranked into the order `tar -T` writes members — the
    # order in which the host-side extraction lands them: keys, then
    # config (first cycle only; `config` is the first-cycle sentinel, so
    # it lands last of the two — a repo with `config` but no key cannot
    # be opened and would never be re-bootstrapped), then data (referenced
    # by index/snapshots), then index, then snapshots — so the destination
    # is valid at every intermediate state if extraction crashes mid-way.
    # Restic file names are hex, so the unquoted `xargs` over `new.txt` is
    # safe; `ls -ln` column 5 is the byte size on GNU, busybox and BSD
    # alike (`stat`'s flags are not). The total is printed with `%.0f`:
    # `print` on older awks (mawk 1.3.3) emits sums above the C int range
    # in scientific notation, which `test -gt` rejects and the `if` then
    # silently skips the pre-check.
    script = f"""\
set -e
cd {paths.repo}
mkdir -p {paths.staging}
touch {paths.manifest}
# Drop any orphan tarballs (and copy-out chunks) from prior cycles whose
# phase-2 commit failed — their content is regenerated by this cycle's diff.
rm -f {paths.staging}/egress-*.tar {paths.staging}/chunk
{{
  find keys -type f 2>/dev/null
  find config -type f 2>/dev/null
  find data -type f 2>/dev/null
  find index -type f 2>/dev/null
  find snapshots -type f 2>/dev/null
}} | LC_ALL=C sort > {paths.staging}/current.txt
LC_ALL=C comm -23 {paths.staging}/current.txt {paths.manifest} > {paths.staging}/new.txt
if [ ! -s {paths.staging}/new.txt ]; then exit 0; fi
total=$(xargs ls -ln < {paths.staging}/new.txt | awk '{{ s += $5 }} END {{ printf "%.0f\\n", s + 0 }}')
if [ "$total" -gt {max_bytes} ]; then echo "{_OVERSIZE_MARKER} $total"; exit 0; fi
awk '{{ r = 5; if ($0 ~ /^keys\\//) r = 1; else if ($0 == "config") r = 2; \\
  else if ($0 ~ /^data\\//) r = 3; else if ($0 ~ /^index\\//) r = 4; print r, $0 }}' \\
  {paths.staging}/new.txt | LC_ALL=C sort | cut -d" " -f2- > {paths.staging}/order.txt
tar -cf {paths.staging}/egress-{tag}.tar -T {paths.staging}/order.txt
wc -c < {paths.staging}/egress-{tag}.tar
cat {paths.staging}/new.txt
"""
    result = await privileged_shell(env, script, user="root")
    if not result.success:
        raise RuntimeError(f"sandbox egress (build) failed: {result.stderr}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return _EgressBuild(new_files=[], tar_size=0)
    marker, _, total = lines[0].partition(" ")
    if marker == _OVERSIZE_MARKER:
        raise RuntimeError(
            f"sandbox egress (build): this cycle's new repo files total {total} "
            f"bytes, over the max_sandbox_snapshot_bytes cap of {max_bytes} bytes; "
            f"nothing was tarred"
        )
    try:
        tar_size = int(lines[0])
    except ValueError as exc:
        raise RuntimeError(
            f"sandbox egress (build): could not parse tar size from {lines[0]!r}"
        ) from exc
    return _EgressBuild(new_files=lines[1:], tar_size=tar_size)


def _scan_repo_files(dest_repo: str) -> set[str]:
    """Repo-relative paths of every file in ``dest_repo`` (observed on the host).

    Also removes ``*.partial`` residue a killed extraction may have left
    (restic ignores such files, but they would otherwise ride along to a
    remote destination).
    """
    files: set[str] = set()
    root = Path(dest_repo)
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        if entry.name.endswith(".partial"):
            entry.unlink(missing_ok=True)
            continue
        files.add(entry.relative_to(root).as_posix())
    return files


class _Extracted(NamedTuple):
    """What ``_extract_verified`` accepted from one cycle's tarball."""

    members: list[str]
    """Every validated member (sorted) — what the manifest advances by."""

    written: list[str]
    """The subset actually written to the destination this cycle."""


class _TarReader(io.BufferedReader):
    """Bound metadata reads before tarfile interprets untrusted headers.

    Each member's headers share a 64 KiB budget, including chained
    GNU/PAX headers and sparse maps. File contents are streamed separately
    under the extraction byte cap. Checking requested read sizes before
    delegating prevents a truncated extension from allocating its claimed
    size, even when the archive itself is tiny.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(io.FileIO(path, "r"))
        self._metadata_remaining: int | None = _MAX_TAR_METADATA_BYTES

    def read(self, size: int | None = -1) -> bytes:
        if self._metadata_remaining is not None and (
            size is None or size < 0 or size > self._metadata_remaining
        ):
            raise tarfile.ReadError("tar metadata exceeds the 64 KiB per-member limit")
        data = super().read(size)
        if self._metadata_remaining is not None:
            self._metadata_remaining -= len(data)
        return data

    @contextmanager
    def file_data(self) -> Iterator[None]:
        """Allow streamed file reads, then reset the next header's budget."""
        self._metadata_remaining = None
        try:
            yield
        finally:
            self._metadata_remaining = _MAX_TAR_METADATA_BYTES


def _extract_verified(
    tar_path: Path,
    staging_dir: str,
    *,
    existing_repo: str | None = None,
    new_files: Sequence[str],
    existing: Collection[str],
    first_cycle: bool,
    max_bytes: int,
    label: str,
) -> _Extracted:
    """Validate the egress tarball member by member into ``staging_dir``.

    ``staging_dir`` is a throwaway directory beside the accepted repo;
    validated new members land there, never in the accepted repo, so a
    later ``restic`` validation runs on a copy and the accepted repo is
    touched only once the whole transfer is accepted (see
    :func:`_build_validation_view` and :func:`_merge_into_repo`).
    ``existing_repo`` is the accepted repo an already-shipped member is
    checked against; it defaults to ``staging_dir`` for callers that
    extract straight into the target.

    Every member must pass ``tarfile.data_filter`` (path safety), be a
    regular file, match the restic layout, be listed in ``new_files``,
    and appear once (which bounds the member count by the diff list's
    length); the member set must equal ``new_files``; cumulative member
    bytes must stay within ``max_bytes``. Header processing is limited to
    64 KiB per member before tarfile can allocate from declared sizes.
    Each member streams through a hash to a temp name beside its
    destination and is renamed into place only if the hash equals its
    basename (``config`` excepted).
    New ``config``/``keys/*`` files are accepted only on the first
    cycle. A member already present in ``existing_repo`` is accepted
    without writing only when the shipped bytes are the existing bytes
    (both hash to the name; ``config`` contents compared by hash) — a
    re-ship after a failed phase-2 commit — and the existing file is
    never replaced.

    Matching a hash to a filename binds that name to those bytes; it
    does not authenticate their contents. The sandbox can supply
    arbitrary new contents under their matching hash-derived names.

    On any failure, every file this call wrote is removed before the
    error propagates, so ``staging_dir`` is left as it was found.
    """
    accepted_repo = existing_repo if existing_repo is not None else staging_dir
    expected = set(new_files)
    if len(expected) != len(new_files):
        raise EgressVerificationError(f"{label}: diff list contains duplicates")
    seen: set[str] = set()
    written: list[str] = []
    total = 0
    try:
        # One TarError mapping for the whole walk: a corrupt header
        # surfaces from iteration, truncated member data from the reads
        # inside the loop body. (FilterError is a TarError too, but
        # _check_member has already mapped it by the time it gets here.)
        try:
            with (
                _TarReader(tar_path) as reader,
                tarfile.open(fileobj=reader, mode="r:") as tar,
            ):
                for member in tar:
                    name = member.name
                    _check_member(member, staging_dir, expected, label)
                    if name in seen:
                        raise EgressVerificationError(
                            f"{label}: member {name!r} appears more than once"
                        )
                    seen.add(name)
                    total += member.size
                    if total > max_bytes:
                        raise EgressVerificationError(
                            f"{label}: extracted bytes would exceed the "
                            f"max_sandbox_snapshot_bytes cap of {max_bytes}"
                        )
                    src = tar.extractfile(member)
                    if src is None:
                        raise EgressVerificationError(
                            f"{label}: member {name!r} has no readable content"
                        )
                    with reader.file_data(), src:
                        if name in existing:
                            _accept_identical_reship(src, accepted_repo, name, label)
                        elif not first_cycle and name.startswith(_FIRST_CYCLE_ONLY):
                            raise EgressVerificationError(
                                f"{label}: member {name!r} is only accepted while "
                                f"the destination repo is uninitialized"
                            )
                        else:
                            _write_member(src, staging_dir, name, label)
                            written.append(name)
        except tarfile.TarError as exc:
            raise EgressVerificationError(
                f"{label}: unreadable tarball: {exc}"
            ) from exc
        missing = expected - seen
        if missing:
            raise EgressVerificationError(
                f"{label}: diff list names {len(missing)} file(s) absent from the "
                f"tarball, e.g. {sorted(missing)[:3]}"
            )
    except BaseException:
        _remove_files(staging_dir, written)
        raise
    return _Extracted(members=sorted(seen), written=written)


def _check_member(
    member: tarfile.TarInfo,
    dest_repo: str,
    expected: Collection[str],
    label: str,
) -> None:
    """Reject a member that fails path safety, layout, or diff-list checks."""
    name = member.name
    try:
        tarfile.data_filter(member, dest_repo)
    except tarfile.FilterError as exc:
        raise EgressVerificationError(
            f"{label}: unsafe member {name!r}: {exc}"
        ) from exc
    if not member.isreg():
        raise EgressVerificationError(f"{label}: member {name!r} is not a regular file")
    if not _MEMBER_RE.fullmatch(name) or (
        name.startswith("data/") and name.split("/")[1] != name.split("/")[2][:2]
    ):
        raise EgressVerificationError(
            f"{label}: member {name!r} is not a restic repository file"
        )
    if name not in expected:
        raise EgressVerificationError(
            f"{label}: member {name!r} is not in the sandbox's diff list"
        )


def _write_member(src: IO[bytes], dest_repo: str, name: str, label: str) -> None:
    """Stream ``src`` to ``dest_repo/name`` via a temp file, hashing in-flight.

    The rename happens only after the content hash matches the name
    (restic's content addressing; ``config`` is the one exception), so
    a mismatching member never appears at its final path.
    """
    final = Path(dest_repo) / name
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f"{final.name}.partial")
    digest = hashlib.sha256()
    try:
        with open(tmp, "wb") as out:
            while chunk := src.read(_HASH_CHUNK):
                digest.update(chunk)
                out.write(chunk)
        if name != "config" and digest.hexdigest() != final.name:
            raise EgressVerificationError(
                f"{label}: member {name!r} content hashes to {digest.hexdigest()}, "
                f"not to its name"
            )
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _accept_identical_reship(
    src: IO[bytes], dest_repo: str, name: str, label: str
) -> None:
    """Accept a member already in ``dest_repo`` only as a byte-identical no-op.

    Both the existing file and the shipped bytes must hash to the name;
    ``config`` is not content-addressed, so its shipped bytes must equal
    the existing bytes exactly. Nothing is written either way.
    """
    existing_path = Path(dest_repo) / name
    if name == "config":
        if _sha256_stream(src) != _sha256_file(existing_path):
            raise EgressVerificationError(
                f"{label}: member 'config' would overwrite the destination's "
                f"config with different content"
            )
        return
    basename = existing_path.name
    if _sha256_file(existing_path) != basename:
        raise EgressVerificationError(
            f"{label}: member {name!r} would overwrite an existing destination "
            f"file whose content does not match its name"
        )
    if _sha256_stream(src) != basename:
        raise EgressVerificationError(
            f"{label}: member {name!r} would overwrite an existing destination "
            f"file with different content"
        )


def _sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return _sha256_stream(f)


def _sha256_stream(src: IO[bytes]) -> str:
    digest = hashlib.sha256()
    while chunk := src.read(_HASH_CHUNK):
        digest.update(chunk)
    return digest.hexdigest()


def _remove_files(dest_repo: str, names: Sequence[str]) -> None:
    """Unwind ``names`` (in write order) from ``dest_repo``, last-written first.

    Reversing the tar order keeps the destination valid if this itself is
    killed mid-way: a snapshot never outlives its index and packs, and
    ``config`` (the first-cycle sentinel) goes before ``keys/*``, so the
    repo cannot be left with a config and no key.
    """
    for name in reversed(names):
        (Path(dest_repo) / name).unlink(missing_ok=True)


# Restic layout order: config + keys must precede the data they open,
# packs precede the indexes that map them, indexes precede the snapshots
# that reference them. Merging and unwinding in this order keep the
# accepted repo valid at every prefix.
_MERGE_RANK = {"keys": 1, "config": 2, "data": 3, "index": 4, "snapshots": 5}


def _merge_rank(name: str) -> int:
    if name == "config":
        return _MERGE_RANK["config"]
    return _MERGE_RANK.get(name.split("/", 1)[0], _MERGE_RANK["snapshots"])


def _try_link(src: Path, dst: Path) -> bool:
    """Hard-link ``src`` to ``dst`` (creating the parent); False if links are refused.

    For the throwaway validation view: a hard link is O(1) and shares the
    accepted file's inode, which is safe because the view is only read. A
    filesystem without hard links (exFAT/FAT, some CIFS and NFS mounts)
    refuses ``os.link`` with an ``OSError`` such as ``EPERM`` or ``ENOTSUP``;
    then the caller copies the file instead. ``FileExistsError`` is never
    swallowed — a name already present is a bug, not a missing feature.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        return False
    return True


def _publish_into(src: Path, dst: Path) -> None:
    """Publish ``src`` at ``dst`` in the accepted repo, never replacing a file.

    The fast path is a hard link, which is atomic and fails with
    ``FileExistsError`` rather than overwrite. Where the filesystem refuses
    links the file is copied to ``dst``'s ``.partial`` sibling and renamed
    into place, so the final name only ever holds a complete file and a
    hard kill mid-copy leaves a ``.partial`` that the next fire's
    ``_scan_repo_files`` sweeps. The no-overwrite rule is kept by refusing
    an existing ``dst`` before the rename (this sandbox is the only writer
    of its repo, so the check-then-rename is not racy). This copy is one
    validated file of this fire's increment, so it is bounded by the
    transfer cap; the merge as a whole runs in one worker-thread call and
    is cancelled only between fires (an interruption mid-merge is the
    safe-prefix case described in the module docstring).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
        return
    except FileExistsError:
        raise
    except OSError:
        pass
    if dst.exists():
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(dst))
    tmp = dst.with_name(f"{dst.name}.partial")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _link_view_batch(pairs: Sequence[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Link one batch into the view; return the pairs the filesystem refused."""
    return [(src, dst) for src, dst in pairs if not _try_link(src, dst)]


def _open_rb(path: Path) -> IO[bytes]:
    return open(path, "rb")


def _open_wb(path: Path) -> IO[bytes]:
    return open(path, "wb")


def _read_block(f: IO[bytes], size: int) -> bytes:
    return f.read(size)


async def _copy_file_interruptibly(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` in :data:`_VIEW_COPY_BLOCK` pieces.

    Each read and each write is its own worker-thread call, so a
    cancellation is honoured between blocks and waits for at most one block,
    whatever the file's size. A partially written ``dst`` is left in the
    view, which lives in scratch the caller sweeps.
    """
    fsrc = await anyio.to_thread.run_sync(_open_rb, src)
    try:
        fdst = await anyio.to_thread.run_sync(_open_wb, dst)
        try:
            while block := await anyio.to_thread.run_sync(
                _read_block, fsrc, _VIEW_COPY_BLOCK
            ):
                await anyio.to_thread.run_sync(fdst.write, block)
        finally:
            fdst.close()
    finally:
        fsrc.close()


async def _build_validation_view(
    view: Path,
    *,
    existing_repo: str,
    existing: Collection[str],
    staging: Path,
    written: Sequence[str],
) -> None:
    """Hard-link the accepted repo files plus this fire's additions into ``view``.

    ``view`` is a throwaway repository equal to the accepted repo as it
    stands plus the staged additions, so ``restic check``/``ls`` run
    against exactly what the accepted repo would become if this fire were
    merged — but on a copy, so a rejected fire never touched the accepted
    repo. Hard links keep it O(files), not O(bytes); the validation only
    reads the repo, so sharing inodes with the accepted files is safe. The
    accepted repo and the staging dir share one filesystem (staging is a
    sibling of the accepted repo), so every link resolves.

    A filesystem without hard links falls back to copying every file
    (:func:`_try_link` reports the refusal), which costs O(bytes of the
    whole accepted repo) in scratch space and I/O per fire — outside the
    per-transfer cap, since it scales with accumulated history rather than
    the increment.

    Cancellation (a sibling sandbox's failure, or the sample ending) is
    honoured at a bounded granularity in both modes, with no up-front pass
    over the repository: the ``(src, dst)`` pairs are produced lazily, one
    :data:`_VIEW_LINK_BATCH`-sized slice at a time (the view needs no
    particular order, so nothing is sorted or materialised whole), links are
    attempted one slice per worker-thread call, and a copy proceeds
    :data:`_VIEW_COPY_BLOCK` bytes per call
    (:func:`_copy_file_interruptibly`). So a cancellation waits for at most
    one slice of path construction plus one batch of links, or one block of
    one file — not for the repository's file count, not for the whole
    repository, and not for a whole staged file, which a hostile sandbox can
    make as large as the transfer cap. The caller's scratch sweep then
    removes what was built.
    """
    view.mkdir(parents=True, exist_ok=True)
    src_repo = Path(existing_repo)

    def pairs() -> Iterator[tuple[Path, Path]]:
        for rel in existing:
            yield src_repo / rel, view / rel
        for rel in written:
            yield staging / rel, view / rel

    remaining = pairs()
    while batch := list(islice(remaining, _VIEW_LINK_BATCH)):
        to_copy = await anyio.to_thread.run_sync(_link_view_batch, batch)
        for src, dst in to_copy:
            await _copy_file_interruptibly(src, dst)


def _merge_into_repo(dest_repo: str, staging: Path, written: Sequence[str]) -> None:
    """Publish this fire's validated new files into the accepted repo.

    Reached only once the temporary view validated, so the accepted repo
    gains only files ``restic check --read-data`` accepted. Files are
    published in restic-layout order (keys, config, packs, indexes,
    snapshots), each atomically (:func:`_publish_into`: a hard link, or a
    copy renamed into place where links are unsupported), so an
    interruption — including a hard kill, which cannot unwind — leaves the
    accepted repo valid at every prefix: a snapshot never appears before
    the index and packs it references, and ``config`` never before its
    key. A new member never collides with an accepted file (an identical
    re-ship is not in ``written``); a collision raises rather than
    overwrites, so an accepted file is never replaced. An ordinary failure
    unwinds this fire's files, last-published first, leaving the accepted
    repo unchanged.
    """
    dest = Path(dest_repo)
    ordered = sorted(written, key=lambda name: (_merge_rank(name), name))
    linked: list[str] = []
    try:
        for name in ordered:
            _publish_into(staging / name, dest / name)
            linked.append(name)
    except BaseException:
        for name in reversed(linked):
            (dest / name).unlink(missing_ok=True)
        raise


async def _snapshot_tags(
    host_restic: Path, dest_repo: str, password: str, *, no_cache: bool = False
) -> dict[str, list[str]]:
    """Full snapshot id → tags for every snapshot the destination lists."""
    snapshots: list[dict[str, Any]] = await list_snapshots(
        host_restic, dest_repo, password, no_cache=no_cache
    )
    return {snap["id"]: list(snap.get("tags") or []) for snap in snapshots}


async def _verify_fresh_snapshot(
    host_restic: Path,
    dest_repo: str,
    password: str,
    *,
    before_ids: Collection[str],
    written: Collection[str],
    snapshot_id: str,
    tag: str,
    label: str,
    no_cache: bool = False,
) -> str:
    """Check that the sandbox's reported snapshot arrived on the host.

    ``dest_repo`` is the repository whose snapshots are compared before
    and after the transfer — the validation view of the accepted
    repository plus the additions, so this runs before anything is
    merged. The added snapshots must be exactly those whose files the
    host just wrote. The snapshot reported by the sandbox must be one of
    them and have exactly the expected checkpoint tag.

    "New" means the snapshot id was absent from the host repository
    before this transfer, not that its contents are recent. The tag
    checks protocol consistency; it does not authenticate the capture.

    Extra snapshots may be leftovers from interrupted attempts or
    deliberately supplied by the sandbox. The host does not distinguish
    these cases. Accept these too, but do not record them in the
    checkpoint file. On resume, snapshots that no checkpoint file records
    are removed.

    Return the full id of the reported snapshot after these checks pass.
    """
    after = await _snapshot_tags(host_restic, dest_repo, password, no_cache=no_cache)
    lost = set(before_ids) - set(after)
    if lost:
        raise EgressVerificationError(
            f"{label}: destination no longer lists snapshot(s) {sorted(lost)}"
        )
    new_ids = set(after) - set(before_ids)
    shipped = {
        name.removeprefix("snapshots/")
        for name in written
        if name.startswith("snapshots/")
    }
    if new_ids != shipped:
        raise EgressVerificationError(
            f"{label}: destination gained snapshot(s) "
            f"{sorted(i[:8] for i in new_ids)} but this fire wrote snapshot "
            f"file(s) {sorted(i[:8] for i in shipped)}"
        )
    verified_id = match_snapshot_id(new_ids, snapshot_id)
    if verified_id is None:
        raise EgressVerificationError(
            f"{label}: reported snapshot {snapshot_id} is not among the "
            f"snapshot(s) the destination gained: {sorted(i[:8] for i in new_ids)}"
        )
    if after[verified_id] != [tag]:
        raise EgressVerificationError(
            f"{label}: snapshot {verified_id[:8]} carries tags "
            f"{after[verified_id]}, expected [{tag!r}]"
        )
    return verified_id


async def _validate_view(
    host_restic: Path,
    view: Path,
    password: str,
    *,
    before_ids: Collection[str],
    written: Collection[str],
    snapshot_id: str,
    tag: str,
    label: str,
) -> str:
    """Validate the temporary view before any file reaches the accepted repo.

    Three checks, cheapest first, each against the throwaway view:

    1. **Freshness** (``restic snapshots``): the view's snapshot set must
       be the accepted repo's plus exactly the snapshot files this fire
       shipped, the reported id must be one of them, and it must carry
       exactly this checkpoint's tag (:func:`_verify_fresh_snapshot`).
    2. **``restic ls <reported id>``**: the committed snapshot must be
       walkable — this loads every index and rejects a malformed or
       undecryptable one (the demonstrated poisoning) before the more
       expensive content read.
    3. **``restic check --read-data``**: reads and decrypts every pack the
       indexes reference and re-derives every blob, so a conflicting
       index that maps a blob to an attacker-supplied pack — which
       ``check`` without ``--read-data`` and ``ls`` both accept — is
       rejected here. Without it the accepted repo could gain a
       structurally valid addition that silently corrupts an earlier
       snapshot's restore.

    A failure of any check raises ``EgressVerificationError`` and the
    accepted repo is never touched (the caller merges only on success).
    Returns the reported snapshot's full id.

    All commands run ``--no-lock --no-cache``: the view shares the
    accepted repo's ``config`` id, so restic's repo-id-keyed cache would
    otherwise let a cached pack mask a staged file (and reorder the blob
    candidates a conflicting index competes in).
    """
    verified_id = await _verify_fresh_snapshot(
        host_restic,
        str(view),
        password,
        before_ids=before_ids,
        written=written,
        snapshot_id=snapshot_id,
        tag=tag,
        label=label,
        no_cache=True,
    )
    await _run_view_restic(
        host_restic,
        ["ls", verified_id],
        view,
        password,
        label=label,
        what=f"listing snapshot {verified_id[:8]}",
    )
    await _run_view_restic(
        host_restic,
        ["check", "--read-data"],
        view,
        password,
        label=label,
        what="content check",
    )
    return verified_id


async def _run_view_restic(
    host_restic: Path,
    args: Sequence[str],
    view: Path,
    password: str,
    *,
    label: str,
    what: str,
) -> None:
    """Run a read-only restic command against the validation view.

    A non-zero exit is a rejected transfer, not a host error: the view is
    built from sandbox-supplied bytes, so a failure here means the
    additions are inconsistent with the accepted repo.

    The process's output is attacker-shaped too — one forged index can make
    restic print megabytes of diagnostics — so neither pipe is buffered
    whole: stdout (progress) is drained and dropped, and only the first
    :data:`_MAX_VIEW_STDERR_BYTES` of stderr are kept for the error, with a
    marker when more was cut. Memory is bounded by one pipe chunk plus
    that cap, whatever the view makes restic say. A cancellation or
    failure while the child runs kills it before propagating, so no restic
    outlives the fire.
    """
    command = [str(host_restic), "-r", str(view), *args, "--no-lock", "--no-cache"]
    stderr = bytearray()
    truncated = False
    async with await anyio.open_process(
        command,
        env=restic_env(password),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        assert proc.stdout is not None and proc.stderr is not None
        stdout_stream, stderr_stream = proc.stdout, proc.stderr

        async def drain_stdout() -> None:
            async for _ in stdout_stream:
                pass

        async def drain_stderr() -> None:
            nonlocal truncated
            async for chunk in stderr_stream:
                room = _MAX_VIEW_STDERR_BYTES - len(stderr)
                if room > 0:
                    stderr.extend(chunk[:room])
                if len(chunk) > room:
                    truncated = True

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(drain_stdout)
                tg.start_soon(drain_stderr)
        except BaseException:
            _kill(proc)
            raise
        returncode = await proc.wait()
    if returncode != 0:
        detail = stderr.decode(errors="replace").strip()
        if truncated:
            detail += f" [stderr truncated to {_MAX_VIEW_STDERR_BYTES} bytes]"
        raise EgressVerificationError(
            f"{label}: the received repository files failed validation "
            f"({what}) against a view of the accepted repository: {detail}"
        )


async def _commit_egress(
    env: SandboxEnvironment, tag: str, members: Sequence[str], paths: _SandboxPaths
) -> None:
    """Phase 2 (in-sandbox): advance the manifest, drop the tarball.

    Ask the sandbox to mark the accepted files as shipped. This supports
    retries when the sandbox follows the protocol; the sandbox can modify
    its own manifest, so the host does not rely on it as evidence of prior
    receipt.
    """
    script = f"""\
set -e
cat {paths.manifest} - | LC_ALL=C sort -u > {paths.manifest}.tmp
mv {paths.manifest}.tmp {paths.manifest}
rm -f {paths.staging}/egress-{tag}.tar {paths.staging}/chunk
"""
    result = await privileged_shell(
        env, script, input="\n".join(members) + "\n", user="root"
    )
    if not result.success:
        raise RuntimeError(f"sandbox egress (commit) failed: {result.stderr}")
