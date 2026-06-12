"""Policy + outer-facade tests for the checkpointer.

The policy tests drive ``_CheckpointerSetup`` directly with prepared dirs
and call its methods without going through the public facade.
Outer-facade tests cover dispatch, sample-identity validation, and
ContextVar wiring (the public ``checkpointer`` is what registers the
active session).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest
from test_helpers.transcript import FakeTranscriptHistoryProvider, make_model_event

from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.log import Transcript, expand_events
from inspect_ai.log._transcript import init_transcript
from inspect_ai.log._transcript_store import TranscriptEventStore
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.util._checkpoint import (
    Manual,
    TimeInterval,
    TokenInterval,
    TurnInterval,
    checkpointer,
)
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
from inspect_ai.util._checkpoint._triggers import CheckpointTriggerKind
from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint
from inspect_ai.util._checkpoint.checkpointer_impl import (
    CheckpointFailureLimitExceeded,
    _CheckpointerSetup,
    _EnteredCheckpointer,
)
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer
from inspect_ai.util._checkpoint.config import ResolvedCheckpointConfig
from inspect_ai.util._checkpoint.hydrate import HydrationResult, _HostHydrationResult
from inspect_ai.util._restic import ResticBackupSummary
from inspect_ai.util._store import Store


def _write_transcript_files(store: TranscriptEventStore, work_dir: Path) -> None:
    store.write_transcript_files(
        events_path=work_dir / "events.json",
        events_data_path=work_dir / "events_data.json",
        attachments_path=work_dir / "attachments.json",
    )


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


# === Policy tests against `_ActiveCheckpointer` directly ====================


@dataclass
class _Dirs:
    checkpoints: str
    """Sample checkpoints dir (destination)."""

    context: str
    """Context subdir inside the sample root — restic backup source."""

    events: list[object] = field(default_factory=list)
    """Live-collected transcript events from the fake transcript patched
    into `_patch_sample_runtime`. Tests that drive fires can inspect this
    to assert emit behavior (e.g. `CheckpointEvent`)."""


@contextmanager
def _patch_sample_runtime(events: list[object]) -> Iterator[None]:
    """Patch sample_state() and transcript() for tests that drive _fire."""
    from types import SimpleNamespace

    from inspect_ai.util._store import Store

    fake_state = SimpleNamespace(store=Store())
    fake_transcript = Transcript(bounded=False)
    fake_transcript._subscribe(events.append)
    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.sample_state",
            return_value=fake_state,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
            return_value=fake_transcript,
        ),
    ):
        yield


@pytest.fixture
def dirs(tmp_path: Path) -> Iterator[_Dirs]:
    """Pre-create the per-sample dirs without going through the facade.

    For local-destination tests the sample root equals the sample
    checkpoints dir, so `context` lives under it as a peer of the
    `restic/` subdir.
    """
    checkpoints = tmp_path / "logs/test.checkpoints/s__0"
    context = checkpoints / "context"
    checkpoints.mkdir(parents=True)
    context.mkdir(parents=True)
    d = _Dirs(checkpoints=str(checkpoints), context=str(context))
    with _patch_sample_runtime(d.events):
        yield d


@pytest.fixture(autouse=True)
def _isolate_transcript() -> Iterator[None]:
    init_transcript(Transcript())
    yield
    init_transcript(Transcript())


class _CountingCheckpointer(_EnteredCheckpointer):
    """Counts fires on top of the real fire path; stubs out restic."""

    fire_count: int = 0

    async def _fire(
        self, trigger: CheckpointTriggerKind, *, final: bool = False
    ) -> None:
        await super()._fire(trigger, final=final)
        self.fire_count += 1

    async def _backup_host(self, checkpoint_id: int) -> ResticBackupSummary:
        return _fake_summary(checkpoint_id)


def _fake_hydration(sample_checkpoints_dir: str, context_dir: str) -> HydrationResult:
    # Local destination: sample root equals the sample checkpoints dir;
    # no staging dir.
    return HydrationResult(
        sample_checkpoints_dir=sample_checkpoints_dir,
        sample_staging_dir=None,
        sample_root=sample_checkpoints_dir,
        context_dir=context_dir,
        host_restic=Path("/fake/restic"),
        host_repo=f"{sample_checkpoints_dir}/restic/host",
        restic_password="test-pwd",
        host=_HostHydrationResult(),
    )


@contextlib.asynccontextmanager
async def _counting(
    config: ResolvedCheckpointConfig, dirs: _Dirs
) -> AsyncIterator[_CountingCheckpointer]:
    """Yield a counting checkpointer, closing its trailing span on exit.

    These policy tests drive fires directly rather than through the
    production ``span_session()`` wrapper, so the ``checkpoint N`` span
    that each fire reopens (``_open_next_span`` in ``_fire_once``'s
    ``finally``) would otherwise never be exited. An abandoned span CM
    is finalized later by GC inside whatever test happens to be running,
    emitting a stray ``SpanEndEvent`` (plus an "Exiting span created in
    another context" warning) into that test's transcript. Closing in
    ``finally`` makes the cleanup structural rather than a per-test
    obligation (``_close_current_span`` is a no-op when no fire opened
    a span).
    """
    cp = _CountingCheckpointer(
        config=config,
        hydration=_fake_hydration(dirs.checkpoints, dirs.context),
        resume_checkpoint=None,
        reset_transcript_store=True,
    )
    try:
        yield cp
    finally:
        await cp._close_current_span()


class _FlakyError(RuntimeError):
    """Sentinel raised by `_FlakyCheckpointer` to stand in for a fire failure."""


class _FlakyCheckpointer(_EnteredCheckpointer):
    """Drives the `_fire` wrapper with scripted per-attempt outcomes.

    Bypasses the real fire body so the `max_consecutive_failures`
    enforcement (counter, record, raise) is tested in isolation. Toggle
    ``should_fail`` between fires; each fire records its outcome.
    """

    should_fail: bool = False
    attempts: int = 0

    async def _fire_once(
        self, trigger: CheckpointTriggerKind, *, final: bool = False
    ) -> None:
        self.attempts += 1
        if self.should_fail:
            raise _FlakyError("boom")


def _flaky(config: ResolvedCheckpointConfig, dirs: _Dirs) -> _FlakyCheckpointer:
    return _FlakyCheckpointer(
        config=config,
        hydration=_fake_hydration(dirs.checkpoints, dirs.context),
        resume_checkpoint=None,
        reset_transcript_store=True,
    )


# --- turn-based -----------------------------------------------------------


async def test_turn_interval_fires_at_each_threshold(dirs: _Dirs) -> None:
    # First tick is informational (boundary before turn 1) — doesn't
    # count toward the threshold. With every=3, fires happen on ticks
    # 4, 7, 10 — capturing 3 turns each. 10 ticks → 3 fires.
    async with _counting(
        ResolvedCheckpointConfig(trigger=TurnInterval(every=3)), dirs
    ) as cp:
        for _ in range(10):
            await cp.tick()
        assert cp.fire_count == 3


async def test_turn_interval_resets_counter_on_fire(dirs: _Dirs) -> None:
    async with _counting(
        ResolvedCheckpointConfig(trigger=TurnInterval(every=4)), dirs
    ) as cp:
        # 4 ticks: first is informational, then 3 turns elapsed — no fire.
        for _ in range(4):
            await cp.tick()
        assert cp.fire_count == 0
        # 5th tick → 4 turns elapsed → fire.
        await cp.tick()
        assert cp.fire_count == 1
        # counter reset; next fire requires another 4 turns (= 4 more ticks
        # since the post-fire ticks all count).
        for _ in range(3):
            await cp.tick()
        assert cp.fire_count == 1
        await cp.tick()
        assert cp.fire_count == 2


# --- time-based -----------------------------------------------------------


async def test_time_interval_fires_when_elapsed_exceeds_threshold(dirs: _Dirs) -> None:
    """tick() advances the simulated clock; fires when delta ≥ interval."""
    fake_now = [1000.0]

    def clock() -> float:
        return fake_now[0]

    with patch("inspect_ai.util._checkpoint.checkpointer_impl.time.monotonic", clock):
        async with _counting(
            ResolvedCheckpointConfig(trigger=TimeInterval(every=timedelta(seconds=10))),
            dirs,
        ) as cp:
            # First tick anchors the clock; never fires.
            await cp.tick()
            assert cp.fire_count == 0

            fake_now[0] = 1004.0
            await cp.tick()
            assert cp.fire_count == 0

            fake_now[0] = 1010.0
            await cp.tick()
            assert cp.fire_count == 1

            # immediately again at t=1010 → does not fire (counter just reset)
            await cp.tick()
            assert cp.fire_count == 1

            fake_now[0] = 1025.0
            await cp.tick()
            assert cp.fire_count == 2


# --- token-based ----------------------------------------------------------


async def test_token_interval_fires_when_usage_crosses_threshold(
    dirs: _Dirs,
) -> None:
    """tick() reads sample_total_tokens; fires when delta ≥ every."""
    fake_tokens = [0]

    def tokens() -> int:
        return fake_tokens[0]

    with patch("inspect_ai.model._model.sample_total_tokens", tokens):
        async with _counting(
            ResolvedCheckpointConfig(trigger=TokenInterval(every=1000)),
            dirs,
        ) as cp:
            # First tick anchors reference at current total; never fires.
            fake_tokens[0] = 50
            await cp.tick()
            assert cp.fire_count == 0

            # Delta = 700 < 1000 → no fire.
            fake_tokens[0] = 750
            await cp.tick()
            assert cp.fire_count == 0

            # Delta = 1050 ≥ 1000 → fire, anchor resets to 1100.
            fake_tokens[0] = 1100
            await cp.tick()
            assert cp.fire_count == 1

            # Immediately again at 1100 → no fire (just anchored).
            await cp.tick()
            assert cp.fire_count == 1

            # Delta = 1000 ≥ 1000 → fire.
            fake_tokens[0] = 2100
            await cp.tick()
            assert cp.fire_count == 2


# --- manual ---------------------------------------------------------------


async def test_manual_policy_tick_never_fires(dirs: _Dirs) -> None:
    async with _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs) as cp:
        for _ in range(50):
            await cp.tick()
        assert cp.fire_count == 0


async def test_checkpoint_method_fires(dirs: _Dirs) -> None:
    async with _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs) as cp:
        await cp.tick()
        await cp.checkpoint()
        await cp.checkpoint()
        assert cp.fire_count == 2


# --- CheckpointEvent emission ---------------------------------------------


async def test_fire_emits_checkpoint_event(dirs: _Dirs) -> None:
    """Successful fire appends a `CheckpointEvent` carrying the checkpoint."""
    from inspect_ai.event._checkpoint import CheckpointEvent

    async with _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs) as cp:
        await cp.tick()
        await cp.checkpoint()
        await cp.checkpoint()

        emitted = [e for e in dirs.events if isinstance(e, CheckpointEvent)]
        assert len(emitted) == 2

        first, second = emitted
        assert first.checkpoint_id == 1
        assert first.trigger == "manual"
        assert second.checkpoint_id == 2
        assert second.trigger == "manual"
        # Flattened checkpoint fields carry full per-repo info; with no real
        # restic the stub values from `_CountingCheckpointer._backup_host`
        # round-trip.
        assert first.host.snapshot_id.startswith("fake-snap-")


async def test_fire_includes_events_emitted_before_checkpointer_construction(
    dirs: _Dirs,
) -> None:
    preexisting = InfoEvent(data="before-checkpointer")
    # Fresh transcript, not the ambient `transcript()`: in a full-suite run
    # the shared ContextVar transcript holds leftover events from prior tests,
    # which would sort ahead of `preexisting` in the dumped events.json.
    active_transcript = Transcript(bounded=False)
    active_transcript._event(preexisting)

    with patch(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        return_value=active_transcript,
    ):
        async with _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs) as cp:
            await cp.checkpoint()

    events = json.loads((Path(dirs.context) / "events.json").read_text())
    assert events[0]["uuid"] == preexisting.uuid
    assert events[0]["data"] == "before-checkpointer"


async def test_fire_reopens_checkpoint_span_after_failure(dirs: _Dirs) -> None:
    async with _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs) as cp:
        assert cp._current_span_cm is None
        await cp._open_next_span()
        open_before = cp._current_span_cm
        assert open_before is not None

        async def fail_write_host_context(*_args: object) -> None:
            raise RuntimeError("write failed")

        with patch.object(
            cp, "_write_host_context", side_effect=fail_write_host_context
        ):
            await cp.checkpoint()

        assert cp._current_span_cm is not None
        assert cp._current_span_cm is not open_before
        await cp._close_current_span()


# --- hydrate: resume-state validation -------------------------------------


def _make_checkpoint(checkpoint_id: int) -> Checkpoint:
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
    )


def _write_checkpoint_files(sample_root: Path, count: int) -> None:
    sample_root.mkdir(parents=True, exist_ok=True)
    for checkpoint_id in range(1, count + 1):
        checkpoint = _make_checkpoint(checkpoint_id)
        (sample_root / f"ckpt-{checkpoint_id:05d}.json").write_text(
            checkpoint.model_dump_json()
        )


def _checkpoint_resume_events(count: int) -> list[Event]:
    from inspect_ai.util._checkpoint.hydrate import _wrap_prior_run

    events: list[Event] = []
    for checkpoint_id in range(1, count + 1):
        span_id = f"checkpoint-{checkpoint_id}"
        events.extend(
            [
                SpanBeginEvent(
                    id=span_id,
                    name=f"checkpoint {checkpoint_id}",
                    type="checkpoint",
                ),
                InfoEvent(uuid=f"work-{checkpoint_id}", data=f"work {checkpoint_id}"),
                SpanEndEvent(id=span_id),
                CheckpointEvent.from_details(_make_checkpoint(checkpoint_id)),
            ]
        )
    return _wrap_prior_run(events, parent_span_id="current")


def test_synthesize_trailing_checkpoint_event(tmp_path: Path) -> None:
    """Hydrate reconstructs the trailing CheckpointEvent from a checkpoint file."""
    from inspect_ai.util._checkpoint.hydrate import (
        _synthesize_trailing_checkpoint_event,
    )

    sample_dir = tmp_path / "1__0"
    sample_dir.mkdir()
    checkpoint = Checkpoint(
        checkpoint_id=7,
        trigger="turn",
        turn=42,
        created_at=datetime(2026, 5, 17, 18, 0, tzinfo=timezone.utc),
        duration_ms=123,
        size_bytes=456,
        host=SnapshotDetails(snapshot_id="abc", size_bytes=456, duration_ms=100),
        sandboxes={},
    )
    (sample_dir / "ckpt-00007.json").write_text(checkpoint.model_dump_json())

    event = _synthesize_trailing_checkpoint_event(str(sample_dir), 7)

    assert isinstance(event, CheckpointEvent)
    assert event.checkpoint_id == 7
    assert event.trigger == "turn"
    assert event.turn == 42
    assert event.host.snapshot_id == "abc"
    # Synthesized event's timestamp matches the checkpoint's original
    # creation time — indistinguishable from a live emit.
    assert event.timestamp == checkpoint.created_at


def _assert_spans_balanced(events: list[Event]) -> None:
    """Assert span_begin/span_end nest LIFO with nothing left open."""
    from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent

    stack: list[str] = []
    for e in events:
        if isinstance(e, SpanBeginEvent):
            stack.append(e.id)
        elif isinstance(e, SpanEndEvent):
            assert stack and stack[-1] == e.id, f"unbalanced span_end {e.id}"
            stack.pop()
    assert not stack, f"unclosed spans: {stack}"


def test_wrap_prior_run_reparents_existing_wraps_across_resumes() -> None:
    """A second resume keeps prior wraps as clean siblings under the current span.

    Models the cumulative buffer a second resume hydrates. Insertion
    order puts the seeded earlier ``prior_run`` wrap *first*, then the
    resumed session's own (still-open) structural ancestry, then a fresh
    unwrapped checkpoint span nested under that ancestry's ``agent``
    span. Both layers of scaffolding — leading (before the first wrap)
    and trailing (between the wrap and the new checkpoint) — must be
    sliced away: the surviving wrap is re-parented onto the current
    span, and the new checkpoint span becomes a second sibling wrap with
    nothing else inside it.
    """
    from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
    from inspect_ai.util._checkpoint.hydrate import _wrap_prior_run

    restored_events: list[Event] = [
        # leading scaffolding before the first wrap — dropped by the slice
        SpanBeginEvent(id="agent0", name="react", type="agent"),
        InfoEvent(data="leading-setup"),
        # the wrap hydrated during the prior resume (seeded first in the
        # buffer), parented to that resume's now-gone agent span
        SpanBeginEvent(
            id="restore-1",
            name="checkpoint restore 1",
            type="prior_run",
            parent_id="agent0",
        ),
        SpanBeginEvent(
            id="checkpoint-1",
            name="checkpoint 1",
            type="checkpoint",
            parent_id="restore-1",
        ),
        SpanEndEvent(id="checkpoint-1"),
        SpanEndEvent(id="restore-1"),
        # the resumed session's OWN structural ancestry, recorded after the
        # seeded wrap and still open at fire time — trailing scaffolding
        SpanBeginEvent(id="init1", name="init", type="init"),
        SpanEndEvent(id="init1"),
        SpanBeginEvent(id="solvers1", name="solvers"),
        SpanBeginEvent(id="solver1", name="react", type="solver", parent_id="solvers1"),
        SpanBeginEvent(id="agent1", name="react", type="agent", parent_id="solver1"),
        InfoEvent(data="trailing-setup"),
        # the new, still-unwrapped checkpoint span nested under that agent
        SpanBeginEvent(
            id="checkpoint-2",
            name="checkpoint 2",
            type="checkpoint",
            parent_id="agent1",
        ),
        SpanEndEvent(id="checkpoint-2"),
    ]

    wrapped = _wrap_prior_run(restored_events, parent_span_id="current")

    # all structural ancestry (leading and trailing) is gone
    span_ids = {
        event.id
        for event in wrapped
        if isinstance(event, (SpanBeginEvent, SpanEndEvent))
    }
    assert {"agent0", "init1", "solvers1", "solver1", "agent1"}.isdisjoint(span_ids)

    wrap_begins = [
        event
        for event in wrapped
        if isinstance(event, SpanBeginEvent) and event.type == "prior_run"
    ]
    assert [w.name for w in wrap_begins] == [
        "checkpoint restore 1",
        "checkpoint restore 2",
    ]
    # both wraps sit under the current session's span as siblings
    assert wrap_begins[0].id == "restore-1"
    assert wrap_begins[0].parent_id == "current"
    assert wrap_begins[1].parent_id == "current"

    # the new wrap's first child is checkpoint-2, re-parented onto it — the
    # wrap contains the checkpoint span and nothing else
    new_wrap = wrap_begins[1]
    new_wrap_idx = next(i for i, e in enumerate(wrapped) if e is new_wrap)
    first_child = wrapped[new_wrap_idx + 1]
    assert isinstance(first_child, SpanBeginEvent)
    assert first_child.id == "checkpoint-2"
    assert first_child.parent_id == new_wrap.id
    _assert_spans_balanced(wrapped)


def test_validate_resume_state_accepts_wrapped_checkpoint_shape(tmp_path: Path) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 2)
    events = _checkpoint_resume_events(2)

    _validate_resume_state(events, str(sample_root), 2)


def test_validate_resume_state_allows_torn_interior_checkpoint_file(
    tmp_path: Path,
) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 3)
    (sample_root / "ckpt-00002.json").write_text("{")
    events = _checkpoint_resume_events(3)

    _validate_resume_state(events, str(sample_root), 3)


def test_validate_resume_state_allows_non_utf8_torn_checkpoint_file(
    tmp_path: Path,
) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 3)
    (sample_root / "ckpt-00002.json").write_bytes(b'{"checkpoint_id": 2, "x": "\xe2')
    events = _checkpoint_resume_events(3)

    _validate_resume_state(events, str(sample_root), 3)


def test_validate_resume_state_allows_unreadable_interior_checkpoint_entry(
    tmp_path: Path,
) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 3)
    (sample_root / "ckpt-00002.json").unlink()
    (sample_root / "ckpt-00002.json").mkdir()
    events = _checkpoint_resume_events(3)

    _validate_resume_state(events, str(sample_root), 3)


def test_validate_resume_state_rejects_missing_prior_run_wrap(tmp_path: Path) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 2)
    events = _checkpoint_resume_events(2)
    unwrapped = [
        event
        for event in events
        if not (isinstance(event, SpanBeginEvent) and event.type == "prior_run")
    ]

    with pytest.raises(RuntimeError, match="no prior_run wrap"):
        _validate_resume_state(unwrapped, str(sample_root), 2)


def test_validate_resume_state_rejects_nonsequential_checkpoint_names(
    tmp_path: Path,
) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 2)
    events = _checkpoint_resume_events(2)
    for event in events:
        if (
            isinstance(event, SpanBeginEvent)
            and event.type == "checkpoint"
            and event.name == "checkpoint 2"
        ):
            event.name = "checkpoint 4"
            break

    with pytest.raises(RuntimeError, match="checkpoint span names not sequential"):
        _validate_resume_state(events, str(sample_root), 2)


def test_validate_resume_state_rejects_unparseable_latest_committed_file(
    tmp_path: Path,
) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 1)
    (sample_root / "ckpt-00002.json").write_text("{")
    events = _checkpoint_resume_events(2)

    with pytest.raises(RuntimeError, match="ckpt-00002.json is missing or unparseable"):
        _validate_resume_state(events, str(sample_root), 2)


def test_validate_resume_state_rejects_checkpoint_content_id_mismatch(
    tmp_path: Path,
) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 2)
    (sample_root / "ckpt-00002.json").write_text(_make_checkpoint(3).model_dump_json())
    events = _checkpoint_resume_events(2)

    with pytest.raises(RuntimeError, match="checkpoint file id mismatch"):
        _validate_resume_state(events, str(sample_root), 2)


def test_validate_resume_state_rejects_latest_committed_count_mismatch(
    tmp_path: Path,
) -> None:
    from inspect_ai.util._checkpoint.hydrate import _validate_resume_state

    sample_root = tmp_path / "sample"
    _write_checkpoint_files(sample_root, 2)
    events = _checkpoint_resume_events(2)

    with pytest.raises(RuntimeError, match="expected 1 checkpoint spans"):
        _validate_resume_state(events, str(sample_root), 1)


# --- tracing (inspect trace anomalies / dump --filter checkpoint) ---------


async def test_fire_emits_trace_action(dirs: _Dirs) -> None:
    """A fire is wrapped in a `Checkpoint` trace action (enter/exit).

    The action is what `inspect trace anomalies` consumes (a live fire shows
    as a Running Action; a stuck/cancelled fire as an anomaly). Every
    checkpoint trace record's message must contain ``checkpoint`` so
    ``inspect trace ... --filter checkpoint`` (a case-insensitive match on
    ``record.message``) catches the whole subsystem.
    """
    from inspect_ai._util.constants import TRACE

    # Collect directly off the emitting logger so capture is independent of
    # logging propagation / global level config.
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    target = logging.getLogger("inspect_ai.util._checkpoint.checkpointer_impl")
    handler = _Collector()
    prev_level = target.level
    target.addHandler(handler)
    target.setLevel(TRACE)
    try:
        async with _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs) as cp:
            await cp.tick()
            await cp.checkpoint()
    finally:
        target.removeHandler(handler)
        target.setLevel(prev_level)

    # The whole fire is wrapped in a `Checkpoint` trace action — enter + exit
    # share a single trace_id (one completed action).
    fire_actions = [r for r in records if getattr(r, "action", None) == "Checkpoint"]
    assert {getattr(r, "event", None) for r in fire_actions} >= {"enter", "exit"}
    assert len({getattr(r, "trace_id", None) for r in fire_actions}) == 1

    # Discovery invariant: `--filter checkpoint` must catch every record.
    assert records and all("checkpoint" in r.getMessage().lower() for r in records)


# --- max_consecutive_failures (working.md §8d) ----------------------------


async def test_unlimited_failures_never_raise(dirs: _Dirs) -> None:
    """Default (None) tolerates any number of consecutive failures."""
    cp = _flaky(ResolvedCheckpointConfig(trigger=Manual()), dirs)
    cp.should_fail = True
    for _ in range(5):
        await cp.checkpoint()  # swallowed, sample continues
    assert cp.attempts == 5
    assert cp._consecutive_failures == 5


async def test_zero_tolerance_raises_on_first_failure(dirs: _Dirs) -> None:
    """max_consecutive_failures=0 is strict — any failure is fatal."""
    cp = _flaky(
        ResolvedCheckpointConfig(trigger=Manual(), max_consecutive_failures=0), dirs
    )
    cp.should_fail = True
    with pytest.raises(CheckpointFailureLimitExceeded):
        await cp.checkpoint()


async def test_tolerates_n_then_raises_on_n_plus_one(dirs: _Dirs) -> None:
    """max_consecutive_failures=2 swallows 1 and 2, raises on the 3rd."""
    cp = _flaky(
        ResolvedCheckpointConfig(trigger=Manual(), max_consecutive_failures=2), dirs
    )
    cp.should_fail = True
    await cp.checkpoint()  # 1: swallowed
    await cp.checkpoint()  # 2: swallowed
    with pytest.raises(CheckpointFailureLimitExceeded):
        await cp.checkpoint()  # 3: > 2, raises


async def test_success_resets_consecutive_count(dirs: _Dirs) -> None:
    """A successful fire zeroes the counter, so failures never accumulate."""
    cp = _flaky(
        ResolvedCheckpointConfig(trigger=Manual(), max_consecutive_failures=2), dirs
    )
    for _ in range(2):
        cp.should_fail = True
        await cp.checkpoint()  # fail
        await cp.checkpoint()  # fail (count now 2)
        cp.should_fail = False
        await cp.checkpoint()  # succeed → reset to 0
        assert cp._consecutive_failures == 0


async def test_failure_recorded_as_info_event_and_warning(
    dirs: _Dirs, caplog: pytest.LogCaptureFixture
) -> None:
    """A swallowed failure emits an InfoEvent and logs a warning."""
    from inspect_ai.event._info import InfoEvent

    cp = _flaky(ResolvedCheckpointConfig(trigger=Manual()), dirs)
    cp.should_fail = True
    # A prior test may have called `eval()`, which sets `propagate=False`
    # on the `inspect_ai` logger — restore propagation for caplog.
    inspect_logger = logging.getLogger("inspect_ai")
    saved_propagate = inspect_logger.propagate
    inspect_logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING):
            await cp.checkpoint()
    finally:
        inspect_logger.propagate = saved_propagate

    infos = [
        e for e in dirs.events if isinstance(e, InfoEvent) and e.source == "checkpoint"
    ]
    assert len(infos) == 1
    assert isinstance(infos[0].data, dict)
    assert infos[0].data["event"] == "checkpoint_failed"
    assert infos[0].data["consecutive_failures"] == 1
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_limit_exceeded_chains_original_error(dirs: _Dirs) -> None:
    """The raised CheckpointFailureLimitExceeded chains the underlying error."""
    cp = _flaky(
        ResolvedCheckpointConfig(trigger=Manual(), max_consecutive_failures=0), dirs
    )
    cp.should_fail = True
    with pytest.raises(CheckpointFailureLimitExceeded) as excinfo:
        await cp.checkpoint()
    assert isinstance(excinfo.value.__cause__, _FlakyError)


# === Outer-facade tests =====================================================


@dataclass
class _FakeSample:
    id: int | str | None = 1


@dataclass
class _FakeActiveSample:
    sample: _FakeSample = field(default_factory=_FakeSample)
    epoch: int = 0
    log_location: str = ""  # filled in by the `active_sample` fixture
    eval_id: str | None = "test-eval-001"
    checkpoint: ResolvedCheckpointConfig | None = None
    # E2E tests assign this after building via `build_impl`.
    checkpointer: object = field(default_factory=_NoopCheckpointer)
    # Read by `SampleContextFilter` if a prior test has installed it on the
    # inspect_ai log handler (e.g. via `eval()`).
    task: str = "test_task"


@contextmanager
def _patch_sample_active(value: object) -> Iterator[None]:
    with patch(
        "inspect_ai.log._samples.sample_active",
        return_value=value,
    ):
        yield


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
def _patch_checkpointing_enabled() -> Iterator[None]:
    """Set INSPECT_CHECKPOINTING=1 so `build_impl()` runs its real path."""
    with patch.dict(os.environ, {"INSPECT_CHECKPOINTING": "1"}):
        yield


@pytest.fixture
def active_sample(tmp_path: Path) -> Iterator[_FakeActiveSample]:
    """Active sample fixture; redirects on-disk writes under tmp_path."""
    fake = _FakeActiveSample(log_location=str(tmp_path / "logs" / "test.eval"))
    (tmp_path / "logs").mkdir()
    with (
        _patch_sample_active(fake),
        _patch_cache_dir(tmp_path),
        _patch_restic(tmp_path),
        _patch_sample_runtime([]),
        _patch_checkpointing_enabled(),
    ):
        yield fake


# --- no active sample → contract violation --------------------------------


async def test_checkpointer_raises_without_active_sample() -> None:
    """`checkpointer()` outside an active sample is a contract violation."""
    with _patch_sample_active(None):
        with pytest.raises(RuntimeError, match="active sample"):
            async with checkpointer():
                pass


# === e2e: outer facade through to disk =====================================


async def test_fire_writes_restic_config_and_checkpoint_files(
    active_sample: _FakeActiveSample, tmp_path: Path
) -> None:
    """Driving the outer checkpointer end-to-end writes destination + working tree."""
    active_sample.sample.id = "s7"
    active_sample.epoch = 2
    active_sample.checkpoint = ResolvedCheckpointConfig(trigger=TurnInterval(every=2))

    # Inject a real checkpointer into the fake, mirroring what
    # `task_run_sample` does in production before opening `active_sample`.
    from inspect_ai.util._checkpoint.checkpointer_factory import create_checkpointer

    assert active_sample.sample.id is not None
    active_sample.checkpointer = create_checkpointer(
        config=active_sample.checkpoint,
        log_location=active_sample.log_location,
        sample_id=active_sample.sample.id,
        epoch=active_sample.epoch,
    )

    async with checkpointer() as cp:
        await cp.tick()  # informational boundary, no fire
        await cp.tick()  # turn 1 elapsed, no fire (every=2)
        await cp.tick()  # turn 2 elapsed, fires (ckpt-1)
        await cp.tick()  # turn 3 elapsed, no fire
        await cp.tick()  # turn 4 elapsed, fires (ckpt-2)

    log = Path(active_sample.log_location)
    eval_dir = log.parent / f"{log.stem}.checkpoints"
    sample_dir = eval_dir / "s7__2"
    assert (sample_dir / "restic" / "restic-config.json").is_file()
    checkpoint_files = sorted(p.name for p in sample_dir.glob("ckpt-*.json"))
    # Clean cm exit (no exception, attempt != RESUME_FOR_SCORING) triggers
    # the forced final "agent_complete" fire — so we get one more
    # checkpoint than the two policy-driven ones.
    assert checkpoint_files == [
        "ckpt-00001.json",
        "ckpt-00002.json",
        "ckpt-00003.json",
    ]
    # The final checkpoint itself is the scoring-phase-resume marker.
    from inspect_ai.util._checkpoint._layout.schemas import Checkpoint

    final_checkpoint = Checkpoint.model_validate_json(
        (sample_dir / "ckpt-00003.json").read_text()
    )
    assert final_checkpoint.trigger == "agent_complete"

    # Local destination → sample root is the sample checkpoints dir
    # itself; the `context/` subdir holds host context files.
    context = sample_dir / "context"
    assert context.is_dir()
    assert (context / "events.json").is_file()
    assert (context / "events_data.json").is_file()
    assert (context / "attachments.json").is_file()
    assert (context / "store.json").is_file()


# === _write_host_context: condensed events round-trip =======================


async def test_write_host_context_condenses_and_round_trips(tmp_path: Path) -> None:
    """Pooled ModelEvent inputs round-trip via expand_events; pool < total slots."""
    msg_sys: ChatMessage = ChatMessageSystem(content="sys")
    msg_u1: ChatMessage = ChatMessageUser(content="q1")
    msg_a1: ChatMessage = ChatMessageAssistant(content="a1")
    msg_u2: ChatMessage = ChatMessageUser(content="q2")
    msg_a2: ChatMessage = ChatMessageAssistant(content="a2")
    messages: list[ChatMessage] = [msg_sys, msg_u1, msg_a1, msg_u2, msg_a2]

    # Each ModelEvent carries the full prior history — 2 + 4 + 5 = 11 input
    # slots across 5 unique messages.
    events: list[Event] = [
        make_model_event([msg_sys, msg_u1]),
        make_model_event([msg_sys, msg_u1, msg_a1, msg_u2]),
        make_model_event(messages),
    ]

    work = tmp_path / "work"
    work.mkdir()
    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration(str(tmp_path / "ckpts"), str(work)),
        resume_checkpoint=None,
        reset_transcript_store=True,
    )
    for event in events:
        cp._track_transcript_event(event)
    await cp._write_host_context(str(work), Store())

    assert (work / "events.json").is_file()
    assert (work / "events_data.json").is_file()
    assert (work / "attachments.json").is_file()
    assert (work / "store.json").is_file()

    events_json = (work / "events.json").read_text()
    data_json = (work / "events_data.json").read_text()

    # Pool dedup happened: 5 unique messages, not 11.
    pool = json.loads(data_json)
    assert len(pool["messages"]) == 5

    # Recovered events match the originals turn-for-turn.
    expanded = expand_events(events_json, data_json)
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert [len(e.input) for e in model_events] == [2, 4, 5]


def _make_cp(**kwargs: object) -> _EnteredCheckpointer:
    # Unique per call so parallel xdist workers (and successive calls) don't
    # collide on the same SQLite transcript store under context_dir.
    base = Path(tempfile.mkdtemp(prefix="cp-test-"))
    defaults: dict[str, object] = {
        "config": ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        "hydration": _fake_hydration(str(base / "ckpts"), str(base / "work")),
        "resume_checkpoint": None,
        "reset_transcript_store": True,
    }
    defaults.update(kwargs)
    cp = _EnteredCheckpointer(**defaults)  # type: ignore[arg-type]
    return cp


def test_track_returns_initial_value(tmp_path: Path) -> None:
    """Without resume hydration, `track()` always returns initial_value."""
    cp = _make_cp()
    out = cp.track("attempt_count", lambda: 7, 0)
    assert out == 0


def test_track_duplicate_key_raises(tmp_path: Path) -> None:
    cp = _make_cp()
    cp.track("attempt_count", lambda: 1, 0)
    with pytest.raises(ValueError, match="unique"):
        cp.track("attempt_count", lambda: 2, 0)


async def _write_agent_state(
    tmp_path: Path, cp: _EnteredCheckpointer
) -> dict[str, object] | None:
    work = tmp_path / "work"
    work.mkdir()
    await cp._write_host_context(str(work), Store())
    agent_state = work / "agent_state.json"
    if not agent_state.exists():
        return None
    return json.loads(agent_state.read_text())


async def test_track_single_key_writes_file(tmp_path: Path) -> None:
    """Registered callback's return value lands in agent_state.json."""
    cp = _make_cp()
    value = 3
    cp.track("attempt_count", lambda: value, 0)

    assert await _write_agent_state(tmp_path, cp) == {"attempt_count": 3}


async def test_track_messages_via_track(tmp_path: Path) -> None:
    """Messages persist via `track('messages', ...)` — Pydantic model lists serialize."""
    cp = _make_cp()
    messages: list[ChatMessage] = [
        ChatMessageSystem(content="sys"),
        ChatMessageUser(content="hi"),
    ]
    cp.track(
        "messages",
        lambda: messages,
        messages,
        value_type=list[ChatMessage],
    )

    state = await _write_agent_state(tmp_path, cp)
    assert state is not None
    assert "messages" in state
    messages_state = state["messages"]
    assert isinstance(messages_state, list)
    assert [m["role"] for m in messages_state] == ["system", "user"]
    assert [m["content"] for m in messages_state] == ["sys", "hi"]


async def test_track_multiple_keys_merge(tmp_path: Path) -> None:
    """Multiple registered keys merge into one top-level dict."""
    cp = _make_cp()
    cp.track("attempt_count", lambda: 3, 0)
    cp.track("phase", lambda: "explore", "")

    assert await _write_agent_state(tmp_path, cp) == {
        "attempt_count": 3,
        "phase": "explore",
    }


async def test_track_not_registered_no_file(tmp_path: Path) -> None:
    """Without any callback, agent_state.json is not written."""
    cp = _make_cp()

    assert await _write_agent_state(tmp_path, cp) is None


def test_track_noop_session() -> None:
    """`_NoopCheckpointer.track()` returns initial_value and never registers."""
    cp = _NoopCheckpointer()
    out = cp.track("attempt_count", lambda: 42, 0)
    assert out == 0


def test_attempt_noop_initial() -> None:
    assert _NoopCheckpointer().attempt == "initial"


def test_attempt_reflects_resume_checkpoint() -> None:
    from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint

    assert _make_cp().attempt == "initial"
    assert (
        _make_cp(
            resume_checkpoint=ResumeCheckpoint(
                sample_checkpoints_dir="/x", attempt="resume"
            ),
        ).attempt
        == "resume"
    )
    assert (
        _make_cp(
            resume_checkpoint=ResumeCheckpoint(
                sample_checkpoints_dir="/x", attempt="resume_for_scoring"
            ),
        ).attempt
        == "resume_for_scoring"
    )


async def test_setup_aenter_defers_io_setup(tmp_path: Path) -> None:
    """All I/O setup (incl. sandbox loop) runs in _CheckpointerSetup.__aenter__."""
    from unittest.mock import AsyncMock, MagicMock

    setup = _CheckpointerSetup(
        config=ResolvedCheckpointConfig(
            trigger=TurnInterval(every=1),
            sandbox_paths={"web": ["/var/www"]},
        ),
        log_location=str(tmp_path / "t.eval"),
        sample_id="s",
        epoch=0,
    )

    from inspect_ai.util._subprocess import ExecResult

    fake_env = MagicMock()
    # Even a config-specified sandbox runs one resolution exec (home + XDG
    # cache) so the cache dir can be excluded; canned `home\ncache` output.
    fake_env.exec = AsyncMock(
        return_value=ExecResult(
            success=True, returncode=0, stdout="/root\n/root/.cache", stderr=""
        )
    )
    fake_sample_state = MagicMock(restic_password="pwd")
    sample_ckpt_path = str(tmp_path / "ckpts" / "s__0")

    # Live-sandbox set drives hydration; "web" has an explicit config entry.
    from inspect_ai.util._sandbox.context import sandbox_environments_context_var

    sandbox_token = sandbox_environments_context_var.set({"web": fake_env})

    with (
        patch(
            "inspect_ai.util._checkpoint.hydrate.ensure_sample_checkpoints_dir",
            new=AsyncMock(return_value=sample_ckpt_path),
        ) as ensure_ckpt,
        patch(
            "inspect_ai.util._checkpoint.hydrate.ensure_context_dir",
            new=AsyncMock(return_value=f"{sample_ckpt_path}/context"),
        ) as ensure_ctx,
        patch(
            "inspect_ai.util._checkpoint.hydrate.ensure_restic_config",
            new=AsyncMock(return_value=fake_sample_state),
        ) as ensure_config_mock,
        patch(
            "inspect_ai.util._checkpoint.hydrate.resolve_restic",
            new=AsyncMock(return_value=Path("/fake/restic")),
        ) as resolve,
        patch(
            "inspect_ai.util._checkpoint.hydrate.init_repo",
            new=AsyncMock(),
        ) as init_host,
        patch(
            "inspect_ai.util._checkpoint.hydrate.sandbox",
            return_value=fake_env,
        ) as get_sandbox,
        patch(
            "inspect_ai.util._checkpoint.hydrate.inject_restic",
            new=AsyncMock(),
        ) as inject,
        patch(
            "inspect_ai.util._checkpoint.hydrate.init_sandbox_repo",
            new=AsyncMock(),
        ) as init_sandbox,
    ):
        io_mocks = (
            ensure_ckpt,
            ensure_ctx,
            ensure_config_mock,
            resolve,
            init_host,
            get_sandbox,
            inject,
            init_sandbox,
        )
        for m in io_mocks:
            m.assert_not_called()

        async with setup as cp:
            assert isinstance(cp, _EnteredCheckpointer)
            # __aenter__ ran every I/O step exactly once
            ensure_ckpt.assert_awaited_once()
            ensure_ctx.assert_awaited_once()
            ensure_config_mock.assert_awaited_once()
            resolve.assert_awaited_once()
            init_host.assert_awaited_once()
            get_sandbox.assert_called_once_with("web")
            inject.assert_awaited_once_with(fake_env)
            init_sandbox.assert_awaited_once_with(fake_env, "pwd")

        call_counts = [m.call_count for m in io_mocks]
        async with setup as cp2:
            assert cp2 is cp
            assert [m.call_count for m in io_mocks] == call_counts

    sandbox_environments_context_var.reset(sandbox_token)


async def test_write_host_context_exports_transcript_store_attachments(
    tmp_path: Path,
) -> None:
    attachments = {"abc123": "data:image/png;base64,iVBORw0", "def456": "long-text"}

    work = tmp_path / "work"
    work.mkdir()
    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration(str(tmp_path / "ckpts"), str(work)),
        resume_checkpoint=None,
        reset_transcript_store=True,
    )
    cp._transcript_store.merge_attachments(attachments)
    await cp._write_host_context(str(work), Store())

    assert json.loads((work / "attachments.json").read_text()) == attachments


async def test_write_host_context_accumulates_across_fires(tmp_path: Path) -> None:
    """Each fire processes only the new event slice; pool + events grow append-only."""
    msg_sys: ChatMessage = ChatMessageSystem(content="sys")
    msg_u1: ChatMessage = ChatMessageUser(content="q1")
    msg_a1: ChatMessage = ChatMessageAssistant(content="a1")
    msg_u2: ChatMessage = ChatMessageUser(content="q2")

    fire1_events: list[Event] = [
        make_model_event([msg_sys, msg_u1]),
        make_model_event([msg_sys, msg_u1, msg_a1]),
    ]
    fire2_events: list[Event] = [
        make_model_event([msg_sys, msg_u1, msg_a1, msg_u2]),
    ]

    work = tmp_path / "work"
    work.mkdir()
    init_transcript(Transcript(bounded=False))
    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "context")),
        resume_checkpoint=None,
        reset_transcript_store=True,
    )
    try:
        cp.track("messages", lambda: [msg_sys], [msg_sys], value_type=list[ChatMessage])
        store = Store()
        store.set("store_message", msg_sys)
        for event in fire1_events:
            cp._track_transcript_event(event)
        await cp._write_host_context(str(work), store)
        store_json = json.loads((work / "store.json").read_text())
        agent_state = json.loads((work / "agent_state.json").read_text())
        events = json.loads((work / "events.json").read_text())
        events_data = json.loads((work / "events_data.json").read_text())
        attachments = json.loads((work / "attachments.json").read_text())
        assert store_json["store_message"]["role"] == "system"
        assert agent_state["messages"][0]["role"] == "system"
        assert isinstance(events, list)
        assert set(events_data) >= {"messages", "calls"}
        assert isinstance(attachments, dict)
        pool_after_1 = events_data["messages"]
        events_after_1 = json.loads((work / "events.json").read_text())
        assert len(pool_after_1) == 3  # sys, u1, a1
        assert len(events_after_1) == 2

        for event in fire2_events:
            cp._track_transcript_event(event)
        await cp._write_host_context(str(work), Store())
        pool_after_2 = json.loads((work / "events_data.json").read_text())["messages"]
        events_after_2 = json.loads((work / "events.json").read_text())
        # Append-only: pool grew by exactly one (u2); first 3 entries unchanged.
        assert pool_after_2[:3] == pool_after_1
        assert len(pool_after_2) == 4
        assert events_after_2[:2] == events_after_1
        assert len(events_after_2) == 3
    finally:
        cp.close()

    # Full round-trip still works on the cumulative output.
    expanded = expand_events(
        (work / "events.json").read_text(),
        (work / "events_data.json").read_text(),
    )
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert [len(e.input) for e in model_events] == [2, 3, 4]


def test_track_consumes_hydrated_agent_state(tmp_path: Path) -> None:
    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work"))
    hydration.host.agent_state = {"phase": "resume", "other": "kept"}
    cp = _make_cp(hydration=hydration)

    assert cp.track("phase", lambda: "fresh", "fresh") == "resume"

    assert "phase" not in cp._agent_state
    assert cp._agent_state == {"other": "kept"}


def test_seed_transcript_store_uses_history_provider_for_truncated_transcript(
    tmp_path: Path,
) -> None:
    provider_events = [
        InfoEvent(uuid=f"provider-event-{index}", data=f"from-provider-{index}")
        for index in range(3)
    ]
    provider = FakeTranscriptHistoryProvider(provider_events)
    fake_transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=provider,
    )
    for event in provider_events:
        fake_transcript._event(event)
    assert fake_transcript.history.resident_events_truncated is True

    with patch(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        return_value=fake_transcript,
    ):
        cp = _make_cp(
            hydration=_fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work")),
        )

    work = tmp_path / "snapshot"
    work.mkdir()
    _write_transcript_files(cp._transcript_store, work)
    cp.close()

    events = json.loads((work / "events.json").read_text())
    assert [event["data"] for event in events] == [
        "from-provider-0",
        "from-provider-1",
        "from-provider-2",
    ]


def test_checkpointer_closes_store_when_transcript_seed_fails(tmp_path: Path) -> None:
    fake_transcript = Transcript(bounded=True, resident_tail=0)
    fake_transcript._event(InfoEvent(data="evicted"))
    assert fake_transcript.history.resident_events_truncated is True

    with patch(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        return_value=fake_transcript,
    ):
        with pytest.raises(RuntimeError, match="Cannot seed transcript events"):
            _make_cp(
                hydration=_fake_hydration(
                    str(tmp_path / "ckpts"), str(tmp_path / "work")
                ),
            )


async def test_checkpointer_setup_resets_transcript_store_after_seed_failure(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    checkpoints = tmp_path / "ckpts"
    work.mkdir()
    checkpoints.mkdir()
    fake_transcript = Transcript(bounded=False)
    fake_transcript._event(InfoEvent(uuid="seeded", data="seeded"))
    hydration = _fake_hydration(str(checkpoints), str(work))
    calls = 0

    def fail_once_merge_event(self: TranscriptEventStore, *args: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_merge_event(self, *args)  # type: ignore[arg-type]
            raise RuntimeError("seed failed")
        original_merge_event(self, *args)  # type: ignore[arg-type]

    original_merge_event = TranscriptEventStore.merge_event
    setup = _CheckpointerSetup(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        log_location=str(tmp_path / "t.eval"),
        sample_id="s",
        epoch=0,
    )

    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.hydrate",
            return_value=hydration,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
            return_value=fake_transcript,
        ),
        patch.object(TranscriptEventStore, "merge_event", fail_once_merge_event),
    ):
        with pytest.raises(RuntimeError, match="seed failed"):
            await setup.__aenter__()

        cp = await setup.__aenter__()
        assert isinstance(cp, _EnteredCheckpointer)
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        await cp._write_host_context(str(snapshot), Store())
        setup.close()

    events = json.loads((snapshot / "events.json").read_text())
    assert [event["data"] for event in events] == ["seeded"]


async def test_fire_retains_attachment_from_evicted_event(
    tmp_path: Path,
) -> None:
    transcript = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    cp = _make_cp(
        hydration=_fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work"))
    )
    payload = "evicted payload" * 100
    evicted = ModelEvent(
        uuid="evicted",
        model="mockllm/model",
        input=[ChatMessageUser(content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "answer"),
    )
    evicted.call = ModelCall.create(
        {"messages": [{"role": "user", "content": payload}]}, None
    )

    with patch(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        return_value=transcript,
    ):
        transcript._subscribe(cp._track_transcript_event)
        transcript._event(evicted)
        transcript._event(InfoEvent(data="resident"))

    assert transcript.history.resident_events == [transcript.history.last_event]
    assert transcript.attachments == {}

    work = tmp_path / "snapshot"
    work.mkdir()
    await cp._write_host_context(str(work), Store())
    cp.close()

    attachments = json.loads((work / "attachments.json").read_text())
    assert payload in attachments.values()


async def test_checkpointer_setup_close_unsubscribes_and_closes_store(
    tmp_path: Path,
) -> None:
    fake_transcript = Transcript(bounded=False)

    setup = _CheckpointerSetup(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        log_location=str(tmp_path / "t.eval"),
        sample_id="s",
        epoch=0,
    )
    # Store-lifecycle test only: suppress the clean-exit finalize so the
    # `async with setup` exits don't fire an `agent_complete` checkpoint
    # (which would emit extra transcript events). Finalize is covered by
    # the dedicated `__aexit__` tests below.
    setup._finalized = True
    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work"))
    Path(hydration.sample_checkpoints_dir).mkdir(parents=True)
    Path(hydration.context_dir).mkdir(parents=True)

    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.hydrate",
            return_value=hydration,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
            return_value=fake_transcript,
        ),
    ):
        async with setup as cp:
            assert isinstance(cp, _EnteredCheckpointer)
            fake_transcript._event(InfoEvent(data="during"))
            assert cp._transcript_store.counts().events == 1
        fake_transcript._event(InfoEvent(data="between"))
        assert cp._transcript_store.counts().events == 2

        async with setup as cp2:
            assert cp2 is cp
            fake_transcript._event(InfoEvent(data="again"))
            assert cp._transcript_store.counts().events == 3

        setup.close()
        assert setup._cached is None
        fake_transcript._event(InfoEvent(data="after-close"))
        setup.close()


async def test_checkpointer_setup_reconstruct_preserves_transcript_store(
    tmp_path: Path,
) -> None:
    fake_transcript = Transcript(bounded=False)
    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work"))
    Path(hydration.sample_checkpoints_dir).mkdir(parents=True)
    Path(hydration.context_dir).mkdir(parents=True)
    setup = _CheckpointerSetup(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        log_location=str(tmp_path / "t.eval"),
        sample_id="s",
        epoch=0,
    )
    # Store-lifecycle test only: suppress the clean-exit finalize so the
    # `async with setup` exits don't fire an `agent_complete` checkpoint
    # (which would emit extra transcript events). Finalize is covered by
    # the dedicated `__aexit__` tests below.
    setup._finalized = True

    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.hydrate",
            return_value=hydration,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
            return_value=fake_transcript,
        ),
    ):
        async with setup as first:
            assert isinstance(first, _EnteredCheckpointer)
            first._track_transcript_event(InfoEvent(data="first"))

        async with setup as second:
            assert isinstance(second, _EnteredCheckpointer)
            second._track_transcript_event(InfoEvent(data="second"))
            work = tmp_path / "snapshot"
            work.mkdir()
            await second._write_host_context(str(work), Store())

    events = json.loads((work / "events.json").read_text())
    assert [event["data"] for event in events] == ["first", "second"]


# === __aexit__ finalize: scoring-phase-resume handoff ========================
#
# On a clean agent exit the setup fires a final "agent_complete" checkpoint and
# a later scoring crash can resume into `"resume_for_scoring"` and skip
# the agent loop. These tests pin the gating: finalize fires iff the cm was
# entered, exited cleanly, isn't already a scoring-phase resume, and hasn't
# already finalized.


@contextmanager
def _finalize_setup(
    tmp_path: Path,
    *,
    attempt: Literal["initial", "resume", "resume_for_scoring"] | None = None,
) -> Iterator[_CheckpointerSetup]:
    """Yield a patched `_CheckpointerSetup`.

    `hydrate` and `transcript` are stubbed (no real I/O). Pass `attempt`
    to simulate a resumed session.
    """
    fake_transcript = Transcript(bounded=False)
    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work"))
    Path(hydration.sample_checkpoints_dir).mkdir(parents=True)
    Path(hydration.context_dir).mkdir(parents=True)
    resume = (
        ResumeCheckpoint(
            sample_checkpoints_dir=str(tmp_path / "prior"), attempt=attempt
        )
        if attempt is not None
        else None
    )
    setup = _CheckpointerSetup(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        log_location=str(tmp_path / "t.eval"),
        sample_id="s",
        epoch=0,
        resume_checkpoint=resume,
    )
    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.hydrate",
            return_value=hydration,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
            return_value=fake_transcript,
        ),
    ):
        yield setup


async def test_finalize_fires_agent_complete(
    tmp_path: Path,
) -> None:
    with _finalize_setup(tmp_path) as setup:
        fire = AsyncMock()
        with patch.object(_EnteredCheckpointer, "_fire", fire):
            async with setup as cp:
                assert isinstance(cp, _EnteredCheckpointer)
        # clean exit → one forced final fire
        fire.assert_awaited_once_with("agent_complete", final=True)


async def test_finalize_skipped_when_exception_propagates(tmp_path: Path) -> None:
    with _finalize_setup(tmp_path) as setup:
        fire = AsyncMock()
        with patch.object(_EnteredCheckpointer, "_fire", fire):
            with pytest.raises(RuntimeError, match="boom"):
                async with setup as cp:
                    assert isinstance(cp, _EnteredCheckpointer)
                    raise RuntimeError("boom")
        # agent raised — the final fire should not run
        fire.assert_not_awaited()


async def test_finalize_skipped_for_scoring_phase_resume(tmp_path: Path) -> None:
    with _finalize_setup(tmp_path, attempt="resume_for_scoring") as setup:
        fire = AsyncMock()
        with patch.object(_EnteredCheckpointer, "_fire", fire):
            async with setup as cp:
                assert isinstance(cp, _EnteredCheckpointer)
        # latest checkpoint is already agent_complete — don't re-fire
        assert cp.attempt == "resume_for_scoring"
        fire.assert_not_awaited()


async def test_finalize_attempts_final_fire_even_when_tolerated_failure(
    tmp_path: Path,
) -> None:
    with _finalize_setup(tmp_path) as setup:
        fire = AsyncMock()
        with patch.object(_EnteredCheckpointer, "_fire", fire):
            async with setup as cp:
                assert isinstance(cp, _EnteredCheckpointer)
                # stand in for a tolerated fire failure: `_fire` swallows the
                # error but leaves the failure count non-zero
                fire.side_effect = lambda *a, **k: setattr(
                    cp, "_consecutive_failures", 1
                )
        # final fire was attempted; no separate marker is written.
        fire.assert_awaited_once_with("agent_complete", final=True)


async def test_finalize_idempotent_across_reentry(tmp_path: Path) -> None:
    with _finalize_setup(tmp_path) as setup:
        fire = AsyncMock()
        with patch.object(_EnteredCheckpointer, "_fire", fire):
            async with setup as cp:
                assert isinstance(cp, _EnteredCheckpointer)
            async with setup as cp2:
                # cached re-entry returns the same checkpointer
                assert cp2 is cp
        # only the first clean exit finalizes
        fire.assert_awaited_once_with("agent_complete", final=True)


async def test_resume_resets_restored_transcript_store_before_seeding(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    restored_store = TranscriptEventStore(
        work / "checkpoint_transcript.sqlite", reset=True
    )
    restored_store.merge_event(InfoEvent(data="orphan"), lambda _: None)
    restored_store.close()

    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(work))
    hydration.host.condensed_events = [InfoEvent(data="committed")]
    fake_transcript = Transcript(bounded=False)
    setup = _CheckpointerSetup(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        log_location=str(tmp_path / "t.eval"),
        sample_id="s",
        epoch=0,
        resume_checkpoint=ResumeCheckpoint(
            sample_checkpoints_dir=str(tmp_path / "prior-ckpts"),
            attempt="resume",
        ),
    )

    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.hydrate",
            return_value=hydration,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
            return_value=fake_transcript,
        ),
    ):
        cp = await setup.__aenter__()
        assert isinstance(cp, _EnteredCheckpointer)
        cp._track_transcript_event(InfoEvent(data="new"))
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        await cp._write_host_context(str(snapshot), Store())
        setup.close()

    events = json.loads((snapshot / "events.json").read_text())
    assert [event["data"] for event in events] == ["committed", "new"]


def test_resume_seed_skips_restored_resident_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restored = InfoEvent(uuid="restored", data="committed")
    fake_transcript = Transcript([restored], bounded=False)
    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work"))
    hydration.host.condensed_events = [restored]

    monkeypatch.setattr(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        lambda: fake_transcript,
    )

    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=hydration,
        resume_checkpoint=ResumeCheckpoint(
            sample_checkpoints_dir=str(tmp_path / "old"),
            attempt="resume",
        ),
        reset_transcript_store=True,
    )
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _write_transcript_files(cp._transcript_store, snapshot)
    cp.close()

    events = json.loads((snapshot / "events.json").read_text())
    assert [event["uuid"] for event in events] == ["restored"]
    assert [event["data"] for event in events] == ["committed"]


def test_checkpointer_tracks_event_emitted_during_history_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks: list[Callable[[Event], None]] = []
    emitted = InfoEvent(uuid="during-seed", data="during-seed")

    def subscribe(callback: Callable[[Event], None]) -> Callable[[], None]:
        callbacks.append(callback)
        return lambda: callbacks.remove(callback)

    class Provider:
        def export_transcript_events(
            self, transcript_store: TranscriptEventStore
        ) -> int:
            for callback in callbacks:
                callback(emitted)
            return 0

    class History:
        resident_events: list[Event] = []
        resident_events_truncated = True

        def __init__(self, provider: Provider) -> None:
            self.provider = provider

    class ExportingTranscript:
        attachments: dict[str, str] = {}

        def __init__(self, provider: Provider) -> None:
            self.history = History(provider)

        def _subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
            return subscribe(callback)

    provider = Provider()
    fake_transcript = ExportingTranscript(provider)
    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "work"))
    monkeypatch.setattr(
        "inspect_ai.util._checkpoint.checkpointer_impl.transcript",
        lambda: fake_transcript,
    )

    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=hydration,
        resume_checkpoint=None,
        reset_transcript_store=True,
    )
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _write_transcript_files(cp._transcript_store, snapshot)
    cp.close()

    events = json.loads((snapshot / "events.json").read_text())
    assert [event["data"] for event in events] == ["during-seed"]


async def test_resume_seed_preserves_message_pool_positions(tmp_path: Path) -> None:
    msg_sys: ChatMessage = ChatMessageSystem(content="sys")
    msg_u1: ChatMessage = ChatMessageUser(content="q1")
    msg_a1: ChatMessage = ChatMessageAssistant(content="a1")
    msg_u2: ChatMessage = ChatMessageUser(content="q2")

    first_work = tmp_path / "first"
    first_work.mkdir()
    first_cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "state1")),
        resume_checkpoint=None,
        reset_transcript_store=True,
    )
    first_cp._track_transcript_event(make_model_event([msg_sys, msg_u1, msg_a1]))
    await first_cp._write_host_context(str(first_work), Store())

    from inspect_ai.util._checkpoint._layout import host_context

    first_context = host_context.read(str(first_work))
    assert len(first_context.condensed_events) == 1

    hydration = _fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "state2"))
    hydration.host.condensed_events = first_context.condensed_events
    hydration.host.msg_pool = first_context.msg_pool
    hydration.host.call_pool = first_context.call_pool
    resumed_cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=hydration,
        resume_checkpoint=None,
        reset_transcript_store=True,
    )

    resumed_work = tmp_path / "resumed"
    resumed_work.mkdir()
    resumed_cp._track_transcript_event(make_model_event([msg_u2]))
    await resumed_cp._write_host_context(str(resumed_work), Store())

    resumed_data = json.loads((resumed_work / "events_data.json").read_text())
    assert len(resumed_data["messages"]) == 4
    expanded = expand_events(
        (resumed_work / "events.json").read_text(),
        (resumed_work / "events_data.json").read_text(),
    )
    model_events = [event for event in expanded if isinstance(event, ModelEvent)]
    assert [len(event.input) for event in model_events] == [3, 1]
    assert [message.content for message in model_events[0].input] == ["sys", "q1", "a1"]
    assert [message.content for message in model_events[1].input] == ["q2"]


async def test_materialize_pooled_model_event_expands_seed_payload(
    tmp_path: Path,
) -> None:
    from inspect_ai.event._pool import materialize_pooled_events
    from inspect_ai.util._checkpoint._layout import host_context

    msg_sys: ChatMessage = ChatMessageSystem(content="sys")
    msg_user: ChatMessage = ChatMessageUser(content="question")
    call_request = {"messages": [{"role": "user", "content": "question"}]}
    restored = make_model_event(
        [msg_sys, msg_user],
        uuid="restored-model",
        call=ModelCall.create(call_request, None),
    )

    work = tmp_path / "work"
    work.mkdir()
    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration(str(tmp_path / "ckpts"), str(tmp_path / "state")),
        resume_checkpoint=None,
        reset_transcript_store=True,
    )
    cp._track_transcript_event(restored)
    await cp._write_host_context(str(work), Store())
    cp.close()

    context = host_context.read(str(work))
    condensed = context.condensed_events[0]
    assert isinstance(condensed, ModelEvent)
    assert condensed.input_refs is not None
    assert condensed.call is not None
    assert condensed.call.call_refs is not None

    materialized = materialize_pooled_events(
        context.condensed_events,
        context.msg_pool,
        context.call_pool,
    )
    assert len(materialized) == 1
    seeded_model = materialized[0]
    assert isinstance(seeded_model, ModelEvent)
    assert seeded_model.input_refs is None
    assert [message.content for message in seeded_model.input] == ["sys", "question"]
    assert seeded_model.call is not None
    assert seeded_model.call.call_refs is None
    assert seeded_model.call.request == call_request
