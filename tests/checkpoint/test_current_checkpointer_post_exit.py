"""Regression tests for the post-exit `current_checkpointer()` window.

`current_checkpointer()` -> `_CheckpointerSetup.current()` must only hand out the
session while the owning agent's `async with checkpointer()` scope is open. The
cached `_EnteredCheckpointer` lives on (`self._cached`) until `close()` at sample
teardown, but the per-checkpoint span machinery (`span_session()` ->
`SpanRotationScope`) is closed as soon as that `async with` block exits.

A fire in that post-exit window runs with the span scope closed: in
`_EnteredCheckpointer._fire_once` the `end_span()` at the top is a no-op and the
reopen at the bottom is gated on `is_open` (now False), so a `ckpt-NNNNN.json` +
`CheckpointEvent` get committed with NO enclosing `checkpoint N` span — which
`hydrate._validate_resume_state` later rejects, making the sample unrecoverable.

The fix: `current()` returns `None` once the scope has exited (gated on an
`_entered` flag), so a sub-component cannot reach the session via
`current_checkpointer()` post-exit and fire a span-less checkpoint through it.

These tests do NOT modify any source. They drive the real production objects
(`_CheckpointerSetup` built by `create_checkpointer` with `INSPECT_CHECKPOINTING=1`,
the real `checkpointer()` / `current_checkpointer()` facades) with restic + the
on-disk dirs stubbed exactly as the existing `active_sample`-based e2e tests do.

Note on transcript wiring: the `checkpoint N` span events are emitted by
`SpanRotationScope`, which writes to the *ambient* `transcript()`; only the heavy
`checkpointer_impl` fire body uses the module-level `transcript`. So these tests
use the ambient transcript for both and read the event structure off
`transcript().history.resident_events`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.event._event import Event
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.log import Transcript
from inspect_ai.log._transcript import init_transcript, transcript
from inspect_ai.util import checkpointer, current_checkpointer
from inspect_ai.util._checkpoint import Manual
from inspect_ai.util._checkpoint.checkpointer_factory import create_checkpointer
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer
from inspect_ai.util._checkpoint.config import ResolvedCheckpointConfig
from inspect_ai.util._restic import ResticBackupSummary
from inspect_ai.util._span import current_span_id
from inspect_ai.util._store import Store

# ---------------------------------------------------------------------------
# Test doubles / patches — mirror the proven setup in test_checkpointer.py so
# we exercise the real fire path with restic + on-disk dirs stubbed.
# ---------------------------------------------------------------------------


def _fake_summary(checkpoint_id: int) -> ResticBackupSummary:
    return ResticBackupSummary(
        message_type="summary",
        files_new=0,
        files_changed=0,
        files_unmodified=0,
        dirs_new=0,
        dirs_changed=0,
        dirs_unmodified=0,
        data_blobs=0,
        tree_blobs=0,
        data_added=0,
        data_added_packed=0,
        total_files_processed=0,
        total_bytes_processed=0,
        backup_start="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        backup_end="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        total_duration=0.0,
        snapshot_id=f"fake-snap-{checkpoint_id:05d}",
    )


@dataclass
class _FakeSample:
    id: int | str | None = "s"


@dataclass
class _FakeActiveSample:
    sample: _FakeSample = field(default_factory=_FakeSample)
    epoch: int = 0
    log_location: str = ""
    eval_id: str | None = "test-eval-001"
    checkpoint: ResolvedCheckpointConfig | None = None
    checkpointer: object = field(default_factory=_NoopCheckpointer)
    task: str = "test_task"


@contextmanager
def _patch_cache_dir(tmp_path: Path) -> Iterator[None]:
    def fake_cache_dir(subdir: str | None) -> Path:
        d = tmp_path / "cache" / (subdir or "")
        d.mkdir(parents=True, exist_ok=True)
        return d

    with patch(
        "inspect_ai.util._checkpoint._layout.staging_dir.inspect_cache_dir",
        side_effect=fake_cache_dir,
    ):
        yield


@contextmanager
def _patch_restic(tmp_path: Path) -> Iterator[None]:
    """Stub out everything that would actually run restic."""
    fake_binary = tmp_path / "fake_restic"
    fake_binary.write_bytes(b"#!/bin/sh\nexit 0\n")

    async def fake_resolve(platform: object = None) -> Path:
        return fake_binary

    async def fake_init_repo(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_run_backup(*_args: object, **_kwargs: object) -> ResticBackupSummary:
        return _fake_summary(checkpoint_id=1)

    with (
        patch(
            "inspect_ai.util._checkpoint.hydrate.resolve_restic",
            side_effect=fake_resolve,
        ),
        patch(
            "inspect_ai.util._checkpoint.hydrate.init_repo",
            side_effect=fake_init_repo,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.run_backup",
            side_effect=fake_run_backup,
        ),
    ):
        yield


@contextmanager
def _patch_sample_active(value: object) -> Iterator[None]:
    with patch("inspect_ai.log._samples.sample_active", return_value=value):
        yield


@dataclass
class _Harness:
    active: _FakeActiveSample
    sample_dir: Path

    def events(self) -> list[Event]:
        """Full event structure from the ambient transcript.

        The `checkpoint N` span events live here (SpanRotationScope writes to
        the ambient transcript), alongside the CheckpointEvents.
        """
        return list(transcript().history.resident_events)


@contextmanager
def _harness(tmp_path: Path) -> Iterator[_Harness]:
    """Build a real `_CheckpointerSetup` bound to a fake active sample.

    Same wiring as `test_checkpointer.py::active_sample`, except the transcript
    and sample-store are the *ambient* ones (so span + checkpoint events all
    land in one observable place). The real `checkpointer()` /
    `current_checkpointer()` facades resolve to a real `_CheckpointerSetup`
    whose fires write real checkpoint files to disk.
    """
    init_transcript(Transcript(bounded=False))
    active = _FakeActiveSample(log_location=str(tmp_path / "logs" / "test.eval"))
    (tmp_path / "logs").mkdir()
    active.checkpoint = ResolvedCheckpointConfig(trigger=Manual())
    fake_state = SimpleNamespace(store=Store())
    with (
        _patch_sample_active(active),
        _patch_cache_dir(tmp_path),
        _patch_restic(tmp_path),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.sample_state",
            return_value=fake_state,
        ),
        patch.dict(os.environ, {"INSPECT_CHECKPOINTING": "1"}),
    ):
        assert active.sample.id is not None
        active.checkpointer = create_checkpointer(
            config=active.checkpoint,
            log_location=active.log_location,
            sample_id=active.sample.id,
            epoch=active.epoch,
        )
        sample_dir = tmp_path / "logs" / "test.checkpoints" / "s__0"
        try:
            yield _Harness(active, sample_dir)
        finally:
            # Sample teardown (what closes the cached checkpointer in prod).
            active.checkpointer.close()


def _checkpoint_span_names(events: list[Event]) -> list[str]:
    return [
        e.name
        for e in events
        if isinstance(e, SpanBeginEvent) and e.type == "checkpoint"
    ]


def _checkpoint_event_ids(events: list[Event]) -> list[int]:
    return [e.checkpoint_id for e in events if isinstance(e, CheckpointEvent)]


def _ckpt_files(sample_dir: Path) -> list[str]:
    return sorted(p.name for p in sample_dir.glob("ckpt-*.json"))


# ---------------------------------------------------------------------------
# Control: a fire INSIDE the agent's `async with checkpointer()` is wrapped in
# a `checkpoint N` span (the correct, recoverable shape). This proves the
# harness faithfully reproduces the normal span/checkpoint pairing — and that
# the `_fire` scope guard does not interfere with legitimate in-session fires.
# ---------------------------------------------------------------------------


async def test_in_session_fire_is_span_wrapped(tmp_path: Path) -> None:
    with _harness(tmp_path) as h:
        async with checkpointer() as cp:
            # `current_checkpointer()` returns the same live session.
            assert current_checkpointer() is cp
            assert current_span_id() is not None  # `checkpoint 1` span is open
            await cp.checkpoint()  # ckpt-1, fired while the span is open

    files = _ckpt_files(h.sample_dir)
    events = h.events()
    # Two checkpoints: the manual ckpt-1 and the clean-exit `agent_complete`
    # finalize ckpt-2.
    assert files == ["ckpt-00001.json", "ckpt-00002.json"]
    assert _checkpoint_event_ids(events) == [1, 2]
    # Each committed checkpoint has its matching `checkpoint N` span — the
    # recoverable shape the validator requires.
    assert _checkpoint_span_names(events) == ["checkpoint 1", "checkpoint 2"]
    assert len(_checkpoint_span_names(events)) == len(files)


# ---------------------------------------------------------------------------
# Fix (b): once the agent's `async with checkpointer()` exits, the session is no
# longer reachable via current_checkpointer() — so a sub-component cannot fire
# through it post-exit and produce a span-less checkpoint.
# ---------------------------------------------------------------------------


async def test_current_checkpointer_is_none_after_session_exit(
    tmp_path: Path,
) -> None:
    with _harness(tmp_path) as h:
        async with checkpointer() as cp:
            assert current_checkpointer() is cp  # reachable while open

        # Post-exit window: no span is active, and the session is no longer
        # handed out — at both the facade and the setup level.
        assert current_span_id() is None
        assert current_checkpointer() is None
        assert h.active.checkpointer.current() is None  # type: ignore[attr-defined]

    # Only the clean-exit finalize was committed; spans and files stay matched
    # (no span-less checkpoint was produced).
    assert len(_checkpoint_span_names(h.events())) == len(_ckpt_files(h.sample_dir))
