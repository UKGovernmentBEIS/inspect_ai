"""Tests for the retry startup copy (``_resume_copy``).

Local-fs coverage of ``copy_resume_payloads``: whole-attempt
replication and failure semantics. Interrupt safety lives one level
up — the copy runs before the destination log's first write, so a
failed copy means no log and the next retry falls back — which is why
these tests only assert copy behavior. The s3 legs of the underlying
copy helpers are covered in ``test_fs_copy_s3.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import inspect_ai.util._checkpoint._resume_copy as resume_copy
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

    Completed samples' dirs are copied too: checkpoints are a permanent
    record (future work branches from arbitrary checkpoints), so each
    attempt with a log is a complete, self-contained archive.
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


async def test_copy_resume_payloads_same_eval_dir_is_noop(tmp_path: Path) -> None:
    """A same-dir retry (reused log location) leaves the payload untouched."""
    source_eval = tmp_path / "same.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])
    before = {p: p.read_bytes() for p in source_eval.rglob("*") if p.is_file()}

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(source_eval),
    )

    after = {p: p.read_bytes() for p in source_eval.rglob("*") if p.is_file()}
    assert after == before


async def test_copy_resume_payloads_missing_source_eval_dir(tmp_path: Path) -> None:
    """A prior attempt that never checkpointed leaves no eval dir at all."""
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(tmp_path / "never-existed.checkpoints"),
        destination_eval_dir=str(dest_eval),
    )

    # nothing to copy
    assert not any(dest_eval.iterdir())


async def test_copy_resume_payloads_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any copy failure propagates.

    The caller runs before the destination log's first write, so the
    raise means the attempt dies without a log and the next retry falls
    back to the newest log that exists.
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


async def test_copy_resume_payloads_tolerates_empty_sandbox_repo_dir(
    tmp_path: Path,
) -> None:
    """An empty sandbox repo dir in a logged attempt must not poison retries.

    A fire interrupted between the sandbox egress's mkdir and its
    extract leaves an empty ``restic/sandboxes/<name>/`` on local
    filesystems. No committed checkpoint can reference it (checkpoint
    files write only after the egress completes), so the copy skips it
    instead of failing every future retry of the attempt.
    """
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])
    (source_eval / "s1__1" / "restic" / "sandboxes" / "torn").mkdir()
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(dest_eval),
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1])
    assert not (dest_eval / "s1__1" / "restic" / "sandboxes" / "torn").exists()


async def test_copy_payload_files_commit_point_order(tmp_path: Path) -> None:
    """Checkpoint files copy after everything they index, newest first.

    Interrupt recovery no longer depends on this (the destination
    log's deferred first write gates the whole pass), but the order
    keeps every intermediate state honest — no checkpoint file ever
    precedes its data — matching the fire path and ``host_egress``.
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
