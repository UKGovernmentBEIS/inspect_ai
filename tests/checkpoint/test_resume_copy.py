"""Tests for the greedy resume payload copy (``_resume_copy``).

Local-fs coverage of ``copy_resume_payloads`` (the retry-startup pass)
and ``copy_sample_payload`` (one sample's payload copy). The s3 legs of
the same helpers are covered in ``test_fs_copy_s3.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import inspect_ai.util._checkpoint._resume_copy as resume_copy
from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    RESUME_SOURCE_FILE,
    resolve_resumable_sample_dir_in_chain,
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


async def _none_reusable() -> set[tuple[int | str, int]]:
    """reusable_ids stand-in: nothing satisfied by the prior log."""
    return set()


async def test_copy_sample_payload_copies_full_payload(
    tmp_path: Path,
) -> None:
    source = tmp_path / "old.checkpoints" / "s1__1"
    _build_payload(source, checkpoint_ids=[1, 2])
    dest = tmp_path / "new.checkpoints" / "s1__1"

    await copy_sample_payload(str(source), str(dest))

    _assert_payload_copied(dest, checkpoint_ids=[1, 2])


async def test_copy_payload_files_commit_point_order(tmp_path: Path) -> None:
    """Checkpoint files copy after everything they index, newest first.

    This ordering is the sole per-sample interrupt-safety mechanism: a
    torn copy must commit nothing (no checkpoint file without its data)
    or the true latest (never a stale prefix that would shadow the
    chain).
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


async def test_copy_sample_payload_same_dir_is_noop(tmp_path: Path) -> None:
    """A same-dir copy (in-eval requeue) leaves the payload untouched."""
    source = tmp_path / "old.checkpoints" / "s1__1"
    _build_payload(source, checkpoint_ids=[1])
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}

    await copy_sample_payload(str(source), str(source))

    after = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert after == before


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
        planned=[("s1", 1), ("s2", 1), ("s3", 1)],
        reusable_ids=_none_reusable,
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
        planned=[("s1", 1)],
        reusable_ids=_none_reusable,
    )

    assert not (source_eval / RESUME_SOURCE_FILE).exists()


async def test_copy_resume_payloads_missing_source_eval_dir(tmp_path: Path) -> None:
    """A prior attempt that never checkpointed leaves no eval dir at all."""
    dest_eval = tmp_path / "new.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(tmp_path / "never-existed.checkpoints"),
        destination_eval_dir=str(dest_eval),
        planned=[("s1", 1)],
        reusable_ids=_none_reusable,
    )

    assert not (dest_eval / "s1__1").exists()


async def test_copy_resume_payloads_failed_copy_stays_reachable_via_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed sample copy warns; the chain still reaches the source.

    The torn dir commits no checkpoint, so detection falls through the
    eval-marker chain to the intact source and the sample re-copies
    lazily at sample start. Other candidates complete normally.
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
        planned=[("s1", 1), ("s2", 1)],
        reusable_ids=_none_reusable,
    )

    # the torn dir commits nothing...
    assert not (dest_eval / "s1__1" / "ckpt-00001.json").exists()
    # ...and detection resolves the intact source through the chain
    resolved = await resolve_resumable_sample_dir_in_chain(str(dest_eval), "s1", 1)
    assert resolved is not None
    assert resolved.sample_dir == str(source_eval / "s1__1")
    # the healthy candidate completed
    _assert_payload_copied(dest_eval / "s2__1", checkpoint_ids=[1])


async def test_copy_resume_payloads_follows_eval_marker_chain(tmp_path: Path) -> None:
    """Candidates absent from the immediate source chain through eval markers.

    The prior attempt never copied this candidate (interrupted, or it
    skipped it): its eval dir's permanent marker points one attempt
    further back, where the payload lives.
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
        planned=[("s1", 1)],
        reusable_ids=_none_reusable,
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1, 2])


async def test_copy_resume_payloads_unresolvable_dir_falls_through_chain(
    tmp_path: Path,
) -> None:
    """A dir that resolves to nothing doesn't shadow a deeper intact payload.

    The nearest attempt's sample dir exists but holds no committed
    checkpoint (created, then interrupted before any checkpoint file
    landed) — the candidate must fall through to the next listing in
    the eval-marker chain.
    """
    attempt1 = tmp_path / "attempt1.checkpoints"
    _build_payload(attempt1 / "s1__1", checkpoint_ids=[1])
    attempt2 = tmp_path / "attempt2.checkpoints"
    (attempt2 / "s1__1").mkdir(parents=True)  # empty: nothing committed
    await write_resume_source_marker(str(attempt2), str(attempt1))
    dest_eval = tmp_path / "attempt3.checkpoints"

    await copy_resume_payloads(
        source_eval_dir=str(attempt2),
        destination_eval_dir=str(dest_eval),
        planned=[("s1", 1)],
        reusable_ids=_none_reusable,
    )

    _assert_payload_copied(dest_eval / "s1__1", checkpoint_ids=[1])
