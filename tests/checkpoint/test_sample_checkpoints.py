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
from inspect_ai.util._checkpoint._layout._paths import sample_dir_segment
from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    _read_restic_config,
    checkpoint_file_id,
    delete_sample_checkpoints_dir,
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


@pytest.mark.parametrize("error_type", [OSError, FileNotFoundError])
async def test_scan_committed_checkpoints_propagates_read_errors(
    tmp_path: Path,
    error_type: type[OSError],
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
                raise error_type("checkpoint read failed")
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
        with pytest.raises(error_type, match="checkpoint read failed"):
            await scan_committed_checkpoints(sample_dir)
        if error_type is FileNotFoundError:
            latest = await scan_latest_committed_checkpoint(sample_dir)
            assert latest is not None and latest.checkpoint_id == 2
        else:
            # A transport failure must not make an existing checkpoint vanish.
            with pytest.raises(error_type, match="checkpoint read failed"):
                await scan_latest_committed_checkpoint(sample_dir)


# -- resume resolution ---------------------------------------------------
#
# Detection looks only in a sample's own dir: the retry startup copy
# replicated every sample dir from the retried attempt (whose log's
# existence proves the copy completed), so a sample either has a
# committed checkpoint here or runs fresh.


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


async def test_scan_committed_checkpoint(tmp_path: Path) -> None:
    """A dir with a committed checkpoint scans to that checkpoint."""
    sample_dir = await _dir_with_checkpoint(tmp_path, "a")

    checkpoint = await scan_latest_committed_checkpoint(sample_dir)

    assert checkpoint is not None
    assert checkpoint.checkpoint_id == 1


async def test_scan_none_when_nothing_committed(tmp_path: Path) -> None:
    """No committed checkpoint (empty or missing dir) → None (run fresh)."""
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "a.checkpoints"), "s", 0
    )
    assert await scan_latest_committed_checkpoint(sample_dir) is None
    # missing dir behaves the same as an empty one
    assert await scan_latest_committed_checkpoint(str(tmp_path / "missing")) is None


def test_checkpoint_file_id() -> None:
    assert checkpoint_file_id("ckpt-00007.json") == 7
    assert checkpoint_file_id("ckpt-123456.json") == 123456
    assert checkpoint_file_id("ckpt-foo.json") is None
    assert checkpoint_file_id("ckpt-1_0.json") is None
    assert checkpoint_file_id("ckpt-00007.tar.zst") is None
    assert checkpoint_file_id("ckpt-00007.json.tmp") is None
    assert checkpoint_file_id("restic-config.json") is None


@pytest.mark.parametrize(
    "name",
    [
        "ckpt-1.json",  # int-parses, but not the zero-padded form the writer emits
        "ckpt-000001.json",  # a second name for id 1
        "ckpt-00007.json\n",  # `$` would accept a trailing newline
        "ckpt-\u0663\u0663\u0663\u0663\u0663.json",  # non-ASCII digits: `\\d` accepts them
        "ckpt- 0005.json",
        "xckpt-00007.json",
    ],
)
def test_checkpoint_file_id_accepts_only_the_written_form(name: str) -> None:
    """One name per id: the file a listing offers must round-trip through the writer."""
    assert checkpoint_file_id(name) is None


@pytest.mark.parametrize("sample_id", ["../../escape", "a/b", "/abs", "..", ""])
def test_sample_checkpoints_dir_contains_hostile_sample_id(sample_id: str) -> None:
    """A dataset id with `/` or `..` cannot relocate the per-sample tree."""
    eval_dir = "/logs/foo.checkpoints"
    sample_dir = sample_checkpoints_dir(eval_dir, sample_id, 0)
    assert sample_dir.startswith(f"{eval_dir}/")
    segment = sample_dir.removeprefix(f"{eval_dir}/")
    assert segment == f"{sample_dir_segment(sample_id)}__0"
    assert "/" not in segment
    assert segment.split("__")[0] not in (".", "..")


async def test_ensure_with_hostile_sample_id_creates_dir_inside_eval_dir(
    tmp_path: Path,
) -> None:
    eval_dir = tmp_path / "foo.checkpoints"
    sample_dir = Path(await ensure_sample_checkpoints_dir(str(eval_dir), "../../x", 0))
    assert sample_dir.is_dir()
    assert sample_dir.parent == eval_dir
    assert not (tmp_path / "x__0").exists()
    assert not (tmp_path.parent / "x__0").exists()


async def test_hostile_sample_id_write_and_resume_lookup_agree(tmp_path: Path) -> None:
    """The write path and the resume lookup derive the same dir name."""
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_id = "task/variant-3"
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, sample_id, 1)
    lookup_dir = sample_checkpoints_dir(eval_dir, sample_id, 1)
    assert lookup_dir == sample_dir
    assert await scan_latest_committed_checkpoint(lookup_dir) is None
    await write_checkpoint_file(
        sample_checkpoints_dir=sample_dir,
        checkpoint=_checkpoint(
            checkpoint_id=1, trigger="turn", turn=1, host=_info("snap-1")
        ),
    )
    checkpoint = await scan_latest_committed_checkpoint(lookup_dir)
    assert checkpoint is not None and checkpoint.checkpoint_id == 1


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

    log_location = str(tmp_path / "a.eval")
    await delete_sample_checkpoints_dir(eval_dir, "s", 0, log_location=log_location)

    assert not Path(sample_dir).exists()
    await delete_sample_checkpoints_dir(  # idempotent
        eval_dir, "s", 0, log_location=log_location
    )


async def test_scan_torn_only_checkpoint_file_is_uncommitted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A dir whose only checkpoint file is torn holds nothing committed.

    The sample runs fresh rather than resuming from an unindexed
    snapshot, and the situation is logged since it should not pass
    silently.
    """
    import importlib

    # the package re-exports a function of the same name, which shadows the
    # submodule attribute; resolve the module itself
    module = importlib.import_module(
        "inspect_ai.util._checkpoint._layout.sample_checkpoints_dir"
    )

    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "a.checkpoints"), "s", 0
    )
    (Path(sample_dir) / "ckpt-00001.json").write_text('{"checkpoint_id": 1, "torn')
    module.logger.addHandler(caplog.handler)
    try:
        assert await scan_latest_committed_checkpoint(sample_dir) is None
    finally:
        module.logger.removeHandler(caplog.handler)
    assert any("none parse" in r.getMessage() for r in caplog.records)
