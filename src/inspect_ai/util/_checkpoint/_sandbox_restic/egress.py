"""Sandbox→host restic repo egress + host→sandbox ingress.

Per Appendix B of the working doc: each cycle, ship newly-written pack
files (and on the first cycle, ``config`` + ``keys/*``) from the in-sandbox
buffer to the destination repo via a manifest-based diff and a two-phase
commit. The destination is *not* pre-initialized — the first cycle's
tarball carries ``config``+``keys/*``, which makes the destination a
valid restic repo on extraction.

Everything the sandbox reports on this path — the diff list, the tar,
the tar's size, the backup's snapshot id — is untrusted: where the
sandbox default user is root the agent controls all of it directly, and
the container owns its own filesystem, so a "forged" snapshot of its
own state is indistinguishable from a real one. What the host verifies
is therefore the narrower set of properties it *can* establish from
host-side truth, and it establishes each of them from state it
observed itself:

- **Committed history is immutable.** A member may not replace a file
  already in the destination (an identical re-ship after a failed
  phase-2 commit is tolerated: both copies must hash to the name, and
  the existing bytes are left untouched). Restic names ``data/``,
  ``index/``, ``snapshots/`` and ``keys/`` files by the SHA-256 of their
  content, and every such member must hash to its own name — so
  rewriting history would take a SHA-256 collision, whatever the
  container ships. ``config`` (not content-addressed) and ``keys/*`` are
  accepted only while the destination has no ``config`` yet.
- **The member set is exactly the diff list**, every member a regular
  file in the restic layout (``filter="data"`` stays as the path-safety
  layer beneath the layout check), so a ``ckpt-N.json`` that names a
  snapshot means exactly the files this fire accepted were added.
- **Freshness, not membership.** The destination's snapshot-id set must
  grow by exactly the reported id, and that snapshot's tags must be
  exactly this cycle's tag. Injected extra snapshots and replayed old
  ids both fail. The host-verified full id is what the strategy
  records.
- **A fire that captured nothing is an error.** A restic backup always
  writes a new ``snapshots/`` file, so an honest post-backup diff is
  never empty; an empty one is a protocol violation, not a no-op.
- **The transfer is bounded** by ``max_bytes`` on bytes actually read
  (see :mod:`.._copy`), and extraction bounds member count (the diff
  list's length, itself bounded by the tar cap) and cumulative bytes.

Any failure after extraction begins rolls back the files this fire
wrote, so the destination is unchanged and the in-sandbox manifest —
advanced only in phase 2, from the host-validated member list — still
lists the files as unshipped for the next fire.

Ingress is the inverse: on resume, copy a host-side repo back into the
sandbox and restic-restore the recorded snapshot at its original
absolute paths.

Layout under the same ``/root/.cache/inspect/`` root as :mod:`.repo`:
- ``./egress-manifest.txt`` — sorted list of files already shipped
- ``./staging/`` — per-cycle tarballs awaiting host-side extraction
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tarfile
from collections.abc import Collection, Iterator, Sequence
from functools import partial
from pathlib import Path
from typing import IO, Any, NamedTuple

import anyio

from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._async_fs import async_mkdir
from .._copy import DEFAULT_COPY_CHUNK_SIZE, copy_out
from .._repo_ops import SNAPSHOT_ID_RE, list_snapshots, match_snapshot_id
from .repo import _SANDBOX_RESTIC_DIR

_HEX64 = r"[0-9a-f]{64}"
_MEMBER_RE = re.compile(
    rf"^(?:config|keys/{_HEX64}|data/[0-9a-f]{{2}}/{_HEX64}|index/{_HEX64}"
    rf"|snapshots/{_HEX64})$"
)
"""The restic repo layout: the only member names egress accepts."""

_FIRST_CYCLE_ONLY = ("config", "keys/")
_HASH_CHUNK = 1024 * 1024


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
    snapshot_id: str | None = None,
    *,
    sandbox_dir: str = _SANDBOX_RESTIC_DIR,
) -> None:
    """Copy a host-side restic repo into the sandbox + restore from it.

    Inverse of :func:`egress_sandbox`. Used on resume:

    1. Tar the host-side repo dir (whose contents were FS-copied from
       the prior eval's host side just before this call).
    2. Stream the tarball into the sandbox via root ``sh`` so the agent
       never sees the bytes in flight, extracting into the standard
       in-sandbox repo location (``/root/.cache/inspect/repo``).
    3. Run ``restic restore <snapshot_id> --target /`` inside the
       sandbox so restored files land at their original absolute paths,
       replacing whatever the fresh sandbox came up with.
       ``snapshot_id`` is the latest committed checkpoint's recorded
       (host-verified) id; ``None`` restores ``latest`` — the degenerate
       resume with no committed record for this sandbox.

    Egress's two-phase manifest is reseeded by writing a manifest line
    for every file in the freshly-populated repo, so the next fire's
    diff treats the inherited snapshots as already-shipped.
    """
    src = Path(src_repo)
    if not src.is_dir():
        raise RuntimeError(
            f"resume: expected sandbox repo at {src}, but it doesn't exist"
        )
    if snapshot_id is not None and not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise RuntimeError(
            f"resume: checkpoint record has malformed sandbox snapshot id "
            f"{snapshot_id!r}"
        )
    paths = _sandbox_paths(sandbox_dir)

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
    result = await env.exec(["sh", "-c", extract_script], input=tar_bytes, user="root")
    if not result.success:
        raise RuntimeError(f"Failed to ingress sandbox restic repo: {result.stderr}")

    restore = await env.exec(
        [
            paths.restic,
            "-r",
            paths.repo,
            "restore",
            snapshot_id if snapshot_id is not None else "latest",
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
    max_bytes: int,
    chunk_size: int = DEFAULT_COPY_CHUNK_SIZE,
    dd_fullblock: bool = False,
    sandbox_dir: str = _SANDBOX_RESTIC_DIR,
) -> str:
    """Ship new pack files from the in-sandbox buffer to ``dest_repo``.

    ``tag`` names the per-cycle staging tarball and must be unique per
    cycle; it is also the tag the backup that immediately preceded this
    call carried, and ``snapshot_id`` is the id that backup reported.
    Both are verified against the destination — see the module
    docstring for the full set of host-side checks — and the
    host-verified full snapshot id is returned for the caller to
    record. ``max_bytes`` caps the tarball transfer and the bytes
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

    build = await _build_egress_tar(env, tag, paths)
    if not build.new_files:
        raise EgressVerificationError(
            f"{label}: sandbox reported an empty diff after a backup; a restic "
            f"backup always writes a new snapshot file, so nothing to ship is a "
            f"protocol violation, not a no-op"
        )

    # Host scratch copy of the tarball: beside (not inside) the repo so
    # nothing partial ever sits where restic would see it. Residue from an
    # interrupted fire (any tag) is swept first so it never rides along
    # with the next host egress to a remote destination.
    dest_path = Path(dest_repo)
    for stale in dest_path.parent.glob(f".egress-{dest_path.name}-*"):
        stale.unlink(missing_ok=True)
    tar_host = dest_path.parent / f".egress-{dest_path.name}-{tag}.tar"
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
    try:
        extracted = await anyio.to_thread.run_sync(
            partial(
                _extract_verified,
                tar_host,
                dest_repo,
                new_files=build.new_files,
                existing=before_files,
                first_cycle=first_cycle,
                max_bytes=max_bytes,
                label=label,
            )
        )
    finally:
        tar_host.unlink(missing_ok=True)

    try:
        verified_id = await _verify_fresh_snapshot(
            host_restic,
            dest_repo,
            password,
            before_ids=before_ids,
            snapshot_id=snapshot_id,
            tag=tag,
            label=label,
        )
    except BaseException:
        # Shielded so a cancellation arriving during verification still
        # rolls the destination back (a cancelled scope would otherwise
        # abort the rollback's own await).
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(_remove_files, dest_repo, extracted.written)
        raise

    await _commit_egress(env, tag, extracted.members, paths)
    return verified_id


class _EgressBuild(NamedTuple):
    """Phase 1's sandbox-reported result (advisory: verified host-side)."""

    new_files: list[str]
    """Repo-relative paths the sandbox staged into this cycle's tarball."""

    tar_size: int
    """The tarball's size in bytes as the sandbox reports it."""


async def _build_egress_tar(
    env: SandboxEnvironment, tag: str, paths: _SandboxPaths
) -> _EgressBuild:
    """Phase 1 (in-sandbox): diff vs manifest, build tarball.

    Returns the sandbox-reported list of newly-staged file paths
    (relative to the repo root) and tarball size. An empty list means
    the sandbox produced no tar — which, after a backup, the caller
    treats as an error.

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
cd {paths.repo}
mkdir -p {paths.staging}
touch {paths.manifest}
# Drop any orphan tarballs (and copy-out chunks) from prior cycles whose
# phase-2 commit failed — their content is regenerated by this cycle's diff.
rm -f {paths.staging}/egress-*.tar {paths.staging}/chunk
{{
  find config -type f 2>/dev/null
  find keys -type f 2>/dev/null
  find data -type f 2>/dev/null
  find index -type f 2>/dev/null
  find snapshots -type f 2>/dev/null
}} | LC_ALL=C sort > {paths.staging}/current.txt
LC_ALL=C comm -23 {paths.staging}/current.txt {paths.manifest} > {paths.staging}/new.txt
if [ ! -s {paths.staging}/new.txt ]; then exit 0; fi
tar -cf {paths.staging}/egress-{tag}.tar -T {paths.staging}/new.txt
wc -c < {paths.staging}/egress-{tag}.tar
cat {paths.staging}/new.txt
"""
    result = await env.exec(["sh", "-c", script], user="root")
    if not result.success:
        raise RuntimeError(f"sandbox egress (build) failed: {result.stderr}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return _EgressBuild(new_files=[], tar_size=0)
    try:
        tar_size = int(lines[0])
    except ValueError as exc:
        raise RuntimeError(
            f"sandbox egress (build): could not parse tar size from {lines[0]!r}"
        ) from exc
    return _EgressBuild(new_files=lines[1:], tar_size=tar_size)


def _scan_repo_files(dest_repo: str) -> set[str]:
    """Repo-relative paths of every file in ``dest_repo`` (host truth).

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


def _extract_verified(
    tar_path: Path,
    dest_repo: str,
    *,
    new_files: Sequence[str],
    existing: Collection[str],
    first_cycle: bool,
    max_bytes: int,
    label: str,
) -> _Extracted:
    """Validate and extract the egress tarball member by member.

    Every member must pass ``tarfile.data_filter`` (path safety), be a
    regular file, match the restic layout, be listed in ``new_files``,
    and appear once (which bounds the member count by the diff list's
    length); the member set must equal ``new_files``; cumulative member
    bytes must stay within ``max_bytes``. Each member streams through a
    hash to a temp name beside its destination and is renamed into
    place only if the hash equals its basename (``config`` excepted).
    New ``config``/``keys/*`` files are accepted only on the first
    cycle. A member already present in ``dest_repo`` is accepted
    without writing only when the shipped bytes are the existing bytes
    (both hash to the name; ``config`` compared byte-for-byte) — a
    re-ship after a failed phase-2 commit — and the existing file is
    never replaced.

    On any failure, every file this call wrote is removed before the
    error propagates, so ``dest_repo`` is left as it was found.
    """
    expected = set(new_files)
    if len(expected) != len(new_files):
        raise EgressVerificationError(f"{label}: diff list contains duplicates")
    seen: set[str] = set()
    written: list[str] = []
    total = 0
    try:
        try:
            tar = tarfile.open(tar_path, mode="r:")
        except tarfile.TarError as exc:
            raise EgressVerificationError(
                f"{label}: unreadable tarball: {exc}"
            ) from exc
        with tar:
            for member in _iter_members(tar, label):
                name = member.name
                _check_member(member, dest_repo, expected, label)
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
                with src:
                    if name in existing:
                        _accept_identical_reship(src, dest_repo, name, label)
                    elif not first_cycle and name.startswith(_FIRST_CYCLE_ONLY):
                        raise EgressVerificationError(
                            f"{label}: member {name!r} is only accepted while the "
                            f"destination repo is uninitialized"
                        )
                    else:
                        _write_member(src, dest_repo, name, label)
                        written.append(name)
        missing = expected - seen
        if missing:
            raise EgressVerificationError(
                f"{label}: diff list names {len(missing)} file(s) absent from the "
                f"tarball, e.g. {sorted(missing)[:3]}"
            )
    except BaseException:
        _remove_files(dest_repo, written)
        raise
    return _Extracted(members=sorted(seen), written=written)


def _iter_members(tar: tarfile.TarFile, label: str) -> Iterator[tarfile.TarInfo]:
    """Iterate ``tar``'s members, surfacing a corrupt archive as a verification error."""
    try:
        yield from tar
    except tarfile.TarError as exc:
        raise EgressVerificationError(f"{label}: unreadable tarball: {exc}") from exc


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


def _remove_files(dest_repo: str, names: Collection[str]) -> None:
    for name in names:
        (Path(dest_repo) / name).unlink(missing_ok=True)


async def _snapshot_tags(
    host_restic: Path, dest_repo: str, password: str
) -> dict[str, list[str]]:
    """Full snapshot id → tags for every snapshot the destination lists."""
    snapshots: list[dict[str, Any]] = await list_snapshots(
        host_restic, dest_repo, password
    )
    return {snap["id"]: list(snap.get("tags") or []) for snap in snapshots}


async def _verify_fresh_snapshot(
    host_restic: Path,
    dest_repo: str,
    password: str,
    *,
    before_ids: Collection[str],
    snapshot_id: str,
    tag: str,
    label: str,
) -> str:
    """Require the destination's snapshot set to have grown by exactly one.

    The one new snapshot must be the reported ``snapshot_id`` and carry
    exactly ``[tag]``. Returns its full id — the host-verified value the
    checkpoint file records.
    """
    after = await _snapshot_tags(host_restic, dest_repo, password)
    lost = set(before_ids) - set(after)
    if lost:
        raise EgressVerificationError(
            f"{label}: destination no longer lists snapshot(s) {sorted(lost)}"
        )
    new_ids = sorted(set(after) - set(before_ids))
    if len(new_ids) != 1:
        raise EgressVerificationError(
            f"{label}: expected the destination to gain exactly one snapshot, "
            f"found {len(new_ids)} new: {[i[:8] for i in new_ids]}"
        )
    (new_id,) = new_ids
    if match_snapshot_id([new_id], snapshot_id) is None:
        raise EgressVerificationError(
            f"{label}: destination gained snapshot {new_id}, not the reported "
            f"{snapshot_id}"
        )
    if after[new_id] != [tag]:
        raise EgressVerificationError(
            f"{label}: snapshot {new_id[:8]} carries tags {after[new_id]}, "
            f"expected [{tag!r}]"
        )
    return new_id


async def _commit_egress(
    env: SandboxEnvironment, tag: str, members: Sequence[str], paths: _SandboxPaths
) -> None:
    """Phase 2 (in-sandbox): advance the manifest, drop the tarball.

    ``members`` is the host-validated member list, so the manifest can
    only advance by files the host actually accepted.
    """
    script = f"""\
set -e
cat {paths.manifest} - | LC_ALL=C sort -u > {paths.manifest}.tmp
mv {paths.manifest}.tmp {paths.manifest}
rm -f {paths.staging}/egress-{tag}.tar {paths.staging}/chunk
"""
    result = await env.exec(
        ["sh", "-c", script],
        input="\n".join(members) + "\n",
        user="root",
    )
    if not result.success:
        raise RuntimeError(f"sandbox egress (commit) failed: {result.stderr}")
