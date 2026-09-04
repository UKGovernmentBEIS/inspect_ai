"""Unit tests for the pluggable sandbox snapshot strategies.

Covers the §4.7 strategy pin semantics, the shared chunked copy-out
primitive, and the ``archive`` strategy's mechanics (snapshot → restore
roundtrip, hash verification, orphan discard) against a *local shell*
sandbox fake: ``exec`` runs the scripts with the host's ``sh`` and file
APIs map to host paths, so the strategy's real shell pipelines (tar |
compress, dd chunking, sha256 verify-then-extract) execute for real — no
Docker required. The strategy's in-sandbox root-only area is pointed at
a temp dir via its ``sandbox_dir`` parameter; ``user="root"`` is ignored
by the fake.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import anyio
import pytest
from test_helpers.local_shell_sandbox import LocalShellSandbox

from inspect_ai.util._checkpoint._copy import copy_out, copy_out_partial_path
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
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
)
from inspect_ai.util._checkpoint._snapshot.types import (
    CommittedSnapshot,
    PriorAttempt,
    SnapshotContext,
)
from inspect_ai.util._checkpoint.sandbox_paths import SandboxBackupPaths
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
    """Populate a capture tree: text, multi-chunk binary, and a cache dir."""
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

    details = await strategy.snapshot(env, paths, 1, ctx)

    assert details.snapshot_id == "ckpt-00001"
    assert snapshot_strategy_name(details) == STRATEGY_ARCHIVE
    extra = details.model_extra or {}
    archives = list(Path(ctx.storage_dir).iterdir())
    assert [a.name for a in archives] == [extra["archive"]]
    assert details.size_bytes == archives[0].stat().st_size
    # In-sandbox staging fully cleaned up after capture.
    assert not (Path(strategy._staging_root)).exists()

    # Wipe the captured tree (cache included), then restore into the
    # "fresh sandbox".
    for rel in files:
        (data_dir / rel).unlink()
    (data_dir / ".cache" / "junk").unlink()
    (data_dir / "extra-not-in-snapshot.txt").write_bytes(b"post-capture")

    await strategy.restore(env, details, ctx)

    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content
    # Excluded at capture: the cache dir's contents are not in the
    # archive, so restore does not recreate them.
    assert not (data_dir / ".cache" / "junk").exists()
    assert not (Path(strategy._staging_root)).exists()


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
    await strategy.restore(env, details, ctx)
    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content


async def test_archive_snapshot_tolerates_tar_exit_1(tmp_path: Path) -> None:
    """Tar exit 1 (file changed while reading) must not fail the fire.

    Regression test for the fd-3 exit-status capture: with ``set -e``
    active, dash/ash abort the capture subshell on tar's non-zero exit
    before ``echo $? >&3`` runs, so the tolerated exit 1 used to fail
    the snapshot with a blank status. A shim ``tar`` that produces a
    valid archive but exits 1 makes the case deterministic.
    """
    real_tar = shutil.which("tar")
    assert real_tar is not None
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "tar"
    shim.write_text(f'#!/bin/sh\n"{real_tar}" "$@"\nexit 1\n')
    shim.chmod(0o755)
    env = LocalShellSandbox(
        extra_env={"PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"}
    )
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    files = _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    details = await strategy.snapshot(env, paths, 1, ctx)

    # Restore with an un-shimmed tar: the shim only simulates the
    # capture-time "file changed as we read it" warning.
    for rel in files:
        (data_dir / rel).unlink()
    await strategy.restore(LocalShellSandbox(), details, ctx)
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
            if cmd == ["sh", "-c", self.cleanup_script]:
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
    await strategy.restore(LocalShellSandbox(), details, ctx)
    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content


async def test_archive_restore_rejects_corrupt_archive(tmp_path: Path) -> None:
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    details = await strategy.snapshot(env, paths, 1, ctx)
    extra = details.model_extra or {}
    archive = Path(ctx.storage_dir) / str(extra["archive"])

    # Flip bytes in the stored archive; the recorded digest no longer
    # matches, so restore must fail *before* extracting anything.
    corrupted = bytearray(archive.read_bytes())
    corrupted[10] ^= 0xFF
    archive.write_bytes(bytes(corrupted))

    marker = data_dir / "notes.txt"
    marker.write_bytes(b"post-capture content")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        await strategy.restore(env, details, ctx)
    # Nothing was extracted over the live tree.
    assert marker.read_bytes() == b"post-capture content"


async def test_archive_restore_without_ref_uses_latest_archive(tmp_path: Path) -> None:
    """Restore with no committed record falls back to the newest archive.

    E.g. the kill tore the only checkpoint file mid-write; restic-parity
    degenerate-case semantics.
    """
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    ctx = _context(tmp_path / "sample")
    data_dir = tmp_path / "capture" / "data"
    files = _write_data(data_dir)
    paths = SandboxBackupPaths(include=[str(data_dir)])

    await strategy.snapshot(env, paths, 1, ctx)
    marker = data_dir / "notes.txt"
    marker.write_bytes(b"second capture\n")
    await strategy.snapshot(env, paths, 2, ctx)

    for rel in files:
        (data_dir / rel).unlink()
    await strategy.restore(env, None, ctx)
    assert marker.read_bytes() == b"second capture\n"
    assert (data_dir / "nested/blob.bin").read_bytes() == files["nested/blob.bin"]


async def test_archive_restore_without_ref_and_no_archives_errors(
    tmp_path: Path,
) -> None:
    env = LocalShellSandbox()
    strategy = await _strategy(env, tmp_path)
    with pytest.raises(RuntimeError, match="no adopted archives"):
        await strategy.restore(env, None, _context(tmp_path / "sample"))


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
    with pytest.raises(RuntimeError, match=match):
        await strategy.restore(env, details, _context(tmp_path / "sample"))


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

    with pytest.raises(RuntimeError, match="corrupted in transit"):
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
            if "dd if=" in cmd[-1]:
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


async def test_archive_adopt_copies_prior_attempt(tmp_path: Path) -> None:
    strategy = ArchiveStrategy(sandbox_dir=str(tmp_path / "sandbox-tools"))
    ctx = _context(tmp_path / "new-sample", resuming=True)
    prior_dir = tmp_path / "prior-sample"
    prior = PriorAttempt(
        sample_checkpoints_dir=str(prior_dir),
        storage_subpath=ctx.storage_subpath,
    )
    prior_storage = prior_dir / ctx.storage_subpath
    prior_storage.mkdir(parents=True)
    (prior_storage / "ckpt-00004.tar.gz").write_bytes(b"archive-bytes")

    await strategy.adopt(prior, ctx)

    assert (
        Path(ctx.storage_dir) / "ckpt-00004.tar.gz"
    ).read_bytes() == b"archive-bytes"


async def test_archive_adopt_raises_on_empty_prior(tmp_path: Path) -> None:
    strategy = ArchiveStrategy(sandbox_dir=str(tmp_path / "sandbox-tools"))
    ctx = _context(tmp_path / "new-sample", resuming=True)
    prior = PriorAttempt(
        sample_checkpoints_dir=str(tmp_path / "prior-sample"),
        storage_subpath=ctx.storage_subpath,
    )
    with pytest.raises(RuntimeError, match="no files were found"):
        await strategy.adopt(prior, ctx)


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
) -> None:
    check_strategy_pin(
        pinned=pinned,
        configured=configured,
        known_strategies=KNOWN_STRATEGY_NAMES,
        default_strategy=STRATEGY_RESTIC,
        live_sandboxes=live if live is not None else set(configured),
        opted_out=opted_out or set(),
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
    with pytest.raises(RuntimeError, match="home directory"):
        _check(
            {"default": STRATEGY_RESTIC, "web": STRATEGY_ARCHIVE},
            {"default": STRATEGY_RESTIC},
            live={"default", "web"},
        )
