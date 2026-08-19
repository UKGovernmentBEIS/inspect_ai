"""Tests for the sample checkpoints dir, restic-config.json, and checkpoint file writes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    RESUME_SOURCE_FILE,
    _read_restic_config,
    delete_resume_source_marker,
    delete_sample_checkpoints_dir,
    ensure_restic_config,
    ensure_sample_checkpoints_dir,
    read_resume_source_marker,
    resolve_resumable_sample_dir,
    sample_checkpoints_dir,
    scan_latest_committed_checkpoint,
    write_checkpoint_file,
    write_resume_source_marker,
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


# -- resume resolution ---------------------------------------------------
#
# Detection looks only in a sample's own dir: the retry startup copy
# replicated every sample dir from the newest clean attempt, so a
# sample either has a committed checkpoint here or runs fresh. The
# eval-level marker (dirty flag) is exercised in test_resume_copy.py.


async def _dir_with_checkpoint(root: Path, name: str) -> str:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(root / f"{name}.checkpoints"), "s", 0
    )
    await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=1, trigger="turn", turn=1, host=_info("snap-1")
        ),
    )
    return sample_dir


async def test_resolve_committed_checkpoint_resolves_to_dir(tmp_path: Path) -> None:
    """A dir with a committed checkpoint resolves to itself."""
    sample_dir = await _dir_with_checkpoint(tmp_path, "a")

    resolved = await resolve_resumable_sample_dir(sample_dir)

    assert resolved is not None
    assert resolved.sample_dir == sample_dir
    assert resolved.checkpoint.checkpoint_id == 1


async def test_resolve_none_when_nothing_committed(tmp_path: Path) -> None:
    """No committed checkpoint (empty or torn dir) → None (fall through)."""
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "a.checkpoints"), "s", 0
    )
    assert await resolve_resumable_sample_dir(sample_dir) is None
    # missing dir behaves the same as an empty one
    assert await resolve_resumable_sample_dir(str(tmp_path / "missing")) is None


async def test_resume_source_marker_roundtrip(tmp_path: Path) -> None:
    """Write → read → delete → read None; delete is idempotent."""
    eval_dir = str(tmp_path / "b.checkpoints")
    Path(eval_dir).mkdir()
    await write_resume_source_marker(eval_dir, str(tmp_path / "a.checkpoints"))

    marker = await read_resume_source_marker(eval_dir)
    assert marker is not None
    assert marker.source_dir == str(tmp_path / "a.checkpoints")

    await delete_resume_source_marker(eval_dir)
    assert await read_resume_source_marker(eval_dir) is None
    await delete_resume_source_marker(eval_dir)  # idempotent


async def test_read_resume_source_marker_torn_is_none(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "b.checkpoints")
    Path(eval_dir).mkdir()
    (Path(eval_dir) / RESUME_SOURCE_FILE).write_text('{"source_d')

    assert await read_resume_source_marker(eval_dir) is None


async def test_delete_sample_checkpoints_dir(tmp_path: Path) -> None:
    """Removes the whole dir (invalidated sample); missing dir is a no-op."""
    eval_dir = str(tmp_path / "a.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s", 0)
    (Path(sample_dir) / "restic" / "host").mkdir(parents=True)
    (Path(sample_dir) / "restic" / "host" / "config").write_text("cfg")
    await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=1, trigger="turn", turn=1, host=_info("snap-1")
        ),
    )

    await delete_sample_checkpoints_dir(eval_dir, "s", 0)

    assert not Path(sample_dir).exists()
    await delete_sample_checkpoints_dir(eval_dir, "s", 0)  # idempotent
