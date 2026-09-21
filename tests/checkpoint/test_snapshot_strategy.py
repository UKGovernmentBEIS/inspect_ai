"""Unit tests for the pluggable sandbox snapshot strategies.

Covers the §4.7 strategy pin semantics, the shared chunked copy-out
primitive, and the ``archive`` strategy's mechanics (snapshot → restore
roundtrip, hash verification, restore scoping, orphan discard) against a
*local shell* sandbox fake: ``exec`` runs the scripts with the host's
``sh`` and file APIs map to host paths, so the strategy's real shell
pipelines (tar | compress, dd chunking, sha256 verify-then-extract)
execute for real — no Docker required. The strategy's in-sandbox
root-only area is pointed at a temp dir via its ``sandbox_dir``
parameter; ``user="root"`` is ignored by the fake.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import re
import shlex
import shutil
import subprocess
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import anyio
import pytest
import zstandard
from test_helpers.local_shell_sandbox import (
    LocalShellSandbox,
    linux_like_path,
    sandbox_path,
)

from inspect_ai.util._checkpoint._copy import copy_out, copy_out_partial_path
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
from inspect_ai.util._checkpoint._restore_scope import (
    MAX_LONG_HEADER_BYTES,
    RestoreRoots,
    RestoreScopeError,
    remove_existing_symlinks,
)
from inspect_ai.util._checkpoint._snapshot import (
    committed_snapshots_for,
    snapshot_strategy_name,
)
from inspect_ai.util._checkpoint._snapshot.archive import (
    ArchiveStrategy,
    _archive_checkpoint_id,
    _tar_pattern,
)
from inspect_ai.util._checkpoint._snapshot.pin import (
    check_strategy_pin,
    read_strategy_pin,
    write_strategy_pin,
)
from inspect_ai.util._checkpoint._snapshot.registry import (
    KNOWN_STRATEGY_NAMES,
    STRATEGY_ARCHIVE,
    STRATEGY_RESTIC,
    strategy_storage_subpath,
)
from inspect_ai.util._checkpoint._snapshot.types import (
    CommittedSnapshot,
    SandboxSnapshotSession,
    SnapshotContext,
)
from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint
from inspect_ai.util._checkpoint.hydrate import _hydrate_sandbox
from inspect_ai.util._checkpoint.sandbox_paths import SandboxBackupPaths
from inspect_ai.util._sandbox import _privileged as privileged
from inspect_ai.util._sandbox._privileged import pinned_shell_command
from inspect_ai.util._subprocess import ExecResult


def _context(
    sample_root: Path, *, resuming: bool = False, max_snapshot_bytes: int | None = None
) -> SnapshotContext:
    subpath = f"sandboxes/default/{STRATEGY_ARCHIVE}"
    ctx = SnapshotContext(
        sandbox_name="default",
        storage_dir=str(sample_root / subpath),
        storage_subpath=subpath,
        secret="test-secret",
        resuming=resuming,
    )
    if max_snapshot_bytes is not None:
        ctx = replace(ctx, max_snapshot_bytes=max_snapshot_bytes)
    return ctx


def _committed(*records: tuple[int, str]) -> list[CommittedSnapshot]:
    """Committed archive records as ``(checkpoint_id, archive filename)``."""
    return [
        CommittedSnapshot(
            checkpoint_id=checkpoint_id,
            details=SnapshotDetails.model_validate(
                dict(
                    snapshot_id=f"ckpt-{checkpoint_id:05d}",
                    size_bytes=1,
                    duration_ms=1,
                    strategy=STRATEGY_ARCHIVE,
                    archive=archive,
                    content_sha256="0" * 64,
                )
            ),
        )
        for checkpoint_id, archive in records
    ]


async def _strategy(env: LocalShellSandbox, tmp_path: Path) -> ArchiveStrategy:
    strategy = ArchiveStrategy(
        chunk_size=256 * 1024, sandbox_dir=str(tmp_path / "sandbox-tools")
    )
    await strategy.setup(env, _context(tmp_path / "sample"))
    return strategy


def _write_data(data_dir: Path) -> dict[str, bytes]:
    """Populate a capture tree: text, multi-chunk binary, a symlink, a cache dir."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "nested").mkdir(exist_ok=True)
    files = {
        "notes.txt": b"hello checkpoint\n",
        # > 4 chunks at the test's 256 KiB chunk size, incompressible.
        "nested/blob.bin": bytes(
            bytearray((i * 7919 + i // 251) % 256 for i in range(1_200_000))
        ),
    }
    for rel, content in files.items():
        (data_dir / rel).write_bytes(content)
    link = data_dir / "link.txt"
    if not link.is_symlink():
        link.symlink_to("notes.txt")
    # Directory special bits are legitimate capture content (a `/tmp`-style
    # drop dir, a `chmod g+s` shared dir) and must survive a restore.
    (data_dir / "drop").mkdir(exist_ok=True)
    (data_dir / "drop").chmod(0o1777)
    (data_dir / "shared").mkdir(exist_ok=True)
    (data_dir / "shared").chmod(0o2775)
    cache = data_dir / ".cache"
    cache.mkdir(exist_ok=True)
    (cache / "junk").write_bytes(b"never captured")
    return files


# --- archive strategy: capture/restore mechanics ---------------------


async def test_archive_snapshot_restore_roundtrip(tmp_path: Path) -> None:
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    files = _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)], exclude=["**/.cache"])
    # Sibling of the capture root: must be untouched by the restore.
    sibling = tmp_path / "capture" / "sibling.txt"
    sibling.write_bytes(b"not captured")
    parent_mode = (tmp_path / "capture").stat().st_mode

    details = await strategy.snapshot(env, paths, 1, ctx)

    assert details.snapshot_id == "ckpt-00001"
    assert snapshot_strategy_name(details) == STRATEGY_ARCHIVE
    extra = details.model_extra or {}
    assert extra["roots"] == [str(data_dir)]
    archives = list(Path(ctx.storage_dir).iterdir())
    assert [a.name for a in archives] == [extra["archive"]]
    assert details.size_bytes == archives[0].stat().st_size
    # In-sandbox staging fully cleaned up after capture.
    assert not (Path(strategy._staging_root)).exists()

    # Wipe the captured tree (cache included), then restore into the
    # "fresh sandbox".
    for rel in files:
        (data_dir / rel).unlink()
    (data_dir / "link.txt").unlink()
    (data_dir / ".cache" / "junk").unlink()
    (data_dir / "extra-not-in-snapshot.txt").write_bytes(b"post-capture")
    (data_dir / "drop").rmdir()
    (data_dir / "shared").rmdir()
    sibling.write_bytes(b"changed after capture")

    await strategy.restore(env, paths, details, ctx)

    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content
    assert (data_dir / "link.txt").is_symlink()
    assert os.readlink(data_dir / "link.txt") == "notes.txt"
    # The sticky and setgid dirs pass the host-side walk and are restored
    # (GNU tar as non-root drops the bits themselves; as root it keeps them).
    assert (data_dir / "drop").is_dir() and (data_dir / "shared").is_dir()
    # Excluded at capture: the cache dir's contents are not in the
    # archive, so restore does not recreate them.
    assert not (data_dir / ".cache" / "junk").exists()
    assert not (Path(strategy._staging_root)).exists()
    # Nothing outside the capture root was written or re-moded.
    assert sibling.read_bytes() == b"changed after capture"
    assert (tmp_path / "capture").stat().st_mode == parent_mode


async def test_archive_snapshot_handles_paths_with_spaces(tmp_path: Path) -> None:
    """Include/exclude tokens are shell-quoted into the capture script."""
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "my data"
    files = _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)], exclude=["**/.cache"])

    details = await strategy.snapshot(env, paths, 1, ctx)
    assert details.snapshot_id == "ckpt-00001"

    for rel in files:
        (data_dir / rel).unlink()
    await strategy.restore(env, paths, details, ctx)
    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content


async def test_archive_snapshot_tolerates_tar_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tar exit 1 (file changed while reading) must not fail the fire.

    Regression test for the fd-3 exit-status capture: with ``set -e``
    active, dash/ash abort the capture subshell on tar's non-zero exit
    before ``echo $? >&3`` runs, so the tolerated exit 1 used to fail
    the snapshot with a blank status. A shim ``tar`` that produces a
    valid archive but exits 1 makes the case deterministic. The
    strategy's root scripts ignore the inherited ``PATH`` and use the
    pinned system directories, so the shim goes on that pinned ``PATH``.
    """
    real_tar = shutil.which("tar", path=sandbox_path())
    assert real_tar is not None
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "tar"
    shim.write_text(f'#!/bin/sh\n"{real_tar}" "$@"\nexit 1\n')
    shim.chmod(0o755)
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    files = _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    with monkeypatch.context() as shimmed:
        shimmed.setattr(
            privileged,
            "SYSTEM_PATH",
            f"{shim_dir}{os.pathsep}{privileged.SYSTEM_PATH}",
        )
        details = await strategy.snapshot(env, paths, 1, ctx)

    # Restore with an un-shimmed tar: the shim only simulates the
    # capture-time "file changed as we read it" warning.
    for rel in files:
        (data_dir / rel).unlink()
    await strategy.restore(LocalShellSandbox(), paths, details, ctx)
    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content


async def test_archive_snapshot_tolerates_staging_cleanup_exception(
    tmp_path: Path,
) -> None:
    """An `exec` exception during staging cleanup must not fail the fire.

    `_clean_staging` runs in the `finally` of `snapshot()`; by then the
    archive is already landed and digest-verified, and cleanup is
    best-effort (the next fire deletes the staging root before
    capturing), so a transport hiccup there must be swallowed — not
    fail the capture or mask a propagating error.
    """

    class _CleanupRaisingSandbox(LocalShellSandbox):
        cleanup_script: str | None = None
        cleanup_attempted = False

        async def exec(
            self,
            cmd: list[str],
            input: str | bytes | None = None,
            cwd: str | None = None,
            env: dict[str, str] | None = None,
            user: str | None = None,
            timeout: int | None = None,
            timeout_retry: bool = True,
            concurrency: bool = True,
        ) -> ExecResult[str]:
            if self.cleanup_script is not None and cmd == pinned_shell_command(
                self.cleanup_script
            ):
                self.cleanup_attempted = True
                raise TimeoutError("transport lost during cleanup")
            return await super().exec(
                cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
            )

    env = _CleanupRaisingSandbox()
    strategy = await _strategy(env, tmp_path)
    env.cleanup_script = f"rm -rf {strategy._staging_root}"
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    files = _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    details = await strategy.snapshot(env, paths, 1, ctx)

    assert env.cleanup_attempted
    assert details.snapshot_id == "ckpt-00001"
    for rel in files:
        (data_dir / rel).unlink()
    await strategy.restore(LocalShellSandbox(), paths, details, ctx)
    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content


class _CountingSandbox(LocalShellSandbox):
    """Counts ``exec`` calls: a refused restore must run none."""

    def __init__(self) -> None:
        super().__init__()
        self.execs = 0

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.execs += 1
        return await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )


async def test_archive_restore_rejects_corrupt_archive(tmp_path: Path) -> None:
    env = _CountingSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    details = await strategy.snapshot(env, paths, 1, ctx)
    extra = details.model_extra or {}
    archive = Path(ctx.storage_dir) / str(extra["archive"])

    # Flip bytes in the stored archive; the host-side walk fails (an
    # unreadable stream, or a digest that no longer matches the record)
    # before any byte is copied into the sandbox.
    corrupted = bytearray(archive.read_bytes())
    corrupted[10] ^= 0xFF
    archive.write_bytes(bytes(corrupted))

    marker = data_dir / "notes.txt"
    marker.write_bytes(b"post-capture content")
    execs_before = env.execs
    with pytest.raises(RestoreScopeError, match="unreadable|digest mismatch"):
        await strategy.restore(env, paths, details, ctx)
    assert env.execs == execs_before
    # Nothing was extracted over the live tree.
    assert marker.read_bytes() == b"post-capture content"


async def test_archive_restore_rejects_digest_mismatch_before_copy_in(
    tmp_path: Path,
) -> None:
    """A well-formed archive whose bytes are not the recorded ones is refused on the host."""
    env = _CountingSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    details = await strategy.snapshot(env, paths, 1, ctx)
    forged = details.model_copy(update={"content_sha256": "0" * 64})
    execs_before = env.execs
    with pytest.raises(RestoreScopeError, match="digest mismatch"):
        await strategy.restore(env, paths, forged, ctx)
    assert env.execs == execs_before


def _crafted_archive(
    path: Path, members: list[tarfile.TarInfo], contents: dict[str, bytes]
) -> str:
    """Write ``members`` as a ``.tar.gz``/``.tar.zst`` at ``path``; return its sha256.

    GNU format, as a Linux tar writes: ``tarfile``'s default PAX format
    puts any name over 100 bytes (a macOS ``tmp_path``) in a PAX header,
    which the restore-scope scan refuses.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for info in members:
            data = contents.get(info.name)
            if data is not None:
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return _compressed_archive(path, raw.getvalue())


def _compressed_archive(path: Path, raw_tar: bytes) -> str:
    """Compress ``raw_tar`` as ``path``'s extension says; return the file's sha256."""
    if path.name.endswith(".tar.zst"):
        payload = zstandard.ZstdCompressor().compress(raw_tar)
    else:
        payload = gzip.compress(raw_tar)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _ustar(
    name: str, type: bytes = tarfile.REGTYPE, mode: int = 0o644, linkname: str = ""
) -> bytes:
    """One raw 512-byte ustar header for an empty member."""
    return _member(name, type, mode=mode, linkname=linkname).tobuf(tarfile.USTAR_FORMAT)


def _data_header(name: str, type: bytes, data: bytes) -> bytes:
    """A raw header of ``type`` whose data block(s) hold ``data``."""
    info = tarfile.TarInfo(name)
    info.type = type
    info.size = len(data)
    padding = b"\0" * (-len(data) % tarfile.BLOCKSIZE)
    return info.tobuf(tarfile.USTAR_FORMAT) + data + padding


def _pax_header(records: bytes, type: bytes = tarfile.XHDTYPE) -> bytes:
    """A raw PAX extended (``x``) or global (``g``) header with ``records``."""
    return _data_header("././@PaxHeader", type, records)


def _long_header(type: bytes, value: str) -> bytes:
    """A raw GNU long-name (``L``) or long-link (``K``) header carrying ``value``."""
    return _data_header("././@LongLink", type, value.encode() + b"\0")


def _bad_checksum(name: str) -> bytes:
    header = bytearray(_ustar(name))
    header[148:156] = b"0000000\0"
    return bytes(header)


def _checksum_in_form(name: str, spell: Callable[[int], bytes]) -> bytes:
    """A header for ``name`` whose correct checksum is spelled by ``spell`` (base-256, signed, …)."""
    header = bytearray(_ustar(name))
    header[148:156] = b"        "
    header[148:156] = spell(sum(header))
    return bytes(header)


_TAR_END = b"\0" * (2 * tarfile.BLOCKSIZE)


def _boundary_tricks(root: str) -> dict[str, tuple[bytes, str]]:
    """Name → (raw tar bytes, substring the refusal must name).

    Archives on which ``tarfile`` and an extracting tar disagree about
    where members start, what they are called or where a hard link
    points, each hiding a setuid ``sh`` or an out-of-scope hard link
    under the root. busybox tar ignores PAX, so a ``size`` record that
    makes ``tarfile`` skip a block leaves busybox reading that block as
    a header; ``tarfile`` ends its listing quietly at a header it cannot
    parse, where busybox and GNU tar skip it and continue; of two
    chained GNU long headers ``tarfile`` applies the first where busybox
    and GNU tar apply the last; and a header the scan cannot judge but
    ``tarfile`` lists past — a checksum spelled in a form the scan does
    not read (base-256, signed), or a PAX header with no records, which
    ``tarfile`` consumes without yielding — must be refused rather than
    end the scan, or the chain behind it would go unscanned while the
    walk kept accepting members. A long header claiming more than
    :data:`MAX_LONG_HEADER_BYTES` is refused on its header alone, since
    ``tarfile`` would read that many bytes into memory.
    """
    dir_ = _ustar(root, tarfile.DIRTYPE, 0o755)
    ok = _ustar(f"{root}/ok")
    hidden = _ustar(f"{root}/sh", mode=0o4755)
    retargeted_link = (
        _long_header(tarfile.GNUTYPE_LONGLINK, f"{root}/ok")
        + _long_header(tarfile.GNUTYPE_LONGLINK, "etc/passwd")
        + _ustar(f"{root}/pw", tarfile.LNKTYPE)
    )
    return {
        "base256_checksum_hides_a_long_link_chain": (
            dir_
            + _checksum_in_form(
                f"{root}/ok", lambda total: b"\x80" + total.to_bytes(7, "big")
            )
            + retargeted_link
            + _TAR_END,
            "holds a checksum field that is not octal",
        ),
        "signed_checksum_hides_a_long_link_chain": (
            dir_
            + _checksum_in_form(f"{root}/ok", lambda total: f"+{total:06o}\0".encode())
            + retargeted_link
            + _TAR_END,
            "holds a checksum field that is not octal",
        ),
        "second_long_link_retargets_a_hard_link": (
            dir_ + ok + retargeted_link + _TAR_END,
            "preceded by two GNU long-link (K) headers",
        ),
        "second_long_name_renames_a_member": (
            dir_
            + _long_header(tarfile.GNUTYPE_LONGNAME, f"{root}/ok")
            + _long_header(tarfile.GNUTYPE_LONGNAME, f"{root}/sh")
            + hidden
            + _TAR_END,
            "preceded by two GNU long-name (L) headers",
        ),
        "empty_pax_hides_a_long_link_chain": (
            dir_ + _pax_header(b"") + ok + retargeted_link + _TAR_END,
            "holds a PAX extended header ('././@PaxHeader')",
        ),
        "empty_global_pax_hides_a_long_link_chain": (
            dir_ + _pax_header(b"", tarfile.XGLTYPE) + ok + retargeted_link + _TAR_END,
            "holds a PAX global header ('././@PaxHeader')",
        ),
        "pax_size_hides_a_member": (
            dir_ + _pax_header(b"12 size=512\n") + ok + hidden + _TAR_END,
            "holds a PAX extended header ('././@PaxHeader')",
        ),
        "global_pax_renames_members": (
            dir_
            + _pax_header(b"20 path=etc/planted\n", tarfile.XGLTYPE)
            + ok
            + _TAR_END,
            "holds a PAX global header ('././@PaxHeader')",
        ),
        "malformed_pax_hides_a_member": (
            dir_ + _pax_header(b"9 size=512\n") + ok + hidden + _TAR_END,
            "holds a PAX extended header ('././@PaxHeader')",
        ),
        "bad_checksum_ends_the_listing": (
            dir_ + _bad_checksum(f"{root}/junk") + ok + hidden + _TAR_END,
            "holds data after the last member",
        ),
        "oversized_long_name_header": (
            dir_
            + _member(
                "././@LongLink",
                tarfile.GNUTYPE_LONGNAME,
                size=MAX_LONG_HEADER_BYTES + 1,
            ).tobuf(tarfile.USTAR_FORMAT)
            + hidden
            + _TAR_END,
            f"long-name (L) header of {MAX_LONG_HEADER_BYTES + 1} bytes",
        ),
    }


def _member(
    name: str, type: bytes = tarfile.REGTYPE, **attrs: object
) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = type
    info.mode = 0o755 if type == tarfile.DIRTYPE else 0o644
    for key, value in attrs.items():
        setattr(info, key, value)
    return info


def _rel(path: Path) -> str:
    """A host path as the tar member name ``tar -c`` would write for it."""
    return str(path).lstrip("/")


def _header_name(path: Path) -> str:
    """The name a raw header carries for ``path``: its first 100 bytes.

    A longer name (a macOS ``tmp_path``) lives in the GNU long-name header
    before it, and the header scan's diagnostic quotes the header's own
    field, decoded as the scan decodes it.
    """
    return _rel(path).encode()[:100].decode("utf-8", "replace")


_HOSTILE_MEMBERS: dict[str, Callable[[Path, Path], tuple[tarfile.TarInfo, str]]] = {
    # (member, substring the error must name)
    "outside_root": lambda root, outside: (
        _member(_rel(outside / "planted.txt")),
        f"{outside}/planted.txt lies outside",
    ),
    "etc_passwd": lambda root, outside: (
        _member("etc/passwd"),
        "/etc/passwd lies outside",
    ),
    "setuid_under_root": lambda root, outside: (
        _member(_rel(root / "sh"), mode=0o4755),
        f"{root}/sh is a regular file with mode 4755",
    ),
    "setgid_file_under_root": lambda root, outside: (
        _member(_rel(root / "sh"), mode=0o2755),
        f"{root}/sh is a regular file with mode 2755",
    ),
    # Sparse, fifo and device headers are refused by the header scan,
    # before tarfile yields the member the walk would also refuse.
    "sparse_under_root": lambda root, outside: (
        _member(_rel(root / "sp"), tarfile.GNUTYPE_SPARSE),
        f"holds a GNU sparse file header ('{_header_name(root / 'sp')}')",
    ),
    "fifo_under_root": lambda root, outside: (
        _member(_rel(root / "pipe"), tarfile.FIFOTYPE),
        f"holds a fifo header ('{_header_name(root / 'pipe')}')",
    ),
    "chardev_under_root": lambda root, outside: (
        _member(_rel(root / "null"), tarfile.CHRTYPE),
        f"holds a character device header ('{_header_name(root / 'null')}')",
    ),
    "hardlink_outside": lambda root, outside: (
        _member(_rel(root / "pw"), tarfile.LNKTYPE, linkname="etc/passwd"),
        f"{root}/pw is a hard link to /etc/passwd",
    ),
    "absolute_member": lambda root, outside: (
        _member(str(root / "abs.txt")),
        "archive member is empty or absolute",
    ),
    "dotdot_member": lambda root, outside: (
        _member(f"{_rel(root)}/../escape.txt"),
        "'..' component",
    ),
}


@pytest.mark.parametrize("compression", ["gz", "zst"])
@pytest.mark.parametrize("violation", sorted(_HOSTILE_MEMBERS))
async def test_archive_restore_refuses_hostile_archive(
    tmp_path: Path, violation: str, compression: str
) -> None:
    """A crafted archive is refused on the host, naming the offending member.

    The archive otherwise looks legitimate — a valid ``ckpt-NNNNN`` name,
    the recorded digest matches its bytes, and it carries the root — so
    only the structural check stands between it and a root ``tar -x``.
    Nothing is sent to the sandbox: no ``exec`` runs at all.
    """
    env = _CountingSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    root = tmp_path / "capture" / "data"
    root.mkdir(parents=True)
    outside = tmp_path / "capture" / "outside"
    paths = SandboxBackupPaths(include=[str(root)])
    hostile, expected = _HOSTILE_MEMBERS[violation](root, outside)

    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    archive_name = f"ckpt-00001.tar.{compression}"
    digest = _crafted_archive(
        storage / archive_name,
        [
            _member(_rel(root), tarfile.DIRTYPE),
            _member(_rel(root / "notes.txt")),
            hostile,
        ],
        {_rel(root / "notes.txt"): b"legit\n"},
    )
    details = SnapshotDetails.model_validate(
        dict(
            snapshot_id="ckpt-00001",
            size_bytes=1,
            duration_ms=1,
            strategy=STRATEGY_ARCHIVE,
            archive=archive_name,
            content_sha256=digest,
            roots=[str(root)],
        )
    )

    execs_before = env.execs
    with pytest.raises(RestoreScopeError, match=re.escape(expected)):
        await strategy.restore(env, paths, details, ctx)
    assert env.execs == execs_before
    assert not (root / "notes.txt").exists()
    assert not outside.exists()


def _hostile_details(archive_name: str, digest: str, root: Path) -> SnapshotDetails:
    return SnapshotDetails.model_validate(
        dict(
            snapshot_id="ckpt-00001",
            size_bytes=1,
            duration_ms=1,
            strategy=STRATEGY_ARCHIVE,
            archive=archive_name,
            content_sha256=digest,
            roots=[str(root)],
        )
    )


@pytest.mark.parametrize("compression", ["gz", "zst"])
@pytest.mark.parametrize("trick", sorted(_boundary_tricks("x")))
async def test_archive_restore_refuses_member_boundary_tricks(
    tmp_path: Path, trick: str, compression: str
) -> None:
    """An archive whose members ``tarfile`` and the sandbox's tar would count differently is refused.

    Every member ``tarfile`` yields is in scope and benign; the refusal
    comes from the raw header scan or from the bytes left behind where
    ``tarfile`` stopped. Nothing is sent to the sandbox.
    """
    env = _CountingSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    root = tmp_path / "capture" / "data"
    root.mkdir(parents=True)
    raw, expected = _boundary_tricks(_rel(root))[trick]
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    archive_name = f"ckpt-00001.tar.{compression}"
    digest = _compressed_archive(storage / archive_name, raw)

    execs_before = env.execs
    with pytest.raises(RestoreScopeError, match=re.escape(expected)):
        await strategy.restore(
            env,
            SandboxBackupPaths(include=[str(root)]),
            _hostile_details(archive_name, digest, root),
            ctx,
        )
    assert env.execs == execs_before
    assert not (root / "ok").exists()
    assert not (root / "sh").exists()


def _split_gzip_archive(clean: bytes, hidden: bytes) -> bytes:
    """``gzip(clean) + gzip(hidden)``: one tar stream to ``gzip -d``, two gzip members."""
    return gzip.compress(clean) + gzip.compress(hidden)


@pytest.mark.parametrize(
    "layout", ["hidden_in_second_member", "member_behind_end_marker", "trailing_bytes"]
)
async def test_archive_restore_decodes_gzip_like_the_sandbox_does(
    tmp_path: Path, layout: str
) -> None:
    """Members in a second gzip member reach the host walk, as they reach the sandbox's tar.

    ``gzip -d`` and busybox gunzip decode concatenated gzip members, so
    ``gzip(clean members without an end marker) + gzip(hidden members)``
    is one archive to the extracting tar; ``tarfile``'s own ``r|gz``
    would list only the clean members. A second member behind an
    end-of-archive marker is trailing data, and bytes that are not gzip
    at all (busybox gunzip ignores them) make the archive unreadable.
    """
    env = _CountingSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    root = tmp_path / "capture" / "data"
    root.mkdir(parents=True)
    rel = _rel(root)
    clean = _ustar(rel, tarfile.DIRTYPE, 0o755) + _ustar(f"{rel}/ok")
    hidden = _ustar(f"{rel}/pw", tarfile.LNKTYPE, linkname="etc/passwd") + _TAR_END
    if layout == "hidden_in_second_member":
        payload = _split_gzip_archive(clean, hidden)
        expected = f"{root}/pw is a hard link to /etc/passwd"
    elif layout == "member_behind_end_marker":
        payload = _split_gzip_archive(clean + _TAR_END, hidden)
        expected = "holds data after the last member"
    else:
        payload = gzip.compress(clean + _TAR_END) + b"not gzip"
        expected = "is unreadable"
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    archive_name = "ckpt-00001.tar.gz"
    (storage / archive_name).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    execs_before = env.execs
    with pytest.raises(RestoreScopeError, match=re.escape(expected)):
        await strategy.restore(
            env,
            SandboxBackupPaths(include=[str(root)]),
            _hostile_details(archive_name, digest, root),
            ctx,
        )
    assert env.execs == execs_before
    assert not (root / "ok").exists()
    assert not (root / "pw").exists()


@contextmanager
def _tar_shim(tmp_path: Path, implementation: str) -> Iterator[None]:
    """Pinned commands resolve ``tar`` to ``implementation``'s (``host`` = the fake's own).

    The strategy's scripts ignore the fake's ``PATH`` and use the pinned
    system directories, so the shim goes first on that pinned ``PATH``.
    """
    if implementation == "host":
        yield
        return
    if shutil.which(implementation) is None:
        pytest.skip(f"{implementation} not installed")
    shim = tmp_path / "tar-shim"
    shim.mkdir()
    (shim / "tar").symlink_to(shutil.which(implementation) or implementation)
    with patch.object(
        privileged, "SYSTEM_PATH", f"{shim}{os.pathsep}{privileged.SYSTEM_PATH}"
    ):
        yield


@pytest.mark.parametrize("hiding", ["tar_parser", "second_gzip_member"])
@pytest.mark.parametrize("implementation", ["host", "busybox"])
async def test_archive_extraction_guard_fails_on_a_planted_special_file(
    tmp_path: Path, implementation: str, hiding: str
) -> None:
    """Third layer: a special node the sandbox's tar wrote under a root fails the restore.

    The host-side check is bypassed so the archive reaches extraction.
    ``second_gzip_member`` hides a fifo behind the first gzip member,
    which both tars' gunzip decode. ``tar_parser`` is a member only the
    extracting tar reads: with busybox tar the PAX ``size`` trick, whose
    setuid ``sh`` busybox extracts (it ignores PAX and, unlike GNU tar
    as non-root, keeps the mode bits) and ``tarfile`` never saw; with
    the host's tar a plain archive carrying a fifo, since GNU tar honors
    the PAX record and would hide the member as ``tarfile`` did.
    """
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    root = tmp_path / "capture" / "data"
    root.mkdir(parents=True)
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    archive_name = "ckpt-00001.tar.gz"
    rel = _rel(root)
    if hiding == "second_gzip_member":
        payload = _split_gzip_archive(
            _ustar(rel, tarfile.DIRTYPE, 0o755) + _ustar(f"{rel}/ok"),
            _ustar(f"{rel}/pipe", tarfile.FIFOTYPE) + _TAR_END,
        )
        (storage / archive_name).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        planted = root / "pipe"
    elif implementation == "busybox":
        raw, _ = _boundary_tricks(rel)["pax_size_hides_a_member"]
        digest = _compressed_archive(storage / archive_name, raw)
        planted = root / "sh"
    else:
        digest = _crafted_archive(
            storage / archive_name,
            [
                _member(_rel(root), tarfile.DIRTYPE),
                _member(_rel(root / "ok")),
                _member(_rel(root / "pipe"), tarfile.FIFOTYPE),
            ],
            {},
        )
        planted = root / "pipe"

    with (
        _tar_shim(tmp_path, implementation),
        patch(
            "inspect_ai.util._checkpoint._snapshot.archive._check_archive",
            return_value=None,
        ),
    ):
        with pytest.raises(RuntimeError, match=rf"extraction produced {planted}"):
            await strategy.restore(
                env,
                SandboxBackupPaths(include=[str(root)]),
                _hostile_details(archive_name, digest, root),
                ctx,
            )
    # The node did land (the guard runs after extraction); the failed
    # restore is what discards the sandbox.
    assert planted.exists()


async def _remove_image_symlinks(env: LocalShellSandbox, root: Path) -> None:
    """The core's pre-``setup`` pass on resume (``_hydrate_sandbox``), for a strategy-level test."""
    await remove_existing_symlinks(
        env, RestoreRoots.from_include([str(root)], label="test"), label="test"
    )


@pytest.mark.parametrize("implementation", ["host", "busybox"])
async def test_archive_restore_never_writes_through_an_image_symlink(
    tmp_path: Path, implementation: str
) -> None:
    """A symlink the fresh image ships under the root cannot route a member outside it.

    The archive passes the host walk: a directory, a regular file
    ``l/shadow`` and a hard link ``pw -> l/passwd``, all lexically under
    the root. In the fresh sandbox ``l`` is a symlink to a directory
    outside the root, through which busybox tar would write ``shadow``
    and both tars would hard-link ``pw`` to the outside ``passwd``. The
    core deletes the image's symlinks under the root before the restore,
    so ``shadow`` lands in a real directory ``l`` and the hard link,
    whose target no longer exists, fails the restore.
    """
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    root = tmp_path / "capture" / "data"
    root.mkdir(parents=True)
    outside = tmp_path / "capture" / "etc"
    outside.mkdir()
    (outside / "passwd").write_text("root:x:0:0\n")
    (root / "l").symlink_to("../etc")
    await _remove_image_symlinks(env, root)
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    archive_name = "ckpt-00001.tar.gz"
    digest = _crafted_archive(
        storage / archive_name,
        [
            _member(_rel(root), tarfile.DIRTYPE),
            _member(_rel(root / "l" / "shadow")),
            _member(
                _rel(root / "pw"),
                tarfile.LNKTYPE,
                linkname=_rel(root / "l" / "passwd"),
            ),
        ],
        {_rel(root / "l" / "shadow"): b"planted\n"},
    )

    with _tar_shim(tmp_path, implementation):
        with pytest.raises(RuntimeError, match="archive snapshot restore failed"):
            await strategy.restore(
                env,
                SandboxBackupPaths(include=[str(root)]),
                _hostile_details(archive_name, digest, root),
                ctx,
            )

    assert not (outside / "shadow").exists()
    assert (outside / "passwd").stat().st_nlink == 1
    assert not (root / "pw").exists()
    assert (root / "l").is_dir() and not (root / "l").is_symlink()


@pytest.mark.parametrize("implementation", ["host", "busybox"])
async def test_archive_restore_replaces_image_symlinks_with_the_snapshot(
    tmp_path: Path, implementation: str
) -> None:
    """Image symlinks under the root give way to what the snapshot holds at each path.

    A directory where the snapshot has one (its file lands there, not in
    the link's target), a link where the snapshot has a link, and nothing
    where the snapshot has nothing. The capture runs with the host's tar;
    only the restore runs under ``implementation``.
    """
    capture_env = LocalShellSandbox()
    strategy = await _strategy(capture_env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    _write_data(data_dir)
    (data_dir / "local").mkdir()
    (data_dir / "local" / "x").write_text("captured\n")
    paths = SandboxBackupPaths(include=[str(data_dir)])
    details = await strategy.snapshot(capture_env, paths, 1, ctx)

    env = LocalShellSandbox()
    shutil.rmtree(data_dir)
    data_dir.mkdir()
    elsewhere = tmp_path / "capture" / "elsewhere"
    elsewhere.mkdir()
    (data_dir / "local").symlink_to("../elsewhere")
    (data_dir / "link.txt").symlink_to("/etc/hostname")
    (data_dir / "stale").symlink_to("/etc")

    await _remove_image_symlinks(env, data_dir)
    with _tar_shim(tmp_path, implementation):
        await strategy.restore(env, paths, details, ctx)

    assert (data_dir / "local").is_dir() and not (data_dir / "local").is_symlink()
    assert (data_dir / "local" / "x").read_text() == "captured\n"
    assert not (elsewhere / "x").exists()
    assert os.readlink(data_dir / "link.txt") == "notes.txt"
    assert not (data_dir / "stale").is_symlink()
    assert not (data_dir / "stale").exists()


async def test_hydrate_removes_image_symlinks_before_the_strategy_stages_under_the_root(
    tmp_path: Path,
) -> None:
    """The symlink pass runs before ``setup``, so strategy state under the root survives it.

    The strategy's sandbox dir is ``<root>/.cache/inspect`` (the default
    ``/root/.cache/inspect`` when the default user is root) and the fresh
    image ships ``<root>/.cache`` as a symlink to a directory outside the
    root. Had the pass run after ``setup`` or the archive staging, the
    strategy's ``install -d`` would have created its dirs through the
    link and the pass would then have severed them, failing the restore
    with "no such file". Run first, the link goes before anything is
    placed and every later ``install -d`` creates real directories; the
    link's target is never written.
    """
    root = tmp_path / "capture" / "home"
    files = _write_data(root)
    sandbox_dir = str(root / ".cache" / "inspect")
    sample = tmp_path / "sample"
    paths = SandboxBackupPaths(include=[str(root)])
    capture_env = LocalShellSandbox()
    capture = ArchiveStrategy(chunk_size=256 * 1024, sandbox_dir=sandbox_dir)
    await capture.setup(capture_env, _context(sample))
    details = await capture.snapshot(capture_env, paths, 1, _context(sample))

    shutil.rmtree(root)
    root.mkdir()
    elsewhere = tmp_path / "capture" / "cache"
    elsewhere.mkdir()
    (root / ".cache").symlink_to("../cache")
    env = LocalShellSandbox()
    ctx = _context(sample, resuming=True)
    checkpoint = Checkpoint(
        checkpoint_id=1,
        trigger="turn",
        turn=1,
        created_at=datetime.now(timezone.utc),
        duration_ms=0,
        size_bytes=0,
        host=SnapshotDetails(snapshot_id="host", size_bytes=0, duration_ms=0),
        sandboxes={"default": details},
    )

    with patch("inspect_ai.util._checkpoint.hydrate.sandbox", return_value=env):
        await _hydrate_sandbox(
            name="default",
            session=SandboxSnapshotSession(
                ArchiveStrategy(chunk_size=256 * 1024, sandbox_dir=sandbox_dir),
                ctx,
                paths,
            ),
            resume=ResumeCheckpoint(attempt="resume"),
            committed_checkpoints=[checkpoint],
            action="test",
        )

    for rel, content in files.items():
        assert (root / rel).read_bytes() == content
    assert (root / ".cache").is_dir() and not (root / ".cache").is_symlink()
    assert not (elsewhere / "inspect").exists()
    assert not (Path(sandbox_dir) / "snapshot-staging").exists()


@pytest.mark.parametrize("compression", ["gz", "zst"])
def test_check_archive_hashes_bytes_past_the_tar_end_marker(
    tmp_path: Path, compression: str
) -> None:
    """The recorded digest covers the whole stored file, not just what tar reads.

    tar stops at the end-of-archive marker; the walk must keep hashing
    to EOF so a file with trailing bytes matches (or fails) on its true
    digest, and a multi-frame zstd payload is read across frames.
    """
    from inspect_ai.util._checkpoint._restore_scope import RestoreRoots
    from inspect_ai.util._checkpoint._snapshot.archive import _check_archive

    root = tmp_path / "data"
    archive = tmp_path / f"ckpt-00001.tar.{compression}"
    _crafted_archive(
        archive,
        [_member(_rel(root), tarfile.DIRTYPE), _member(_rel(root / "a"))],
        {_rel(root / "a"): b"a"},
    )
    trailer = (
        zstandard.ZstdCompressor().compress(b"\0" * 1024)
        if compression == "zst"
        else gzip.compress(b"\0" * 1024)
    )
    payload = archive.read_bytes() + trailer
    archive.write_bytes(payload)
    roots = RestoreRoots.from_include([str(root)], label="test")

    _check_archive(archive, roots, hashlib.sha256(payload).hexdigest(), label="test")
    with pytest.raises(RestoreScopeError, match="digest mismatch"):
        _check_archive(
            archive,
            roots,
            hashlib.sha256(payload[: -len(trailer)]).hexdigest(),
            label="test",
        )


async def test_archive_restore_refuses_snapshot_missing_a_root(tmp_path: Path) -> None:
    env = _CountingSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    root = tmp_path / "capture" / "data"
    other = tmp_path / "capture" / "other"
    root.mkdir(parents=True)
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    digest = _crafted_archive(
        storage / "ckpt-00001.tar.gz",
        [_member(_rel(root), tarfile.DIRTYPE), _member(_rel(root / "a"))],
        {_rel(root / "a"): b"a"},
    )
    details = SnapshotDetails.model_validate(
        dict(
            snapshot_id="ckpt-00001",
            size_bytes=1,
            duration_ms=1,
            archive="ckpt-00001.tar.gz",
            content_sha256=digest,
        )
    )
    execs_before = env.execs
    with pytest.raises(RestoreScopeError, match=rf"no node at capture root.*{other}"):
        await strategy.restore(
            env, SandboxBackupPaths(include=[str(root), str(other)]), details, ctx
        )
    assert env.execs == execs_before


async def test_archive_restore_rejects_recorded_roots_mismatch(tmp_path: Path) -> None:
    """A snapshot recorded from other roots is an error naming both, not widened."""
    env = _CountingSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    _write_data(data_dir)
    details = await strategy.snapshot(
        env, SandboxBackupPaths(include=[str(data_dir)]), 1, ctx
    )
    current = SandboxBackupPaths(include=[str(tmp_path / "capture" / "elsewhere")])
    execs_before = env.execs
    with pytest.raises(RestoreScopeError, match="captured from .* but this attempt"):
        await strategy.restore(env, current, details, ctx)
    assert env.execs == execs_before


async def test_archive_extraction_is_scoped_to_roots(tmp_path: Path) -> None:
    """Second layer: even past the listing check, tar writes only the roots.

    The host-side check is bypassed for this test so an archive with a
    member outside the root reaches extraction; the member arguments
    keep tar from writing it.
    """
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    root = tmp_path / "capture" / "data"
    outside = tmp_path / "capture" / "outside"
    root.mkdir(parents=True)
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    digest = _crafted_archive(
        storage / "ckpt-00001.tar.gz",
        [
            _member(_rel(root), tarfile.DIRTYPE),
            _member(_rel(root / "notes.txt")),
            _member(_rel(outside), tarfile.DIRTYPE),
            _member(_rel(outside / "planted.txt")),
        ],
        {_rel(root / "notes.txt"): b"legit\n", _rel(outside / "planted.txt"): b"evil"},
    )
    details = SnapshotDetails.model_validate(
        dict(
            snapshot_id="ckpt-00001",
            size_bytes=1,
            duration_ms=1,
            archive="ckpt-00001.tar.gz",
            content_sha256=digest,
        )
    )
    with patch(
        "inspect_ai.util._checkpoint._snapshot.archive._check_archive",
        return_value=None,
    ):
        await strategy.restore(
            env, SandboxBackupPaths(include=[str(root)]), details, ctx
        )

    assert (root / "notes.txt").read_bytes() == b"legit\n"
    assert not outside.exists()


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("archive", "../../../etc/passwd", "malformed archive name"),
        ("archive", "ckpt-00001.tar.zst; rm -rf /", "malformed archive name"),
        ("content_sha256", "$(reboot)", "malformed content_sha256"),
    ],
)
async def test_archive_restore_rejects_malformed_record(
    tmp_path: Path, field: str, value: str, match: str
) -> None:
    """Corrupted records fail validation before path joins / root scripts."""
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    record = {
        "snapshot_id": "ckpt-00001",
        "size_bytes": 0,
        "duration_ms": 0,
        "archive": "ckpt-00001.tar.gz",
        "content_sha256": "0" * 64,
        field: value,
    }
    details = SnapshotDetails.model_validate(record)
    paths = SandboxBackupPaths(include=[str(tmp_path / "capture")])
    with pytest.raises(RuntimeError, match=match):
        await strategy.restore(env, paths, details, _context(tmp_path / "sample"))


async def test_archive_discard_orphans(tmp_path: Path) -> None:
    """Every archive no committed checkpoint records is deleted."""
    strategy = ArchiveStrategy(sandbox_dir=str(tmp_path / "sandbox-tools"))
    ctx = _context(tmp_path / "sample")
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    for checkpoint_id in (1, 2, 3, 4):
        (storage / f"ckpt-{checkpoint_id:05d}.tar.gz").write_bytes(b"x")
    (storage / "stray.bin").write_bytes(b"x")

    # Checkpoint 2's file was lost (unparseable), so its archive is an
    # orphan just like the uncommitted tail (4).
    await strategy.discard_orphans(
        _committed((1, "ckpt-00001.tar.gz"), (3, "ckpt-00003.tar.gz")), ctx
    )

    assert sorted(p.name for p in storage.iterdir()) == [
        "ckpt-00001.tar.gz",
        "ckpt-00003.tar.gz",
    ]


async def test_archive_discard_orphans_requires_latest_archive(tmp_path: Path) -> None:
    strategy = ArchiveStrategy(sandbox_dir=str(tmp_path / "sandbox-tools"))
    ctx = _context(tmp_path / "sample")
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    (storage / "ckpt-00001.tar.gz").write_bytes(b"x")

    with pytest.raises(RuntimeError, match="absent"):
        await strategy.discard_orphans(
            _committed((1, "ckpt-00001.tar.gz"), (2, "ckpt-00002.tar.gz")), ctx
        )
    # Nothing was deleted before the check failed.
    assert [p.name for p in storage.iterdir()] == ["ckpt-00001.tar.gz"]
    # A missing storage area is the same contract violation, not a no-op.
    with pytest.raises(RuntimeError, match="absent"):
        await strategy.discard_orphans(
            _committed((1, "ckpt-00001.tar.gz")), _context(tmp_path / "nowhere")
        )


async def test_archive_snapshot_rejects_oversized_archive(tmp_path: Path) -> None:
    """An archive over ``max_snapshot_bytes`` fails the fire, leaving no file."""
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample", max_snapshot_bytes=1024)
    data_dir = tmp_path / "capture" / "data"
    _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    with pytest.raises(RuntimeError, match="max_sandbox_snapshot_bytes"):
        await strategy.snapshot(env, paths, 1, ctx)
    storage = Path(ctx.storage_dir)
    assert not storage.exists() or list(storage.iterdir()) == []
    assert not (Path(strategy._staging_root)).exists()


# --- LocalShellSandbox: a Linux-like tar on PATH ------------------------


def _fake_tar(bin_dir: Path, version: str) -> Path:
    """A ``tar`` in ``bin_dir`` answering ``--version`` with ``version``; every other call's arguments go to the returned log."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "calls.log"
    tar = bin_dir / "tar"
    tar.write_text(
        "#!/bin/sh\n"
        f'[ "$1" = "--version" ] && {{ echo {shlex.quote(version)}; exit 0; }}\n'
        f'printf "%s\\n" "$*" >> {shlex.quote(str(log))}\n'
    )
    tar.chmod(0o755)
    return log


def _run_tar(path: str, *args: str) -> None:
    """Run ``tar`` as a script would, resolved through ``path``."""
    subprocess.run(
        ["sh", "-c", 'tar "$@"', "sh", *args],
        env={**os.environ, "PATH": path},
        check=True,
        capture_output=True,
    )


def test_linux_like_path_shims_bsdtar_to_create_gnu_archives(tmp_path: Path) -> None:
    """With bsdtar on the host, ``tar -c`` gets the GNU-format flags and everything else passes through."""
    log = _fake_tar(tmp_path / "bin", "bsdtar 3.5.3 - libarchive 3.7.4 zlib/1.2.12")
    host = f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"
    shim_dir = tmp_path / "shim"

    path = linux_like_path(host, shim_dir)

    assert path == f"{shim_dir}{os.pathsep}{host}"
    assert shutil.which("tar", path=path) == str(shim_dir / "tar")
    _run_tar(path, "-cf", "-", "--exclude=.cache", "/data")
    _run_tar(path, "-xzf", "staged.tar.gz", "-C", "/", "--", "data")
    _run_tar(path, "-tf", "-")
    assert log.read_text().splitlines() == [
        "--format gnutar --no-xattrs --no-mac-metadata -cf - --exclude=.cache /data",
        "-xzf staged.tar.gz -C / -- data",
        "-tf -",
    ]


@pytest.mark.parametrize(
    "version", ["tar (GNU tar) 1.35", "BusyBox v1.36.1 multi-call binary."]
)
def test_linux_like_path_leaves_a_linux_tar_alone(tmp_path: Path, version: str) -> None:
    _fake_tar(tmp_path / "bin", version)
    host = f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"

    assert linux_like_path(host, tmp_path / "shim") == host
    assert not (tmp_path / "shim").exists()


def test_linux_like_path_without_a_tar_is_unchanged(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert linux_like_path(str(empty), tmp_path / "shim") == str(empty)
    assert not (tmp_path / "shim").exists()


# --- shared chunked copy-out -----------------------------------------


_COPY_CHUNK = 64 * 1024


def _copy_fixture(tmp_path: Path, size: int) -> tuple[Path, bytes]:
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    payload = bytes(bytearray((i * 7919 + i // 251) % 256 for i in range(size)))
    (sandbox_dir / "blob").write_bytes(payload)
    return sandbox_dir, payload


def test_copy_out_partial_path_hides_once(tmp_path: Path) -> None:
    """A hidden dest gets no second leading dot, so a `.prefix-*` sweep still matches."""
    assert (
        copy_out_partial_path(tmp_path / "blob.out") == tmp_path / ".blob.out.partial"
    )
    assert (
        copy_out_partial_path(tmp_path / ".egress-default-ckpt-00001.tar")
        == tmp_path / ".egress-default-ckpt-00001.tar.partial"
    )


async def test_copy_out_roundtrip_multi_chunk(tmp_path: Path) -> None:
    sandbox_dir, payload = _copy_fixture(tmp_path, 5 * _COPY_CHUNK + 123)
    dest = tmp_path / "host" / "blob.out"

    result = await copy_out(
        LocalShellSandbox(),
        src=str(sandbox_dir / "blob"),
        chunk_path=str(sandbox_dir / "chunk"),
        size=len(payload),
        dest=dest,
        max_bytes=len(payload),
        label="test copy",
        chunk_size=_COPY_CHUNK,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )

    assert dest.read_bytes() == payload
    assert result.size == len(payload)
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert not dest.with_name(".blob.out.partial").exists()


async def test_copy_out_rejects_reported_size_over_cap_before_reading(
    tmp_path: Path,
) -> None:
    sandbox_dir, payload = _copy_fixture(tmp_path, 2 * _COPY_CHUNK)
    dest = tmp_path / "host" / "blob.out"

    class _CountingSandbox(LocalShellSandbox):
        execs = 0

        async def exec(
            self,
            cmd: list[str],
            input: str | bytes | None = None,
            cwd: str | None = None,
            env: dict[str, str] | None = None,
            user: str | None = None,
            timeout: int | None = None,
            timeout_retry: bool = True,
            concurrency: bool = True,
        ) -> ExecResult[str]:
            _CountingSandbox.execs += 1
            return await super().exec(
                cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
            )

    with pytest.raises(RuntimeError, match="exceeds the max_sandbox_snapshot_bytes"):
        await copy_out(
            _CountingSandbox(),
            src=str(sandbox_dir / "blob"),
            chunk_path=str(sandbox_dir / "chunk"),
            size=len(payload),
            dest=dest,
            max_bytes=len(payload) - 1,
            label="test copy",
            chunk_size=_COPY_CHUNK,
        )
    assert _CountingSandbox.execs == 0
    assert not dest.exists()
    assert not dest.with_name(".blob.out.partial").exists()


async def test_copy_out_aborts_mid_transfer_when_bytes_exceed_cap(
    tmp_path: Path,
) -> None:
    """The cap binds on bytes actually read, not on the sandbox's size claim."""
    sandbox_dir, payload = _copy_fixture(tmp_path, 4 * _COPY_CHUNK)
    dest = tmp_path / "host" / "blob.out"
    # The sandbox under-reports the size (and the cap trusts that claim
    # only to the extent of letting the copy start).
    claimed = 2 * _COPY_CHUNK - 1

    with pytest.raises(RuntimeError, match="exceeded the max_sandbox_snapshot_bytes"):
        await copy_out(
            LocalShellSandbox(),
            src=str(sandbox_dir / "blob"),
            chunk_path=str(sandbox_dir / "chunk"),
            size=claimed,
            dest=dest,
            max_bytes=claimed,
            label="test copy",
            chunk_size=_COPY_CHUNK,
        )
    assert not dest.exists()
    assert not dest.with_name(".blob.out.partial").exists()


async def test_copy_out_rejects_short_file_and_digest_mismatch(tmp_path: Path) -> None:
    sandbox_dir, payload = _copy_fixture(tmp_path, 3 * _COPY_CHUNK)
    dest = tmp_path / "host" / "blob.out"
    partial = dest.with_name(".blob.out.partial")

    # Sandbox over-reports the size: the file runs out first.
    with pytest.raises(RuntimeError, match="unexpected EOF"):
        await copy_out(
            LocalShellSandbox(),
            src=str(sandbox_dir / "blob"),
            chunk_path=str(sandbox_dir / "chunk"),
            size=len(payload) + _COPY_CHUNK,
            dest=dest,
            max_bytes=1 << 30,
            label="test copy",
            chunk_size=_COPY_CHUNK,
        )
    assert not dest.exists() and not partial.exists()

    with pytest.raises(
        RuntimeError, match="received bytes do not match the sandbox-reported SHA-256"
    ):
        await copy_out(
            LocalShellSandbox(),
            src=str(sandbox_dir / "blob"),
            chunk_path=str(sandbox_dir / "chunk"),
            size=len(payload),
            dest=dest,
            max_bytes=1 << 30,
            label="test copy",
            chunk_size=_COPY_CHUNK,
            expected_sha256="0" * 64,
        )
    assert not dest.exists() and not partial.exists()


async def test_copy_out_cancelled_mid_transfer_leaves_no_partial(
    tmp_path: Path,
) -> None:
    """Cancellation between chunks removes the partial file (asyncio and trio)."""
    sandbox_dir, payload = _copy_fixture(tmp_path, 4 * _COPY_CHUNK)
    dest = tmp_path / "host" / "blob.out"
    partial = dest.with_name(".blob.out.partial")
    second_chunk_started = anyio.Event()

    class _StallingSandbox(LocalShellSandbox):
        """Blocks forever on the second chunk's ``dd``."""

        dd_calls = 0

        async def exec(
            self,
            cmd: list[str],
            input: str | bytes | None = None,
            cwd: str | None = None,
            env: dict[str, str] | None = None,
            user: str | None = None,
            timeout: int | None = None,
            timeout_retry: bool = True,
            concurrency: bool = True,
        ) -> ExecResult[str]:
            if any("dd if=" in part for part in cmd):
                _StallingSandbox.dd_calls += 1
                if _StallingSandbox.dd_calls == 2:
                    second_chunk_started.set()
                    await anyio.sleep_forever()
            return await super().exec(
                cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
            )

    async def _copy() -> None:
        await copy_out(
            _StallingSandbox(),
            src=str(sandbox_dir / "blob"),
            chunk_path=str(sandbox_dir / "chunk"),
            size=len(payload),
            dest=dest,
            max_bytes=1 << 30,
            label="test copy",
            chunk_size=_COPY_CHUNK,
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(_copy)
        await second_chunk_started.wait()
        # One chunk has landed in the partial file by now.
        assert partial.exists() and partial.stat().st_size == _COPY_CHUNK
        tg.cancel_scope.cancel()

    assert not dest.exists()
    assert not partial.exists()


async def test_archive_setup_reports_missing_tool(tmp_path: Path) -> None:
    class _NoZstdNoGzip(LocalShellSandbox):
        async def exec(self, cmd: list[str], **kwargs: object) -> ExecResult[str]:  # type: ignore[override]
            return ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr="missing required tool: tar",
            )

    strategy = ArchiveStrategy(sandbox_dir=str(tmp_path / "sandbox-tools"))
    with pytest.raises(RuntimeError, match="missing required tool"):
        await strategy.setup(_NoZstdNoGzip(), _context(tmp_path / "sample"))


def test_archive_checkpoint_id_parsing() -> None:
    assert _archive_checkpoint_id("ckpt-00007.tar.zst") == 7
    assert _archive_checkpoint_id("ckpt-00007.tar.gz") == 7
    assert _archive_checkpoint_id(".ckpt-00007.tar.gz.partial") is None
    assert _archive_checkpoint_id("other.txt") is None


def test_tar_pattern_conversion() -> None:
    assert _tar_pattern("**/.cache") == ".cache"
    assert _tar_pattern("/home/user/.cache") == "home/user/.cache"


# --- committed snapshot records --------------------------------------


def test_committed_snapshots_for_selects_one_sandbox_in_order() -> None:
    def _checkpoint(checkpoint_id: int, sandboxes: dict[str, str]) -> Checkpoint:
        return Checkpoint(
            checkpoint_id=checkpoint_id,
            trigger="turn",
            turn=checkpoint_id,
            created_at=datetime.now(timezone.utc),
            duration_ms=0,
            size_bytes=0,
            host=SnapshotDetails(snapshot_id="host", size_bytes=0, duration_ms=0),
            sandboxes={
                name: SnapshotDetails(snapshot_id=sid, size_bytes=0, duration_ms=0)
                for name, sid in sandboxes.items()
            },
        )

    checkpoints = [
        _checkpoint(1, {"default": "d1", "web": "w1"}),
        _checkpoint(2, {"web": "w2"}),
        _checkpoint(3, {"default": "d3", "web": "w3"}),
    ]

    assert [
        (c.checkpoint_id, c.details.snapshot_id)
        for c in committed_snapshots_for(checkpoints, "default")
    ] == [(1, "d1"), (3, "d3")]
    assert [
        c.details.snapshot_id for c in committed_snapshots_for(checkpoints, "web")
    ] == ["w1", "w2", "w3"]
    assert committed_snapshots_for(checkpoints, "other") == []


# --- snapshot details strategy identity ------------------------------


def test_snapshot_strategy_name_defaults_to_restic() -> None:
    details = SnapshotDetails(snapshot_id="abc", size_bytes=1, duration_ms=1)
    assert snapshot_strategy_name(details) == STRATEGY_RESTIC


def test_snapshot_strategy_name_round_trips_via_extra() -> None:
    details = SnapshotDetails.model_validate(
        dict(snapshot_id="ckpt-00001", size_bytes=1, duration_ms=1, strategy="archive")
    )
    reparsed = SnapshotDetails.model_validate_json(details.model_dump_json())
    assert snapshot_strategy_name(reparsed) == STRATEGY_ARCHIVE


# --- strategy pin (§4.7) ---------------------------------------------


async def test_pin_write_read_roundtrip(tmp_path: Path) -> None:
    assert await read_strategy_pin(str(tmp_path)) is None
    await write_strategy_pin(str(tmp_path), {"default": STRATEGY_ARCHIVE})
    assert await read_strategy_pin(str(tmp_path)) == {"default": STRATEGY_ARCHIVE}
    assert (tmp_path / "restic" / "snapshot-strategies.json").is_file()


def _check(
    pinned: dict[str, str] | None,
    configured: dict[str, str],
    *,
    live: set[str] | None = None,
    opted_out: set[str] | None = None,
    unscopable: dict[str, str] | None = None,
) -> None:
    check_strategy_pin(
        pinned=pinned,
        configured=configured,
        known_strategies=KNOWN_STRATEGY_NAMES,
        default_strategy=STRATEGY_RESTIC,
        live_sandboxes=live if live is not None else set(configured),
        opted_out=opted_out or set(),
        unscopable=unscopable or {},
    )


def test_pin_matching_strategies_pass() -> None:
    _check(
        {"default": STRATEGY_ARCHIVE, "web": STRATEGY_RESTIC},
        {"default": STRATEGY_ARCHIVE, "web": STRATEGY_RESTIC},
    )


def test_pin_mismatch_is_hard_error() -> None:
    with pytest.raises(RuntimeError, match="not supported"):
        _check({"default": STRATEGY_RESTIC}, {"default": STRATEGY_ARCHIVE})


def test_pin_absent_defaults_to_restic() -> None:
    _check(None, {"default": STRATEGY_RESTIC})
    with pytest.raises(RuntimeError, match="predates strategy selection"):
        _check(None, {"default": STRATEGY_ARCHIVE})


def test_pin_unknown_strategy_is_hard_error() -> None:
    with pytest.raises(RuntimeError, match="does not provide"):
        _check({"default": "zfs-clone"}, {"default": STRATEGY_RESTIC})


def test_pin_configured_sandbox_without_pin_entry_is_hard_error() -> None:
    with pytest.raises(RuntimeError, match="sandbox set changed"):
        _check(
            {"default": STRATEGY_RESTIC},
            {"default": STRATEGY_RESTIC, "web": STRATEGY_RESTIC},
        )


def test_pin_mirror_case_removed_sandbox_is_hard_error() -> None:
    # Pinned sandbox absent from this attempt's effective set and not
    # live → config change.
    with pytest.raises(RuntimeError, match="absent from this attempt"):
        _check(
            {"default": STRATEGY_RESTIC, "web": STRATEGY_ARCHIVE},
            {"default": STRATEGY_RESTIC},
            live={"default"},
        )
    # Opted out via an empty paths entry → also a config change.
    with pytest.raises(RuntimeError, match="absent from this attempt"):
        _check(
            {"default": STRATEGY_RESTIC, "web": STRATEGY_ARCHIVE},
            {"default": STRATEGY_RESTIC},
            live={"default", "web"},
            opted_out={"web"},
        )


def test_pin_mirror_case_resolution_failure_has_own_error() -> None:
    # Live, not opted out, yet absent from the effective set: home-dir
    # resolution flaked — distinct message and remedy (no config change
    # happened).
    with pytest.raises(RuntimeError, match="home directory") as excinfo:
        _check(
            {"default": STRATEGY_RESTIC, "web": STRATEGY_ARCHIVE},
            {"default": STRATEGY_RESTIC},
            live={"default", "web"},
        )
    assert "transient" in str(excinfo.value)


def test_pin_mirror_case_unscopable_home_has_own_error() -> None:
    # Live, not opted out, dropped because the home dir can't be scoped
    # for restore (HOME=/): permanent, so the remedy must not be "resume
    # again" — it is to configure the paths, opt out, or start fresh.
    reason = "checkpoint: home dir of sandbox 'web': a capture root of '/' ..."
    with pytest.raises(RuntimeError, match="cannot be scoped") as excinfo:
        _check(
            {"default": STRATEGY_RESTIC, "web": STRATEGY_ARCHIVE},
            {"default": STRATEGY_RESTIC},
            live={"default", "web"},
            unscopable={"web": reason},
        )
    message = str(excinfo.value)
    assert reason in message
    assert "transient" not in message
    assert "sandbox_paths" in message and "empty entry" in message


# --- storage subpath: sandbox name containment -------------------------------


@pytest.mark.parametrize("sandbox_name", ["default", "web-1", "db_2", "a.b"])
def test_strategy_storage_subpath_layouts(sandbox_name: str) -> None:
    assert (
        strategy_storage_subpath(STRATEGY_RESTIC, sandbox_name)
        == f"restic/sandboxes/{sandbox_name}"
    )
    assert (
        strategy_storage_subpath(STRATEGY_ARCHIVE, sandbox_name)
        == f"sandboxes/{sandbox_name}/{STRATEGY_ARCHIVE}"
    )


@pytest.mark.parametrize(
    "sandbox_name", ["../host", "a/b", "/abs", "..", ".", "", "a\\b", "a\x00"]
)
def test_strategy_storage_subpath_rejects_non_component_sandbox_name(
    sandbox_name: str,
) -> None:
    """A sandbox name must be one path component; it can't relocate storage."""
    for strategy in (STRATEGY_RESTIC, STRATEGY_ARCHIVE):
        with pytest.raises(ValueError, match="sandbox name"):
            strategy_storage_subpath(strategy, sandbox_name)
