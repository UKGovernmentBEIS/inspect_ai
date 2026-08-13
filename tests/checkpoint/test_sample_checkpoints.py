"""Tests for the sample checkpoints dir, restic-config.json, and checkpoint file writes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    RESUME_SOURCE_FILE,
    _read_restic_config,
    ensure_restic_config,
    ensure_sample_checkpoints_dir,
    resolve_resumable_sample_dir,
    resolve_resumable_sample_dir_in_chain,
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


# -- resume-source marker resolution ------------------------------------
#
# The marker is hydration's first write; the checkpoint files are its
# last (the commit point). `resolve_resumable_sample_dir` is what makes
# an interrupted hydration recoverable: a dir with no committed
# checkpoint but a marker resolves to the intact source it was resuming
# from.


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


async def test_resolve_own_committed_checkpoint_wins(tmp_path: Path) -> None:
    """A dir with a committed checkpoint resolves to itself, marker or not."""
    source = await _dir_with_checkpoint(tmp_path, "a")
    sample_dir = await _dir_with_checkpoint(tmp_path, "b")
    await write_resume_source_marker(sample_dir, source)

    resolved = await resolve_resumable_sample_dir(sample_dir)

    assert resolved is not None
    assert resolved.sample_dir == sample_dir
    assert resolved.checkpoint.checkpoint_id == 1


async def test_resolve_follows_marker_from_torn_hydration(tmp_path: Path) -> None:
    """No committed checkpoint + marker (a torn hydration) → the source."""
    source = await _dir_with_checkpoint(tmp_path, "a")
    torn = await ensure_sample_checkpoints_dir(str(tmp_path / "b.checkpoints"), "s", 0)
    await write_resume_source_marker(torn, source)

    resolved = await resolve_resumable_sample_dir(torn)

    assert resolved is not None
    assert resolved.sample_dir == source
    assert resolved.checkpoint.checkpoint_id == 1


async def test_resolve_follows_marker_chain(tmp_path: Path) -> None:
    """Two torn hydrations in a row still resolve back to the source."""
    source = await _dir_with_checkpoint(tmp_path, "a")
    torn1 = await ensure_sample_checkpoints_dir(str(tmp_path / "b.checkpoints"), "s", 0)
    await write_resume_source_marker(torn1, source)
    torn2 = await ensure_sample_checkpoints_dir(str(tmp_path / "c.checkpoints"), "s", 0)
    await write_resume_source_marker(torn2, torn1)

    resolved = await resolve_resumable_sample_dir(torn2)

    assert resolved is not None
    assert resolved.sample_dir == source


async def test_resolve_none_when_nothing_committed(tmp_path: Path) -> None:
    """No checkpoint and no marker (fresh dir) → None (run fresh)."""
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "a.checkpoints"), "s", 0
    )
    assert await resolve_resumable_sample_dir(sample_dir) is None
    # missing dir behaves the same as an empty one
    assert await resolve_resumable_sample_dir(str(tmp_path / "missing")) is None


async def test_resolve_none_on_dangling_marker(tmp_path: Path) -> None:
    """A marker whose source has been deleted → None (run fresh)."""
    torn = await ensure_sample_checkpoints_dir(str(tmp_path / "b.checkpoints"), "s", 0)
    await write_resume_source_marker(torn, str(tmp_path / "deleted.checkpoints/s__0"))

    assert await resolve_resumable_sample_dir(torn) is None


async def test_resolve_none_on_torn_marker(tmp_path: Path) -> None:
    """A marker interrupted mid-write parses as absent → None (run fresh)."""
    torn = await ensure_sample_checkpoints_dir(str(tmp_path / "b.checkpoints"), "s", 0)
    (Path(torn) / RESUME_SOURCE_FILE).write_text('{"source_sample')

    assert await resolve_resumable_sample_dir(torn) is None


async def test_resolve_bails_on_marker_cycle(tmp_path: Path) -> None:
    """A hand-crafted marker cycle returns None rather than looping."""
    d1 = await ensure_sample_checkpoints_dir(str(tmp_path / "a.checkpoints"), "s", 0)
    d2 = await ensure_sample_checkpoints_dir(str(tmp_path / "b.checkpoints"), "s", 0)
    await write_resume_source_marker(d1, d2)
    await write_resume_source_marker(d2, d1)

    assert await resolve_resumable_sample_dir(d1) is None


async def test_resolve_in_chain_walks_eval_markers(tmp_path: Path) -> None:
    """A sample with no per-sample trail resolves via the eval-dir chain.

    The nearest attempt's eval dir has neither a sample dir nor a
    per-sample marker for this sample (its greedy copy skipped it, or
    the sample was fed in mid-run) — the eval dir's permanent
    resume-source marker leads one attempt back, where the payload is.
    """
    old_eval = str(tmp_path / "a.checkpoints")
    old_sample = await ensure_sample_checkpoints_dir(old_eval, "s", 0)
    await write_checkpoint_file(
        sample_checkpoints_dir=old_sample,
        checkpoint=_checkpoint(
            checkpoint_id=1, trigger="turn", turn=1, host=_info("snap-1")
        ),
    )
    new_eval = str(tmp_path / "b.checkpoints")
    Path(new_eval).mkdir()
    await write_resume_source_marker(new_eval, old_eval)

    resolved = await resolve_resumable_sample_dir_in_chain(new_eval, "s", 0)

    assert resolved is not None
    assert resolved.sample_dir == old_sample


async def test_resolve_in_chain_prefers_nearest_attempt(tmp_path: Path) -> None:
    """The chain stops at the first attempt holding the sample's payload."""
    old_eval = str(tmp_path / "a.checkpoints")
    await _dir_with_checkpoint(tmp_path, "a")
    new_eval = str(tmp_path / "b.checkpoints")
    new_sample = await ensure_sample_checkpoints_dir(new_eval, "s", 0)
    await write_checkpoint_file(
        sample_checkpoints_dir=new_sample,
        checkpoint=_checkpoint(
            checkpoint_id=2, trigger="turn", turn=2, host=_info("snap-2")
        ),
    )
    await write_resume_source_marker(new_eval, old_eval)

    resolved = await resolve_resumable_sample_dir_in_chain(new_eval, "s", 0)

    assert resolved is not None
    assert resolved.sample_dir == new_sample
    assert resolved.checkpoint.checkpoint_id == 2


async def test_resolve_in_chain_none_when_chain_exhausted(tmp_path: Path) -> None:
    old_eval = str(tmp_path / "a.checkpoints")
    Path(old_eval).mkdir()
    new_eval = str(tmp_path / "b.checkpoints")
    Path(new_eval).mkdir()
    await write_resume_source_marker(new_eval, old_eval)

    assert await resolve_resumable_sample_dir_in_chain(new_eval, "s", 0) is None
