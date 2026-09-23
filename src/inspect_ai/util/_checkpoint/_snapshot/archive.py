"""``archive``: one complete compressed tar per checkpoint.

Captures with tools already present in effectively every image (tar,
dd, sha256sum, zstd or gzip) — nothing is injected into the sandbox,
unlike restic. Each checkpoint's archive is self-contained: restore
reads one file, and ``discard_orphans`` is one file-delete per
checkpoint. Self-contained archives also make mid-run storage
reclamation possible (deleting an old checkpoint's data is a plain
file delete, where restic's shared pack files can never be reclaimed);
a retention policy exposing that is designed (§4.4) but not yet
offered.

Capture mechanics (design §7.2/§8, first implementation):

- The archive is produced complete inside the sandbox's root-only
  staging area, then copied out in fixed-size chunks (``dd`` per chunk
  + ``read_file``; the shared ``_copy.copy_out`` primitive). Chunking
  limits buffering when the sandbox follows the protocol; it does not
  bound staging inside ``read_file``. The transfer is capped by ``SnapshotContext.max_snapshot_bytes`` against the bytes
  actually read. Transient sandbox disk equals the archive size plus
  one chunk; the §8 detached-producer pipeline that bounds sandbox
  disk to ~two chunks is a compatible follow-up (same storage layout
  and recorded details).
- Each snapshot stages in its own ``ckpt-NNNNN`` subdirectory and
  ``snapshot()`` begins by deleting the staging root, so residue from
  an interrupted fire can never corrupt the next one (§4.2). There is
  no detached producer in this implementation, so cleanup is a plain
  delete.
- The host compares the received bytes' SHA-256 digest with the digest
  reported by the sandbox. This detects mismatches, such as accidental
  corruption during copying. A compromised sandbox can supply matching
  bytes and a matching digest; agreement does not authenticate the
  archive. On restore the host walks the archive's member headers
  first (``_check_archive``): every member must lie at or under one of
  this attempt's capture roots, be a regular file, directory, symlink
  or in-scope hard link, carry no PAX records, and (a regular file) no
  setuid/setgid/sticky bit; the raw header stream may hold no PAX,
  sparse, device or fifo header and at most one GNU long-name and one
  long-link header per member; the compressed payload is decoded the way
  the sandbox decodes it (every gzip member, every zstd frame); nothing
  but zero padding may follow the last member ``tarfile`` parsed; and
  the bytes must hash to the recorded digest — all before any of it is
  copied in. Every symlink the image left under a root is already gone
  (the core runs ``_restore_scope.remove_existing_symlinks`` before
  ``setup``), so no member is written, or hard-linked, through one into
  a path outside the root. Extraction names the roots as tar member
  arguments so only they are written, and a ``find`` over the roots
  afterwards fails the restore if the sandbox's tar nonetheless produced
  a special file or device node
  (``_restore_scope.find_special_nodes_command``) — the layer that does
  not depend on ``tarfile`` and the image's tar agreeing on member
  boundaries. A second digest check runs inside the sandbox before
  extraction; it detects corruption in transit when that sandbox
  follows the protocol and cannot constrain one controlled by the agent.
- Compression is zstd when available in the sandbox, else gzip
  (present in effectively every image, busybox included) — the
  archive is always compressed. ``setup`` probes and records the
  compressor; ``restore`` infers the decompressor from the file
  extension so mixed lineages never arise.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import shlex
import tarfile
import time
import zlib
from collections.abc import Callable, Sequence
from functools import partial
from logging import getLogger
from pathlib import Path
from typing import Protocol

import anyio
import zstandard
from typing_extensions import Buffer

from inspect_ai.util._sandbox._privileged import privileged_shell
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._copy import DD_FULLBLOCK_PROBE, DEFAULT_COPY_CHUNK_SIZE, copy_out
from .._layout.schemas import SnapshotDetails
from .._repo_ops import checkpoint_tag
from .._restore_scope import (
    RestoreRoots,
    RestoreScopeError,
    TarHeaderScan,
    check_recorded_roots,
    find_special_nodes_command,
    tar_member_argument,
    tar_member_node,
)
from .._sandbox_dir import ensure_root_sandbox_dir
from ..sandbox_paths import SandboxBackupPaths
from .types import (
    CommittedSnapshot,
    SandboxSnapshotStrategy,
    SnapshotContext,
)

logger = getLogger(__name__)

_DEFAULT_SANDBOX_DIR = "/root/.cache/inspect"
"""Root-only (0700) in-sandbox area shared with the restic tooling: the
parent is unlistable by the agent and ``.cache`` falls inside the
always-on capture exclude, so staging never captures itself."""

_DEFAULT_CHUNK_SIZE = DEFAULT_COPY_CHUNK_SIZE

_TAIL_READ_SIZE = 1024 * 1024
"""Chunk size for reading past the last tar member (padding check, digest)."""

_ARCHIVE_NAME_RE = re.compile(r"ckpt-\d{5,}\.tar\.(?:zst|gz)")
"""The exact archive filename form ``snapshot()`` generates — also the
shell-safety gate for names interpolated into ``restore``'s root scripts."""


class ArchiveStrategy(SandboxSnapshotStrategy):
    """Complete compressed tar archive per checkpoint."""

    name = "archive"

    def __init__(
        self,
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        sandbox_dir: str = _DEFAULT_SANDBOX_DIR,
    ) -> None:
        self._chunk_size = chunk_size
        self._sandbox_dir = sandbox_dir
        self._staging_root = f"{sandbox_dir}/snapshot-staging"
        self._compressor: str | None = None
        self._dd_fullblock = False

    async def setup(self, env: SandboxEnvironment, ctx: SnapshotContext) -> None:
        """Probe required tools and pick the compressor.

        Prepares the root-only work area first (which needs ``stat`` and
        ``id`` in the image; see :func:`ensure_root_sandbox_dir`), then
        verifies ``tar``, ``sha256sum``, and ``dd`` (so a missing tool
        fails at provisioning rather than at first fire or restore), and
        records zstd vs. the gzip fallback for this sandbox. Also probes
        ``dd iflag=fullblock`` (GNU/busybox), which
        copy-out uses when available to defeat short reads — BSD ``dd``
        lacks it, and the copy-out digest check still catches any
        short-read desync loudly. Nothing is injected.
        """
        await ensure_root_sandbox_dir(env, self._sandbox_dir)
        script = (
            "set -e; "
            "for tool in tar sha256sum dd; do "
            'command -v "$tool" >/dev/null 2>&1 || '
            '{ echo "missing required tool: $tool" >&2; exit 1; }; done; '
            f"if {DD_FULLBLOCK_PROBE}; then echo fullblock; fi; "
            "if command -v zstd >/dev/null 2>&1; then echo zstd; "
            "elif command -v gzip >/dev/null 2>&1; then echo gzip; "
            'else echo "missing required tool: zstd or gzip" >&2; exit 1; fi'
        )
        result = await privileged_shell(env, script, user="root")
        if not result.success:
            raise RuntimeError(
                f"archive snapshot setup failed for sandbox "
                f"{ctx.sandbox_name!r}: {result.stderr}"
            )
        lines = result.stdout.strip().splitlines()
        self._dd_fullblock = "fullblock" in lines
        self._compressor = lines[-1]

    async def snapshot(
        self,
        env: SandboxEnvironment,
        paths: SandboxBackupPaths,
        checkpoint_id: int,
        ctx: SnapshotContext,
    ) -> SnapshotDetails:
        if self._compressor is None:
            raise RuntimeError("archive snapshot: setup() did not run")
        start = time.monotonic()
        tag = checkpoint_tag(checkpoint_id)
        staging = f"{self._staging_root}/{tag}"
        ext = "tar.zst" if self._compressor == "zstd" else "tar.gz"
        archive_name = f"{tag}.{ext}"
        archive = f"{staging}/{archive_name}"
        compress = "zstd -q" if self._compressor == "zstd" else "gzip"

        size, sandbox_digest = await self._create_archive(
            env, ctx, paths, staging=staging, archive=archive, compress=compress
        )
        local_path = Path(ctx.storage_dir) / archive_name
        try:
            await copy_out(
                env,
                src=archive,
                chunk_path=f"{staging}/chunk",
                size=size,
                dest=local_path,
                max_bytes=ctx.max_snapshot_bytes,
                label=f"archive snapshot copy-out for sandbox {ctx.sandbox_name!r}",
                chunk_size=self._chunk_size,
                dd_fullblock=self._dd_fullblock,
                expected_sha256=sandbox_digest,
            )
        finally:
            await self._clean_staging(env)

        # `strategy`, `roots` and the archive metadata ride as extra fields
        # (see `snapshot_strategy_name` and `_restore_scope.recorded_roots`).
        return SnapshotDetails.model_validate(
            dict(
                snapshot_id=tag,
                size_bytes=size,
                duration_ms=int((time.monotonic() - start) * 1000),
                strategy=self.name,
                archive=archive_name,
                content_sha256=sandbox_digest,
                roots=list(paths.include),
            )
        )

    async def _create_archive(
        self,
        env: SandboxEnvironment,
        ctx: SnapshotContext,
        paths: SandboxBackupPaths,
        *,
        staging: str,
        archive: str,
        compress: str,
    ) -> tuple[int, str]:
        """Produce the complete archive in staging; return (size, sha256).

        Deleting the staging root first is the cross-fire isolation
        step (§4.2): an interrupted fire's residue — including a retry
        of the same reused checkpoint id — can never leak into this
        stream. tar's own exit status is captured through the pipe via
        fd 3 (a plain ``tar | compress`` pipeline in POSIX sh reports
        only the compressor's status); exit 1 (file changed while
        reading — expected on a live sandbox) is tolerated, anything
        higher is fatal.
        """
        excludes = " ".join(
            shlex.quote(f"--exclude={_tar_pattern(p)}")
            for p in [*paths.exclude, self._sandbox_dir]
        )
        includes = " ".join(shlex.quote(p) for p in paths.include)
        # `set +e` is scoped to the left pipeline subshell: without it,
        # dash/ash abort that subshell on tar's non-zero exit before the
        # fd-3 echo runs, losing the status (bash-as-sh happens to keep
        # going). A compressor failure still aborts via the pipeline's
        # exit status and the outer `set -e`.
        script = (
            "set -e\n"
            f"rm -rf {self._staging_root}\n"
            f"mkdir -p {staging}\n"
            f"rc=$( {{ {{ set +e; tar -cf - {excludes} {includes}; echo $? >&3; }} "
            f"| {compress} > {archive}; }} 3>&1 )\n"
            f'[ -n "$rc" ] && [ "$rc" -le 1 ] || '
            f'{{ echo "tar failed with exit status $rc" >&2; exit 1; }}\n'
            f"wc -c < {archive}\n"
            f"sha256sum {archive}\n"
        )
        result = await privileged_shell(env, script, user="root")
        if not result.success:
            raise RuntimeError(
                f"archive snapshot failed for sandbox {ctx.sandbox_name!r}: "
                f"{result.stderr}"
            )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        try:
            size = int(lines[-2])
            digest = lines[-1].split()[0]
        except (IndexError, ValueError) as exc:
            raise RuntimeError(
                f"archive snapshot for sandbox {ctx.sandbox_name!r}: could not "
                f"parse size/digest from output: {result.stdout!r}"
            ) from exc
        return size, digest

    async def restore(
        self,
        env: SandboxEnvironment,
        paths: SandboxBackupPaths,
        ref: SnapshotDetails,
        ctx: SnapshotContext,
    ) -> None:
        label = f"archive snapshot restore for sandbox {ctx.sandbox_name!r}"
        roots = RestoreRoots.from_include(paths.include, label=label)
        check_recorded_roots(ref, roots, label=label)
        extra = ref.model_extra or {}
        archive_name = extra.get("archive")
        expected_digest = extra.get("content_sha256")
        if not isinstance(archive_name, str) or not isinstance(expected_digest, str):
            raise RuntimeError(
                f"{label}: checkpoint record for {ref.snapshot_id} lacks archive "
                f"metadata (archive/content_sha256)"
            )
        # `archive_name` is joined into a host path and interpolated into
        # root shell scripts below. Require the filename form generated
        # by `snapshot()` so a malformed record fails before becoming a
        # path-traversal or shell-injection surface (or a confusing
        # shell error).
        if not _ARCHIVE_NAME_RE.fullmatch(archive_name):
            raise RuntimeError(
                f"{label}: checkpoint record for {ref.snapshot_id} has malformed "
                f"archive name {archive_name!r}"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise RuntimeError(
                f"{label}: checkpoint record for {ref.snapshot_id} has malformed "
                f"content_sha256 {expected_digest!r}"
            )
        local_path = Path(ctx.storage_dir) / archive_name
        if not local_path.is_file():
            raise RuntimeError(
                f"{label}: expected archive at {local_path}, but it doesn't exist"
            )
        # Threaded: this decompresses and walks the whole archive on the
        # host. Nothing has been sent to the sandbox yet, so a refused
        # archive leaves it untouched.
        await anyio.to_thread.run_sync(
            partial(_check_archive, local_path, roots, expected_digest, label=label)
        )

        staging = f"{self._staging_root}/restore"
        staged = f"{staging}/{archive_name}"
        await ensure_root_sandbox_dir(env, self._sandbox_dir)
        init = await privileged_shell(
            env,
            f"set -e; rm -rf {self._staging_root}; mkdir -p {staging}",
            user="root",
        )
        if not init.success:
            raise RuntimeError(
                f"archive snapshot restore staging failed for sandbox "
                f"{ctx.sandbox_name!r}: {init.stderr}"
            )

        # Chunked host → sandbox copy: `exec` takes fully materialized
        # input bytes, so streaming the whole archive through one exec
        # would buffer it entirely in host RAM (and can exceed per-call
        # provider limits) — the copy-out problem in reverse.
        with open(local_path, "rb") as f:
            first = True
            while True:
                data = f.read(self._chunk_size)
                if not data:
                    break
                redirect = ">" if first else ">>"
                result = await privileged_shell(
                    env, f"cat {redirect} {staged}", input=data, user="root"
                )
                if not result.success:
                    raise RuntimeError(
                        f"archive snapshot restore copy-in failed for sandbox "
                        f"{ctx.sandbox_name!r}: {result.stderr}"
                    )
                first = False

        # Verify-then-extract: a corrupt archive is rejected before any
        # byte reaches a final path. Extraction names each capture root
        # as a member argument, so
        # tar writes only members at or under a root — the second layer
        # behind the host-side listing check. The find afterwards is the
        # third: whatever this tar made of the member boundaries, a
        # special file or device node under a root fails the restore
        # (the sandbox is discarded on failure).
        members = " ".join(
            shlex.quote(tar_member_argument(root)) for root in roots.roots
        )
        extract = (
            f"zstd -dc {staged} | tar -xf - -C / -- {members}"
            if archive_name.endswith(".tar.zst")
            else f"tar -xzf {staged} -C / -- {members}"
        )
        script = (
            "set -e\n"
            f'digest=$(sha256sum {staged} | cut -d" " -f1)\n'
            f'[ "$digest" = "{expected_digest}" ] || '
            f'{{ echo "archive digest mismatch: $digest != {expected_digest}" >&2; '
            f"exit 1; }}\n"
            f"{extract}\n"
            f"bad=$({find_special_nodes_command(roots.roots)})\n"
            f'[ -z "$bad" ] || {{ echo "extraction produced $bad: a setuid, setgid '
            f'or sticky regular file, or a fifo or device node" >&2; exit 1; }}\n'
            f"rm -rf {self._staging_root}\n"
        )
        result = await privileged_shell(env, script, user="root")
        if not result.success:
            raise RuntimeError(
                f"archive snapshot restore failed for sandbox "
                f"{ctx.sandbox_name!r}: {result.stderr}"
            )

    async def discard_orphans(
        self, committed: Sequence[CommittedSnapshot], ctx: SnapshotContext
    ) -> None:
        storage = Path(ctx.storage_dir)
        recorded = {c.checkpoint_id for c in committed}
        latest = max(committed, key=lambda c: c.checkpoint_id)
        extra = latest.details.model_extra or {}
        latest_archive = extra.get("archive")
        if (
            not isinstance(latest_archive, str)
            or not (storage / latest_archive).is_file()
        ):
            raise RuntimeError(
                f"archive snapshot discard for sandbox {ctx.sandbox_name!r}: the "
                f"latest committed checkpoint's archive {latest_archive!r} is "
                f"absent from {ctx.storage_dir}"
            )
        for entry in storage.iterdir():
            checkpoint_id = _archive_checkpoint_id(entry.name)
            if checkpoint_id is None or checkpoint_id not in recorded:
                entry.unlink(missing_ok=True)

    async def _clean_staging(self, env: SandboxEnvironment) -> None:
        """Best-effort removal of the in-sandbox staging root.

        Never raises: this runs in the ``finally`` of ``snapshot()``, where
        an escaping exception would mask the root-cause capture error (or
        fail a capture whose archive already landed digest-verified in the
        storage area). Residue is harmless — the next ``snapshot()`` deletes
        the staging root before capturing, and staging lives inside the
        always-excluded ``sandbox_dir`` so it is never captured.
        """
        try:
            result = await privileged_shell(
                env, f"rm -rf {self._staging_root}", user="root"
            )
        except Exception as exc:
            logger.warning(
                "archive snapshot: failed to clean in-sandbox staging: %s", exc
            )
            return
        if not result.success:
            logger.warning(
                "archive snapshot: failed to clean in-sandbox staging: %s",
                result.stderr,
            )


class _Readable(Protocol):
    def read(self, size: int, /) -> bytes: ...


class _TeeRaw(io.RawIOBase):
    """Raw binary reader that passes every byte read to ``sink``, in order."""

    def __init__(self, raw: _Readable, sink: Callable[[bytes], object]) -> None:
        super().__init__()
        self._raw = raw
        self._sink = sink

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        view = memoryview(buffer).cast("B")
        data = self._raw.read(len(view))
        view[: len(data)] = data
        self._sink(data)
        return len(data)


def _check_archive(
    path: Path, roots: RestoreRoots, expected_digest: str, *, label: str
) -> None:
    """Host-side check of a stored archive before any of it enters the sandbox.

    Walks the member headers in stream mode so nothing is extracted on
    the host and memory stays bounded by one header; every member must
    pass the :class:`RestoreWalk` and every root must be present. The
    bytes are hashed as they stream by and compared with the recorded
    digest, so a corrupt or substituted archive is refused here, before
    the copy-in (the in-sandbox digest check before extraction remains
    as the guard against corruption in transit).

    The decompressor must see the payload the way the sandbox's will:
    ``gzip -d`` and busybox gunzip decode every concatenated gzip member
    and ``zstd -d`` every frame, so gzip goes through ``GzipFile`` (which
    reads across members; ``tarfile``'s own ``r|gz`` stops at the first)
    and zstd is read across frames. Members hidden in a second gzip
    member thereby reach the walk instead of only the extracting tar.

    The decompressed bytes also pass through a :class:`TarHeaderScan`
    on their way into ``tarfile``, for what the yielded members cannot
    show: a repeated long header, or a PAX header ``tarfile`` consumes
    without yielding.

    ``tarfile`` ends its listing quietly at the first header it cannot
    parse past offset 0 (a bad checksum, a malformed PAX record), where
    busybox and GNU tar skip the block and keep extracting — the members
    behind it would never reach the walk. So after the loop the rest of
    the decompressed stream must be zero padding; anything else is
    refused. Read through ``tar.fileobj`` (tarfile's stream wrapper),
    not ``stream``: the wrapper reads ahead of what tarfile consumed.
    """
    digest = hashlib.sha256()
    walk = roots.walker(label=label)
    scan = TarHeaderScan(label=label)
    with open(path, "rb") as raw:
        hashed = io.BufferedReader(_TeeRaw(raw, digest.update))
        decompressed: zstandard.ZstdDecompressionReader | gzip.GzipFile
        if path.name.endswith(".tar.zst"):
            decompressed = zstandard.ZstdDecompressor().stream_reader(
                hashed, read_across_frames=True
            )
        else:
            decompressed = gzip.GzipFile(fileobj=hashed, mode="rb")
        stream = io.BufferedReader(_TeeRaw(decompressed, scan.feed))
        try:
            with tarfile.open(fileobj=stream, mode="r|") as tar:
                for member in tar:
                    walk.visit(tar_member_node(member, label=label))
                if tar.fileobj is None:
                    raise RuntimeError(f"{label}: tarfile closed its stream early")
                while chunk := tar.fileobj.read(_TAIL_READ_SIZE):
                    if chunk.strip(b"\0"):
                        raise RestoreScopeError(
                            f"{label}: archive {path.name} holds data after the last "
                            f"member the host could parse; the extracting tar could "
                            f"read it as further members, so the archive is refused"
                        )
        except (
            tarfile.TarError,
            zstandard.ZstdError,
            gzip.BadGzipFile,
            EOFError,
            zlib.error,
        ) as exc:
            # GzipFile reports a bad header or trailing non-gzip bytes as
            # BadGzipFile, a truncated member as EOFError and a corrupt
            # deflate body as zlib.error; none is a TarError.
            raise RestoreScopeError(
                f"{label}: archive {path.name} is unreadable (corrupt or "
                f"truncated): {exc}"
            ) from exc
        # tar stops at the end-of-archive marker; hash whatever trails it.
        while hashed.read(_TAIL_READ_SIZE):
            pass
    if digest.hexdigest() != expected_digest:
        raise RestoreScopeError(
            f"{label}: archive digest mismatch: {digest.hexdigest()} != recorded "
            f"{expected_digest}"
        )
    walk.finish()


def _archive_checkpoint_id(filename: str) -> int | None:
    """Checkpoint id from an archive filename (``ckpt-NNNNN.tar.*``)."""
    stem = filename.split(".", 1)[0]
    if not stem.startswith("ckpt-"):
        return None
    try:
        return int(stem.removeprefix("ckpt-"))
    except ValueError:
        return None


def _tar_pattern(pattern: str) -> str:
    """Convert a restic exclude pattern to a tar ``--exclude`` pattern.

    tar strips the leading ``/`` from member names, so absolute paths
    lose their slash; restic's ``**/`` prefix (match at any depth) maps
    to tar's default unanchored matching by dropping the prefix.
    """
    if pattern.startswith("**/"):
        return pattern[3:]
    return pattern.lstrip("/")
