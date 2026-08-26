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
  + ``read_file``), so host RAM is bounded by one chunk regardless of
  archive size. Transient sandbox disk equals the archive size plus
  one chunk; the §8 detached-producer pipeline that bounds sandbox
  disk to ~two chunks is a compatible follow-up (same storage layout
  and recorded details).
- Each snapshot stages in its own ``ckpt-NNNNN`` subdirectory and
  ``snapshot()`` begins by deleting the staging root, so residue from
  an interrupted fire can never corrupt the next one (§4.2). There is
  no detached producer in this implementation, so cleanup is a plain
  delete.
- The archive's sha256 is minted in-sandbox at capture time and
  cross-checked against the digest of the bytes the host actually
  read, so transport corruption cannot produce a "verified" archive
  whose recorded hash matches corrupt bytes. ``restore`` re-verifies
  the recorded digest in-sandbox after staging, before any byte is
  extracted to a final path (verify-then-extract costs transient
  sandbox disk equal to the archive size).
- Compression is zstd when available in the sandbox, else gzip
  (present in effectively every image, busybox included) — the
  archive is always compressed. ``setup`` probes and records the
  compressor; ``restore`` infers the decompressor from the file
  extension so mixed lineages never arise.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import time
from logging import getLogger
from pathlib import Path

from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.limits import override_max_read_file_size

from .._layout.schemas import SnapshotDetails
from .._repo_ops import checkpoint_tag, fs_copy_repo
from ..sandbox_paths import SandboxBackupPaths
from .types import (
    PriorAttempt,
    SandboxSnapshotStrategy,
    SnapshotContext,
)

logger = getLogger(__name__)

_DEFAULT_SANDBOX_DIR = "/root/.cache/inspect"
"""Root-only (0700) in-sandbox area shared with the restic tooling: the
parent is unlistable by the agent and ``.cache`` falls inside the
always-on capture exclude, so staging never captures itself."""

_DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024

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

        Verifies ``tar``, ``sha256sum``, and ``dd`` up front (so a
        missing tool fails at provisioning rather than at first fire or
        restore), and records zstd vs. the gzip fallback for this
        sandbox. Also probes ``dd iflag=fullblock`` (GNU/busybox), which
        copy-out uses when available to defeat short reads — BSD ``dd``
        lacks it, and the copy-out digest check still catches any
        short-read desync loudly. Nothing is injected.
        """
        script = (
            "set -e; "
            f"install -d -m 0700 {self._sandbox_dir}; "
            "for tool in tar sha256sum dd; do "
            'command -v "$tool" >/dev/null 2>&1 || '
            '{ echo "missing required tool: $tool" >&2; exit 1; }; done; '
            "if dd if=/dev/null of=/dev/null bs=1 count=0 iflag=fullblock "
            ">/dev/null 2>&1; then echo fullblock; fi; "
            "if command -v zstd >/dev/null 2>&1; then echo zstd; "
            "elif command -v gzip >/dev/null 2>&1; then echo gzip; "
            'else echo "missing required tool: zstd or gzip" >&2; exit 1; fi'
        )
        result = await env.exec(["sh", "-c", script], user="root")
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
            await self._copy_out(
                env,
                ctx,
                staging=staging,
                archive=archive,
                size=size,
                dest=local_path,
                expected_sha256=sandbox_digest,
            )
        finally:
            await self._clean_staging(env)

        # `strategy` and the archive metadata ride as extra fields (see
        # `snapshot_strategy_name`).
        return SnapshotDetails.model_validate(
            dict(
                snapshot_id=tag,
                size_bytes=size,
                duration_ms=int((time.monotonic() - start) * 1000),
                strategy=self.name,
                archive=archive_name,
                content_sha256=sandbox_digest,
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
        result = await env.exec(["sh", "-c", script], user="root")
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

    async def _copy_out(
        self,
        env: SandboxEnvironment,
        ctx: SnapshotContext,
        *,
        staging: str,
        archive: str,
        size: int,
        dest: Path,
        expected_sha256: str,
    ) -> None:
        """Chunked sandbox → host copy, digest-verified before it lands.

        Written to a dot-prefixed partial file and renamed into place
        only after the digest of the bytes actually read matches the
        in-sandbox one, so an interrupted or corrupted copy never
        leaves a plausible-looking archive in the storage area.
        """
        chunk_path = f"{staging}/chunk"
        digest = hashlib.sha256()
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(f".{dest.name}.partial")
        try:
            with open(partial, "wb") as out:
                index = 0
                copied = 0
                while copied < size:
                    script = (
                        # fullblock (when dd supports it): without it a short
                        # read (fuse/9p-backed filesystems) desyncs the
                        # block-indexed `skip` from the bytes actually copied,
                        # dropping data — which the digest check then rejects.
                        f"rm -f {chunk_path} && dd if={archive} of={chunk_path} "
                        f"bs={self._chunk_size} skip={index} count=1 "
                        f"{'iflag=fullblock ' if self._dd_fullblock else ''}"
                        f"2>/dev/null"
                    )
                    result = await env.exec(["sh", "-c", script], user="root")
                    if not result.success:
                        raise RuntimeError(
                            f"archive snapshot copy-out failed for sandbox "
                            f"{ctx.sandbox_name!r}: {result.stderr}"
                        )
                    with override_max_read_file_size(self._chunk_size * 2):
                        data = await env.read_file(chunk_path, text=False)
                    if not data:
                        raise RuntimeError(
                            f"archive snapshot copy-out for sandbox "
                            f"{ctx.sandbox_name!r}: unexpected EOF at chunk "
                            f"{index} ({copied}/{size} bytes)"
                        )
                    out.write(data)
                    digest.update(data)
                    copied += len(data)
                    index += 1
            if digest.hexdigest() != expected_sha256:
                raise RuntimeError(
                    f"archive snapshot for sandbox {ctx.sandbox_name!r} "
                    f"corrupted in transit: in-sandbox sha256 "
                    f"{expected_sha256} != host-read sha256 {digest.hexdigest()}"
                )
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        os.replace(partial, dest)

    async def restore(
        self,
        env: SandboxEnvironment,
        ref: SnapshotDetails | None,
        ctx: SnapshotContext,
    ) -> None:
        expected_digest: str | None
        if ref is None:
            # No committed checkpoint records a snapshot for this sandbox —
            # e.g. the kill tore the only checkpoint file mid-write. Restic
            # parity (see ``ResticStrategy.restore``): orphan discard is
            # skipped in exactly this case, so restore the newest adopted
            # archive — the best available capture, digest-verified when it
            # was copied out. Transit into the sandbox is still verified
            # below, against a digest computed during copy-in.
            archive_name = self._latest_archive_name(ctx)
            expected_digest = None
        else:
            extra = ref.model_extra or {}
            archive_name_extra = extra.get("archive")
            digest_extra = extra.get("content_sha256")
            if not isinstance(archive_name_extra, str) or not isinstance(
                digest_extra, str
            ):
                raise RuntimeError(
                    f"archive snapshot restore for sandbox {ctx.sandbox_name!r}: "
                    f"checkpoint record for {ref.snapshot_id} lacks archive "
                    f"metadata (archive/content_sha256)"
                )
            # `archive_name` is joined into a host path and interpolated into
            # root shell scripts below. Checkpoint records are host-written
            # and trusted, but `snapshot()` only ever generates this exact
            # form, so a corrupted record fails here instead of becoming a
            # path-traversal or shell-injection surface (or a confusing
            # shell error).
            if not _ARCHIVE_NAME_RE.fullmatch(archive_name_extra):
                raise RuntimeError(
                    f"archive snapshot restore for sandbox {ctx.sandbox_name!r}: "
                    f"checkpoint record for {ref.snapshot_id} has malformed "
                    f"archive name {archive_name_extra!r}"
                )
            if not re.fullmatch(r"[0-9a-f]{64}", digest_extra):
                raise RuntimeError(
                    f"archive snapshot restore for sandbox {ctx.sandbox_name!r}: "
                    f"checkpoint record for {ref.snapshot_id} has malformed "
                    f"content_sha256 {digest_extra!r}"
                )
            archive_name = archive_name_extra
            expected_digest = digest_extra
        local_path = Path(ctx.storage_dir) / archive_name
        if not local_path.is_file():
            raise RuntimeError(
                f"archive snapshot restore for sandbox {ctx.sandbox_name!r}: "
                f"expected archive at {local_path}, but it doesn't exist"
            )

        staging = f"{self._staging_root}/restore"
        staged = f"{staging}/{archive_name}"
        init = await env.exec(
            [
                "sh",
                "-c",
                f"set -e; install -d -m 0700 {self._sandbox_dir}; "
                f"rm -rf {self._staging_root}; mkdir -p {staging}",
            ],
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
        digest = hashlib.sha256()
        with open(local_path, "rb") as f:
            first = True
            while True:
                data = f.read(self._chunk_size)
                if not data:
                    break
                digest.update(data)
                redirect = ">" if first else ">>"
                result = await env.exec(
                    ["sh", "-c", f"cat {redirect} {staged}"], input=data, user="root"
                )
                if not result.success:
                    raise RuntimeError(
                        f"archive snapshot restore copy-in failed for sandbox "
                        f"{ctx.sandbox_name!r}: {result.stderr}"
                    )
                first = False
        if expected_digest is None:
            expected_digest = digest.hexdigest()

        # Verify-then-extract: a corrupt archive is rejected before any
        # byte reaches a final path.
        extract = (
            f"zstd -dc {staged} | tar -xf - -C /"
            if archive_name.endswith(".tar.zst")
            else f"tar -xzf {staged} -C /"
        )
        script = (
            "set -e\n"
            f'digest=$(sha256sum {staged} | cut -d" " -f1)\n'
            f'[ "$digest" = "{expected_digest}" ] || '
            f'{{ echo "archive digest mismatch: $digest != {expected_digest}" >&2; '
            f"exit 1; }}\n"
            f"{extract}\n"
            f"rm -rf {self._staging_root}\n"
        )
        result = await env.exec(["sh", "-c", script], user="root")
        if not result.success:
            raise RuntimeError(
                f"archive snapshot restore failed for sandbox "
                f"{ctx.sandbox_name!r}: {result.stderr}"
            )

    def _latest_archive_name(self, ctx: SnapshotContext) -> str:
        """Newest adopted archive, for restores with no committed record."""
        candidates = [
            entry.name
            for entry in Path(ctx.storage_dir).glob("ckpt-*")
            if _ARCHIVE_NAME_RE.fullmatch(entry.name)
        ]
        if not candidates:
            raise RuntimeError(
                f"archive snapshot restore for sandbox {ctx.sandbox_name!r}: "
                f"no committed checkpoint records a snapshot and no adopted "
                f"archives exist in {ctx.storage_dir}"
            )
        return max(candidates, key=lambda name: _archive_checkpoint_id(name) or 0)

    async def adopt(self, prior: PriorAttempt, ctx: SnapshotContext) -> None:
        """Copy the prior attempt's archives into this attempt.

        Cost is proportional to the prior attempt's checkpoint count —
        the same shape as restic's whole-repo ``fs_copy_repo`` — and the
        simple choice compliant with §4.5 (snapshots durable at this
        attempt's destination before agent work runs, via the same
        end-of-hydration host egress that ships the restic repos).
        """
        await fs_copy_repo(
            prior.sample_checkpoints_dir,
            prior.storage_subpath,
            ctx.storage_dir,
            label=f"sandbox {ctx.sandbox_name!r}",
        )

    async def discard_orphans(
        self, latest_committed_id: int, ctx: SnapshotContext
    ) -> None:
        storage = Path(ctx.storage_dir)
        if not storage.is_dir():
            return
        for entry in storage.iterdir():
            checkpoint_id = _archive_checkpoint_id(entry.name)
            if checkpoint_id is None or checkpoint_id > latest_committed_id:
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
            result = await env.exec(
                ["sh", "-c", f"rm -rf {self._staging_root}"], user="root"
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
