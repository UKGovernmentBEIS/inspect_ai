"""Tests for the sample checkpoints dir, restic-config.json, and checkpoint file writes."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    _read_restic_config,
    ensure_restic_config,
    ensure_sample_checkpoints_dir,
    sample_checkpoints_dir,
    scan_committed_checkpoints,
    scan_latest_committed_checkpoint,
    write_checkpoint_file,
)
from inspect_ai.util._checkpoint._layout.schemas import (
    Checkpoint,
    ResticConfig,
    SnapshotDetails,
)
from inspect_ai.util._checkpoint._triggers import CheckpointTriggerKind


def _info(
    snapshot_id: str, size_bytes: int = 0, duration_ms: int = 0
) -> SnapshotDetails:
    return SnapshotDetails(
        snapshot_id=snapshot_id, size_bytes=size_bytes, duration_ms=duration_ms
    )


def _checkpoint(
    *,
    checkpoint_id: int,
    trigger: CheckpointTriggerKind,
    turn: int,
    host: SnapshotDetails,
    sandboxes: dict[str, SnapshotDetails] | None = None,
    duration_ms: int = 0,
) -> Checkpoint:
    sb = sandboxes or {}
    return Checkpoint(
        checkpoint_id=checkpoint_id,
        trigger=trigger,
        turn=turn,
        created_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
        size_bytes=host.size_bytes + sum(s.size_bytes for s in sb.values()),
        host=host,
        sandboxes=sb,
    )


def test_sample_checkpoints_dir_uses_sample_id_and_epoch() -> None:
    assert (
        sample_checkpoints_dir("/logs/foo.checkpoints", "sample-7", 0)
        == "/logs/foo.checkpoints/sample-7__0"
    )


def test_sample_checkpoints_dir_accepts_int_sample_id() -> None:
    assert (
        sample_checkpoints_dir("/logs/foo.checkpoints", 42, 1)
        == "/logs/foo.checkpoints/42__1"
    )


async def test_ensure_creates_dir_and_returns_path(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    assert Path(sample_dir).is_dir()
    assert sample_dir == f"{eval_dir}/s1__0"


async def test_ensure_is_idempotent(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    a = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    b = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    assert a == b
    assert Path(a).is_dir()


async def test_ensure_creates_parent_eval_dir(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    assert Path(eval_dir).is_dir()


async def test_ensure_restic_config_mints_password_on_first_call(
    tmp_path: Path,
) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    sample = await ensure_restic_config(sample_dir)
    assert sample.restic_password
    assert (Path(sample_dir) / "restic" / "restic-config.json").is_file()


async def test_ensure_restic_config_preserves_password_on_second_call(
    tmp_path: Path,
) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    first = await ensure_restic_config(sample_dir)
    second = await ensure_restic_config(sample_dir)
    assert first.restic_password == second.restic_password


async def test_ensure_restic_config_different_samples_get_distinct_passwords(
    tmp_path: Path,
) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    a_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    b_dir = await ensure_sample_checkpoints_dir(eval_dir, "s2", 0)
    a = await ensure_restic_config(a_dir)
    b = await ensure_restic_config(b_dir)
    assert a.restic_password != b.restic_password


async def test_read_restic_config_returns_written_value(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    written = await ensure_restic_config(sample_dir)
    read = await _read_restic_config(sample_dir)
    assert read.restic_password == written.restic_password


async def test_restic_config_round_trip_pydantic(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    await ensure_restic_config(sample_dir)
    raw = (Path(sample_dir) / "restic" / "restic-config.json").read_text()
    parsed = ResticConfig.model_validate_json(raw)
    assert parsed.restic_password


async def test_write_checkpoint_file_returns_zero_padded_path(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s1", 0
    )
    path = await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=1,
            trigger="turn",
            turn=3,
            host=_info("snap-1"),
        ),
    )
    assert path == f"{sample_dir}/ckpt-00001.json"
    assert Path(path).is_file()


async def test_checkpoint_file_contents_round_trip(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    path = await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=42,
            trigger="manual",
            turn=7,
            host=_info("snap-42", size_bytes=1000, duration_ms=10),
            sandboxes={"default": _info("sb-42", size_bytes=234, duration_ms=20)},
            duration_ms=99,
        ),
    )
    checkpoint = Checkpoint.model_validate_json(Path(path).read_text())
    assert checkpoint.checkpoint_id == 42
    assert checkpoint.trigger == "manual"
    assert checkpoint.turn == 7
    assert checkpoint.host.snapshot_id == "snap-42"
    assert checkpoint.host.duration_ms == 10
    assert checkpoint.sandboxes["default"].snapshot_id == "sb-42"
    assert checkpoint.size_bytes == 1234  # rolled-up total
    assert checkpoint.duration_ms == 99  # whole-cycle


async def test_checkpoint_file_filename_zero_padded_for_lexical_sort(
    tmp_path: Path,
) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    paths = [
        await write_checkpoint_file(
            sample_checkpoints_dir=sample_dir,
            checkpoint=_checkpoint(
                checkpoint_id=cid,
                trigger="turn",
                turn=cid,
                host=_info(f"snap-{cid}"),
            ),
        )
        for cid in (1, 2, 10, 100)
    ]
    names = [Path(p).name for p in paths]
    assert names == sorted(names)
    assert names == [
        "ckpt-00001.json",
        "ckpt-00002.json",
        "ckpt-00010.json",
        "ckpt-00100.json",
    ]


async def test_checkpoint_file_is_pretty_printed_json(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    path = await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=1,
            trigger="turn",
            turn=1,
            host=_info("snap-1"),
        ),
    )
    raw = Path(path).read_text()
    assert json.loads(raw)["checkpoint_id"] == 1
    assert "\n" in raw


async def test_scan_latest_committed_checkpoint_returns_latest_parseable(
    tmp_path: Path,
) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=1,
            trigger="turn",
            turn=1,
            host=_info("snap-1"),
        ),
    )
    await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=2,
            trigger="agent_complete",
            turn=2,
            host=_info("snap-2"),
        ),
    )
    (Path(sample_dir) / "ckpt-00003.json").write_text("{")

    checkpoint = await scan_latest_committed_checkpoint(sample_dir)

    assert checkpoint is not None
    assert checkpoint.checkpoint_id == 2
    assert checkpoint.trigger == "agent_complete"


async def test_scan_committed_checkpoints_skips_torn_files_in_order(
    tmp_path: Path,
) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    for checkpoint_id in (3, 1):
        await write_checkpoint_file(
            sample_checkpoints_dir=sample_dir,
            checkpoint=_checkpoint(
                checkpoint_id=checkpoint_id,
                trigger="turn",
                turn=checkpoint_id,
                host=_info(f"snap-{checkpoint_id}"),
            ),
        )
    (Path(sample_dir) / "ckpt-00002.json").write_text("{")
    (Path(sample_dir) / "ckpt-00004.json").write_text("{")

    committed = await scan_committed_checkpoints(sample_dir)

    assert [c.checkpoint_id for c in committed] == [1, 3]
    latest = await scan_latest_committed_checkpoint(sample_dir)
    assert latest is not None and latest.checkpoint_id == committed[-1].checkpoint_id
    assert await scan_committed_checkpoints(str(tmp_path / "missing")) == []


async def test_scan_committed_checkpoints_propagates_read_errors(
    tmp_path: Path,
) -> None:
    """An unreadable (not unparseable) file fails the scan instead of vanishing.

    The list drives orphan discard on resume, which deletes every snapshot
    not in it, so a transient remote read failure must not read as "this
    checkpoint was never committed".
    """
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    for checkpoint_id in (1, 2, 3):
        await write_checkpoint_file(
            sample_checkpoints_dir=sample_dir,
            checkpoint=_checkpoint(
                checkpoint_id=checkpoint_id,
                trigger="turn",
                turn=checkpoint_id,
                host=_info(f"snap-{checkpoint_id}"),
            ),
        )
    real_fs = get_async_filesystem()

    class _FlakyFs:
        def __getattr__(self, name: str) -> Any:
            return getattr(real_fs, name)

        async def read_file(self, filename: str) -> bytes:
            if filename.endswith("ckpt-00003.json"):
                raise OSError("connection reset by peer")
            return await real_fs.read_file(filename)

    # Resolve the submodule explicitly: the `_layout` package re-exports a
    # *function* named `sample_checkpoints_dir`, so a dotted `patch` target
    # (or `from _layout import sample_checkpoints_dir`) lands on that
    # function instead of the module on Python 3.10.
    module = importlib.import_module(
        "inspect_ai.util._checkpoint._layout.sample_checkpoints_dir"
    )
    with patch.object(
        module,
        "get_async_filesystem",
        return_value=_FlakyFs(),
    ):
        with pytest.raises(OSError, match="connection reset"):
            await scan_committed_checkpoints(sample_dir)
        # The latest-only scan must not fall back to checkpoint 2 either:
        # the next fire would reuse id 3 and overwrite the committed file.
        with pytest.raises(OSError, match="connection reset"):
            await scan_latest_committed_checkpoint(sample_dir)
