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
    """Materialize a complete sample payload.

    Host repo, a restic sandbox repo, an archive-strategy sandbox
    storage area, the restic config, the strategy pin, and the
    checkpoint files.
    """
    (sample_dir / "restic" / "host" / "data" / "ab").mkdir(parents=True)
    (sample_dir / "restic" / "host" / "config").write_text("host-config")
    (sample_dir / "restic" / "host" / "data" / "ab" / "cd").write_text("pack")
    (sample_dir / "restic" / "sandboxes" / "default").mkdir(parents=True)
    (sample_dir / "restic" / "sandboxes" / "default" / "config").write_text("sb-config")
    (sample_dir / "sandboxes" / "bulk" / "archive").mkdir(parents=True)
    (sample_dir / "sandboxes" / "bulk" / "archive" / "ckpt-00001.tar.gz").write_text(
        "tarball"
    )
    (sample_dir / "restic" / "restic-config.json").write_text(
        '{"restic_password":"pw"}'
    )
    (sample_dir / "restic" / "snapshot-strategies.json").write_text(
        '{"strategies":{"default":"restic-incremental","bulk":"archive"}}'
    )
    # the live host-context working dir: not payload (its committed
    # contents are in the host repo)
    (sample_dir / "context").mkdir()
    (sample_dir / "context" / "events.json").write_text("[]")
    for n in checkpoint_ids:
        (sample_dir / f"ckpt-{n:05d}.json").write_text(_checkpoint_json(n))


def _assert_payload_copied(dest: Path, *, checkpoint_ids: list[int]) -> None:
    assert (dest / "restic" / "host" / "config").read_text() == "host-config"
    assert (dest / "restic" / "host" / "data" / "ab" / "cd").read_text() == "pack"
    assert (
        dest / "restic" / "sandboxes" / "default" / "config"
    ).read_text() == "sb-config"
    assert (
        dest / "sandboxes" / "bulk" / "archive" / "ckpt-00001.tar.gz"
    ).read_text() == "tarball"
    assert (
        dest / "restic" / "restic-config.json"
    ).read_text() == '{"restic_password":"pw"}'
    assert (
        dest / "restic" / "snapshot-strategies.json"
    ).read_text() == '{"strategies":{"default":"restic-incremental","bulk":"archive"}}'
    for n in checkpoint_ids:
        assert (dest / f"ckpt-{n:05d}.json").read_text() == _checkpoint_json(n)
    assert not (dest / "context").exists()


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

    async def failing_copy(
        source_dir: str, destination_dir: str, rels: list[str]
    ) -> list[str]:
        raise OSError("simulated transient failure")

    monkeypatch.setattr(resume_copy, "_copy_payload_data", failing_copy)

    with pytest.raises(OSError):
        await copy_resume_payloads(
            source_eval_dir=str(source_eval),
            destination_eval_dir=str(dest_eval),
        )


async def test_copy_resume_payloads_copies_incomplete_sample_dirs_verbatim(
    tmp_path: Path,
) -> None:
    """A sample dir is copied as whatever it holds; nothing is required.

    The copy has no opinion about a sample dir's shape: a dir whose
    provisioning died before `restic init` finished, or a storage area
    that is an empty directory, copies as-is (an empty dir contributes
    no files). Neither holds a committed checkpoint, so resume detection
    runs such a sample fresh — and neither can poison the source
    attempt.
    """
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])
    (source_eval / "s1__1" / "restic" / "sandboxes" / "torn").mkdir()
    (source_eval / "s2__1" / "restic").mkdir(parents=True)  # no restic/host
    (source_eval / "s2__1" / "restic" / "restic-config.json").write_text("{}")
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(dest_eval),
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1])
    assert not (dest_eval / "s1__1" / "restic" / "sandboxes" / "torn").exists()
    assert (dest_eval / "s2__1" / "restic" / "restic-config.json").read_text() == "{}"
    assert not list((dest_eval / "s2__1").glob("ckpt-*.json"))
