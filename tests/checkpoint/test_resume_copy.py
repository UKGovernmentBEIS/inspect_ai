"""Tests for the greedy resume payload copy (``_resume_copy``).

Local-fs coverage of ``copy_resume_payloads`` (the retry-startup pass)
and ``copy_sample_payload`` (one sample's committed-equivalent copy and
its marker lifecycle). The s3 legs of the same helpers are covered in
``test_fs_copy_s3.py``.
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
from inspect_ai.util._checkpoint._resume_copy import (
    copy_resume_payloads,
    copy_sample_payload,
)


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
    assert not (dest / RESUME_SOURCE_FILE).exists()


async def test_copy_sample_payload_committed_equivalent_and_marker_deleted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "old.checkpoints" / "s1__1"
    _build_payload(source, checkpoint_ids=[1, 2])
    dest = tmp_path / "new.checkpoints" / "s1__1"

    await copy_sample_payload(str(source), str(dest))

    _assert_payload_copied(dest, checkpoint_ids=[1, 2])


async def test_copy_sample_payload_same_dir_is_noop(tmp_path: Path) -> None:
    source = tmp_path / "old.checkpoints" / "s1__1"
    _build_payload(source, checkpoint_ids=[1])

    await copy_sample_payload(str(source), str(source))

    # no self-pointing marker was written
    assert not (source / RESUME_SOURCE_FILE).exists()


async def test_copy_resume_payloads_copies_incomplete_candidates(
    tmp_path: Path,
) -> None:
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1, 2])
    _build_payload(source_eval / "s2__1", checkpoint_ids=[1])
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(dest_eval),
        # s3 never checkpointed (no source dir) — skipped without error
        candidates=[("s1", 1), ("s2", 1), ("s3", 1)],
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1, 2])
    _assert_payload_copied(dest_eval / "s2__1", checkpoint_ids=[1])
    assert not (dest_eval / "s3__1").exists()
    # the eval-level marker is permanent provenance: later retries walk it
    # for candidates this pass had no per-sample trail for
    eval_marker = json.loads((dest_eval / RESUME_SOURCE_FILE).read_text())
    assert eval_marker["source_dir"] == str(source_eval)


async def test_copy_resume_payloads_same_eval_dir_is_noop(tmp_path: Path) -> None:
    source_eval = tmp_path / "same.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(source_eval),
        candidates=[("s1", 1)],
    )

    assert not (source_eval / RESUME_SOURCE_FILE).exists()


async def test_copy_resume_payloads_missing_source_eval_dir(tmp_path: Path) -> None:
    """A prior attempt that never checkpointed leaves no eval dir at all."""
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(tmp_path / "never-existed.checkpoints"),
        destination_eval_dir=str(dest_eval),
        candidates=[("s1", 1)],
    )

    assert not (dest_eval / "s1__1").exists()


async def test_copy_resume_payloads_all_markers_precede_any_payload_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marker phase completes before the first payload byte moves.

    An interrupt landing anywhere inside the payload copies must find a
    marker in *every* candidate's destination dir — that is the whole
    interrupt-safety design (see the module docstring).
    """
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])
    _build_payload(source_eval / "s2__1", checkpoint_ids=[1])
    dest_eval = tmp_path / "new.checkpoints"

    original = resume_copy._fs_copy_repo
    markers_seen_at_first_copy: list[bool] = []

    async def checking_copy_repo(
        old_sample_dir: str, subpath: str, new_repo: str, *, label: str
    ) -> list[str]:
        if not markers_seen_at_first_copy:
            markers_seen_at_first_copy.extend(
                (dest_eval / name / RESUME_SOURCE_FILE).is_file()
                for name in ("s1__1", "s2__1")
            )
        return await original(old_sample_dir, subpath, new_repo, label=label)

    monkeypatch.setattr(resume_copy, "_fs_copy_repo", checking_copy_repo)

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(dest_eval),
        candidates=[("s1", 1), ("s2", 1)],
    )

    assert markers_seen_at_first_copy == [True, True]
    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1])
    _assert_payload_copied(dest_eval / "s2__1", checkpoint_ids=[1])


async def test_copy_resume_payloads_failed_copy_leaves_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed sample copy warns and leaves the torn dir + marker.

    The marker keeps the trail intact: the sample's resume retries the
    copy lazily at sample start. Other candidates complete normally.
    """
    source_eval = tmp_path / "old.checkpoints"
    _build_payload(source_eval / "s1__1", checkpoint_ids=[1])
    _build_payload(source_eval / "s2__1", checkpoint_ids=[1])
    dest_eval = tmp_path / "new.checkpoints"

    original = resume_copy._fs_copy_repo

    async def failing_copy_repo(
        old_sample_dir: str, subpath: str, new_repo: str, *, label: str
    ) -> list[str]:
        if "s1__1" in old_sample_dir:
            raise RuntimeError("simulated copy failure")
        return await original(old_sample_dir, subpath, new_repo, label=label)

    monkeypatch.setattr(resume_copy, "_fs_copy_repo", failing_copy_repo)

    await copy_resume_payloads(
        source_eval_dir=str(source_eval),
        destination_eval_dir=str(dest_eval),
        candidates=[("s1", 1), ("s2", 1)],
    )

    # torn dir: marker intact, no committed checkpoint copied
    torn = dest_eval / "s1__1"
    marker = json.loads((torn / RESUME_SOURCE_FILE).read_text())
    assert marker["source_dir"] == str(source_eval / "s1__1")
    assert not (torn / "ckpt-00001.json").exists()
    # the healthy candidate completed
    _assert_payload_copied(dest_eval / "s2__1", checkpoint_ids=[1])


async def test_copy_resume_payloads_follows_eval_marker_chain(tmp_path: Path) -> None:
    """Candidates absent from the immediate source chain through eval markers.

    The prior attempt's greedy pass was interrupted before this
    candidate got its per-sample marker: its eval dir still carries the
    eval-level marker pointing one attempt further back, where the
    payload lives.
    """
    attempt1 = tmp_path / "attempt1.checkpoints"
    _build_payload(attempt1 / "s1__1", checkpoint_ids=[1, 2])
    attempt2 = tmp_path / "attempt2.checkpoints"
    attempt2.mkdir()
    await write_resume_source_marker(str(attempt2), str(attempt1))
    dest_eval = tmp_path / "attempt3.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(attempt2),
        destination_eval_dir=str(dest_eval),
        candidates=[("s1", 1)],
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1, 2])


async def test_copy_resume_payloads_unresolvable_dir_falls_through_chain(
    tmp_path: Path,
) -> None:
    """A dir that resolves to nothing doesn't shadow a deeper intact payload.

    The nearest attempt's sample dir exists but holds nothing (created,
    then interrupted before even its marker landed) — the candidate must
    fall through to the next listing in the eval-marker chain.
    """
    attempt1 = tmp_path / "attempt1.checkpoints"
    _build_payload(attempt1 / "s1__1", checkpoint_ids=[1])
    attempt2 = tmp_path / "attempt2.checkpoints"
    (attempt2 / "s1__1").mkdir(parents=True)  # empty: no marker, no payload
    await write_resume_source_marker(str(attempt2), str(attempt1))
    dest_eval = tmp_path / "attempt3.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(attempt2),
        destination_eval_dir=str(dest_eval),
        candidates=[("s1", 1)],
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1])


async def test_copy_resume_payloads_resolves_torn_source_via_sample_marker(
    tmp_path: Path,
) -> None:
    """A torn source dir (interrupted copy) resolves through its marker.

    The immediate source holds only a resume-source marker — its own
    copy was interrupted before any checkpoint file landed — so the
    payload is pulled from the dir the marker points at.
    """
    attempt1 = tmp_path / "attempt1.checkpoints"
    _build_payload(attempt1 / "s1__1", checkpoint_ids=[1])
    attempt2 = tmp_path / "attempt2.checkpoints"
    torn = attempt2 / "s1__1"
    torn.mkdir(parents=True)
    await write_resume_source_marker(str(torn), str(attempt1 / "s1__1"))
    dest_eval = tmp_path / "attempt3.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(attempt2),
        destination_eval_dir=str(dest_eval),
        candidates=[("s1", 1)],
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1])
