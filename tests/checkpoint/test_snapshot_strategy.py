"""Unit tests for the pluggable sandbox snapshot strategies.

Covers the §4.7 strategy pin semantics and the ``archive`` strategy's
mechanics (snapshot → restore roundtrip, hash verification, orphan
discard) against a *local shell* sandbox fake: ``exec`` runs
the scripts with the host's ``sh`` and file APIs map to host paths, so
the strategy's real shell pipelines (tar | compress, dd chunking,
sha256 verify-then-extract) execute for real — no Docker required. The
strategy's in-sandbox root-only area is pointed at a temp dir via its
``sandbox_dir`` parameter; ``user="root"`` is ignored by the fake.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal, Union, overload

import pytest

from inspect_ai.util._checkpoint._layout.schemas import SnapshotDetails
from inspect_ai.util._checkpoint._snapshot import snapshot_strategy_name
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
    PriorAttempt,
    SnapshotContext,
)
from inspect_ai.util._checkpoint.sandbox_paths import SandboxBackupPaths
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult


class _LocalShellSandbox(SandboxEnvironment):
    """Sandbox fake that executes ``exec`` on the host shell.

    ``extra_env`` overlays the inherited environment (e.g. a ``PATH``
    with a shim dir prepended) for every ``exec``.
    """

    def __init__(self, extra_env: dict[str, str] | None = None) -> None:
        self._extra_env = extra_env

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
        input_bytes = input.encode() if isinstance(input, str) else input
        run_env = {**os.environ, **self._extra_env} if self._extra_env else None
        proc = subprocess.run(
            cmd, input=input_bytes, capture_output=True, timeout=120, env=run_env
        )
        return ExecResult(
            success=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout.decode(errors="replace"),
            stderr=proc.stderr.decode(errors="replace"),
        )

    async def write_file(self, file: str, contents: str | bytes) -> None:
        data = contents.encode() if isinstance(contents, str) else contents
        Path(file).write_bytes(data)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        if text:
            return Path(file).read_text()
        return Path(file).read_bytes()

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


def _context(sample_root: Path, *, resuming: bool = False) -> SnapshotContext:
    subpath = f"sandboxes/default/{STRATEGY_ARCHIVE}"
    return SnapshotContext(
        sandbox_name="default",
        storage_dir=str(sample_root / subpath),
        storage_subpath=subpath,
        secret="test-secret",
        resuming=resuming,
    )


async def _strategy(env: _LocalShellSandbox, tmp_path: Path) -> ArchiveStrategy:
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
    env = _LocalShellSandbox()
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
    env = _LocalShellSandbox()
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
    env = _LocalShellSandbox(
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
    await strategy.restore(_LocalShellSandbox(), details, ctx)
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

    class _CleanupRaisingSandbox(_LocalShellSandbox):
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
    await strategy.restore(_LocalShellSandbox(), details, ctx)
    for rel, content in files.items():
        assert (data_dir / rel).read_bytes() == content


async def test_archive_restore_rejects_corrupt_archive(tmp_path: Path) -> None:
    env = _LocalShellSandbox()
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
    env = _LocalShellSandbox()
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
    env = _LocalShellSandbox()
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
    env = _LocalShellSandbox()
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
    strategy = ArchiveStrategy(sandbox_dir=str(tmp_path / "sandbox-tools"))
    ctx = _context(tmp_path / "sample")
    storage = Path(ctx.storage_dir)
    storage.mkdir(parents=True)
    for checkpoint_id in (1, 2, 3):
        (storage / f"ckpt-{checkpoint_id:05d}.tar.gz").write_bytes(b"x")

    await strategy.discard_orphans(2, ctx)

    assert sorted(p.name for p in storage.iterdir()) == [
        "ckpt-00001.tar.gz",
        "ckpt-00002.tar.gz",
    ]


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
    class _NoZstdNoGzip(_LocalShellSandbox):
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
