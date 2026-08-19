"""Tests for the retry startup copy (``_resume_copy``).

Local-fs coverage of ``copy_resume_payloads``: whole-attempt
replication, the dirty-flag marker lifecycle, the skip-dirty walk, and
failure semantics. The s3 legs of the underlying copy helpers are
covered in ``test_fs_copy_s3.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import inspect_ai.util._checkpoint._resume_copy as resume_copy
from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    RESUME_SOURCE_FILE,
    write_resume_source_marker,
)
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
from inspect_ai.util._checkpoint._resume_copy import copy_resume_payloads


def _checkpoint_json(checkpoint_id: int) -> str:
    return Checkpoint(
        checkpoint_id=checkpoint_id,
        trigger="turn",
        turn=checkpoint_id,
        created_at=datetime(2026, 5, 17, 18, 0, tzinfo=timezone.utc),
        duration_ms=10,
        size_bytes=100 + checkpoint_id,
        host=SnapshotDetails(
            snapshot_id=f"snap-{checkpoint_id}",
            size_bytes=100 + checkpoint_id,
            duration_ms=10,
        ),
        sandboxes={},
    ).model_dump_json()


def _build_payload(sample_dir: Path, *, checkpoint_ids: list[int]) -> None:
    """Materialize a complete sample payload: repos, config, checkpoint files."""
    (sample_dir / "restic" / "host" / "data" / "ab").mkdir(parents=True)
    (sample_dir / "restic" / "host" / "config").write_text("host-config")
    (sample_dir / "restic" / "host" / "data" / "ab" / "cd").write_text("pack")
    (sample_dir / "restic" / "sandboxes" / "default").mkdir(parents=True)
    (sample_dir / "restic" / "sandboxes" / "default" / "config").write_text("sb-config")
    (sample_dir / "restic" / "restic-config.json").write_text(
        '{"restic_password":"pw"}'
    )
    for n in checkpoint_ids:
        (sample_dir / f"ckpt-{n:05d}.json").write_text(_checkpoint_json(n))


def _assert_payload_copied(dest: Path, *, checkpoint_ids: list[int]) -> None:
    assert (dest / "restic" / "host" / "config").read_text() == "host-config"
    assert (dest / "restic" / "host" / "data" / "ab" / "cd").read_text() == "pack"
    assert (
        dest / "restic" / "sandboxes" / "default" / "config"
    ).read_text() == "sb-config"
    assert (
        dest / "restic" / "restic-config.json"
    ).read_text() == '{"restic_password":"pw"}'
    for n in checkpoint_ids:
        assert (dest / f"ckpt-{n:05d}.json").read_text() == _checkpoint_json(n)


async def test_copy_resume_payloads_replicates_every_sample_dir(
    tmp_path: Path,
) -> None:
    """Every sample dir the source has is copied — a complete archive.

    Completed samples' dirs are copied too (checkpoints are a permanent
    record; future work branches from arbitrary checkpoints), and the
    dirty marker is deleted once every copy lands.
    """
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1, 2])
    _build_payload(source_eval / "s2__1", checkpoint_ids=[1])
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(dest_eval),
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1, 2])
    _assert_payload_copied(dest_eval / "s2__1", checkpoint_ids=[1])
    # the marker's deletion is the pass's commit point: this attempt is clean
    assert not (dest_eval / RESUME_SOURCE_FILE).exists()


async def test_copy_resume_payloads_same_eval_dir_is_noop(tmp_path: Path) -> None:
    source_eval = tmp_path / "same.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(source_eval),
    )

    assert not (source_eval / RESUME_SOURCE_FILE).exists()


async def test_copy_resume_payloads_missing_source_eval_dir(tmp_path: Path) -> None:
    """A prior attempt that never checkpointed leaves no eval dir at all."""
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(tmp_path / "never-existed.checkpoints"),
        destination_eval_dir=str(dest_eval),
    )

    # nothing to copy; the attempt still completes clean
    assert not (dest_eval / RESUME_SOURCE_FILE).exists()
    assert not any(p.is_dir() for p in dest_eval.iterdir())


async def test_copy_resume_payloads_skips_dirty_attempts(tmp_path: Path) -> None:
    """The walk follows dirty markers past dead attempts to the clean one.

    Attempts 2 and 3 both died during their startup copies (markers
    still present, nothing of their own); attempt 4 copies from
    attempt 1 — the newest clean attempt.
    """
    attempt1 = tmp_path / "attempt1.checkpoints"
    _build_payload(attempt1 / "s1__1", checkpoint_ids=[1, 2])
    attempt2 = tmp_path / "attempt2.checkpoints"
    attempt2.mkdir()
    await write_resume_source_marker(str(attempt2), str(attempt1))
    attempt3 = tmp_path / "attempt3.checkpoints"
    attempt3.mkdir()
    await write_resume_source_marker(str(attempt3), str(attempt2))
    dest_eval = tmp_path / "attempt4.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(attempt3),
        destination_eval_dir=str(dest_eval),
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1, 2])
    assert not (dest_eval / RESUME_SOURCE_FILE).exists()


async def test_copy_resume_payloads_failure_leaves_marker_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any copy failure fails the retry; the dirty marker stays.

    The next retry then skips this attempt via the marker — the skip is
    the recovery.
    """
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])
    dest_eval = tmp_path / "new.checkpoints"

    async def failing_copy_repo(
        old_sample_dir: str, subpath: str, new_repo: str, *, label: str
    ) -> list[str]:
        raise OSError("simulated transient failure")

    monkeypatch.setattr(resume_copy, "_fs_copy_repo", failing_copy_repo)

    with pytest.raises(OSError):
        await copy_resume_payloads(
            source_eval_dir=str(source_eval),
            destination_eval_dir=str(dest_eval),
        )

    marker = json.loads((dest_eval / RESUME_SOURCE_FILE).read_text())
    assert marker["source_dir"] == str(source_eval)


async def test_copy_resume_payloads_skips_sample_dir_without_host_repo(
    tmp_path: Path,
) -> None:
    """A structurally incomplete sample dir is skipped, not fatal.

    A dir whose provisioning died before `restic init` finished holds
    nothing committed; it must not poison the source attempt forever.
    """
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])
    (source_eval / "s2__1" / "context").mkdir(parents=True)  # no restic/host
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(dest_eval),
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1])
    assert not (dest_eval / RESUME_SOURCE_FILE).exists()


async def test_copy_payload_files_commit_point_order(tmp_path: Path) -> None:
    """Checkpoint files copy after everything they index, newest first.

    Interrupt recovery no longer depends on this (the dirty marker
    covers the whole pass), but the order keeps every intermediate
    state honest — no checkpoint file ever precedes its data — matching
    the fire path and ``host_egress``.
    """
    source = tmp_path / "old.checkpoints" / "s1__1"
    _build_payload(source, checkpoint_ids=[1, 2, 3])
    dest = tmp_path / "new.checkpoints" / "s1__1"

    written = await resume_copy.copy_payload_files(str(source), str(dest))

    checkpoint_positions = [
        i for i, name in enumerate(written) if name.startswith("ckpt-")
    ]
    other_positions = [
        i for i, name in enumerate(written) if not name.startswith("ckpt-")
    ]
    assert checkpoint_positions, "no checkpoint files copied"
    assert min(checkpoint_positions) > max(other_positions), (
        "a checkpoint file copied before the data it indexes"
    )
    assert [written[i] for i in checkpoint_positions] == [
        "ckpt-00003.json",
        "ckpt-00002.json",
        "ckpt-00001.json",
    ], "checkpoint files must copy newest first"


def test_same_dir_matches_relative_and_absolute_spellings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The own-dir assert must not fire on two spellings of one dir.

    The log location reaches detection absolute but can reach hydrate
    relativized to the eval working dir (the default ./logs case).
    """
    from inspect_ai.util._checkpoint.hydrate import _same_dir

    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    relative = "logs/x.checkpoints/s__1"
    absolute = str(tmp_path / "logs" / "x.checkpoints" / "s__1")

    assert _same_dir(relative, absolute)
    assert _same_dir(absolute, absolute)
    assert not _same_dir(relative, str(tmp_path / "logs" / "y.checkpoints" / "s__1"))
    assert _same_dir("s3://b/x.checkpoints/s__1", "s3://b/x.checkpoints/s__1")
    assert not _same_dir("s3://b/x.checkpoints/s__1", absolute)
