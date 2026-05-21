"""Policy + outer-facade tests for the checkpointer.

The policy tests drive ``_CheckpointerSetup`` directly with prepared dirs
and call its methods without going through the public facade.
Outer-facade tests cover dispatch, sample-identity validation, and
ContextVar wiring (the public ``checkpointer`` is what registers the
active session).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.log import expand_events
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.util._checkpoint import (
    Manual,
    TimeInterval,
    TokenInterval,
    TurnInterval,
    checkpointer,
)
from inspect_ai.util._checkpoint._triggers import CheckpointTriggerKind
from inspect_ai.util._checkpoint.checkpointer_impl import (
    _CheckpointerSetup,
    _EnteredCheckpointer,
)
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer
from inspect_ai.util._checkpoint.config import ResolvedCheckpointConfig
from inspect_ai.util._checkpoint.hydrate import HydrationResult, _HostHydrationResult
from inspect_ai.util._restic import ResticBackupSummary
from inspect_ai.util._store import Store


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
    working: str
    events: list[object] = field(default_factory=list)
    """Live-collected transcript events from the fake transcript patched
    into `_patch_sample_runtime`. Tests that drive fires can inspect this
    to assert emit behavior (e.g. `CheckpointEvent`)."""


@contextmanager
def _patch_sample_runtime(events: list[object]) -> Iterator[None]:
    """Patch sample_state() and transcript() for tests that drive _fire.

    `_CheckpointerSetup._fire` reads ``sample_state().store`` and
    ``transcript().events`` directly from ContextVars. Tests that
    construct `_CheckpointerSetup` outside a real sample run need stand-ins.

    ``events`` is the externally-owned event-collection list — the fake
    transcript's ``events`` attribute and ``_event`` callable both wire
    to it so tests can inspect emit behavior.
    """
    from types import SimpleNamespace

    from inspect_ai.util._store import Store

    fake_state = SimpleNamespace(store=Store())
    fake_transcript = SimpleNamespace(
        events=events,
        attachments={},
        _event=events.append,
    )
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
    """Pre-create the two sample dirs without going through the facade."""
    checkpoints = tmp_path / "logs/test.checkpoints/s__0"
    working = tmp_path / "cache/checkpoints/test/s__0"
    checkpoints.mkdir(parents=True)
    working.mkdir(parents=True)
    d = _Dirs(checkpoints=str(checkpoints), working=str(working))
    with _patch_sample_runtime(d.events):
        yield d


class _CountingCheckpointer(_EnteredCheckpointer):
    """Counts fires on top of the real fire path; stubs out restic."""

    fire_count: int = 0

    async def _fire(self, trigger: CheckpointTriggerKind) -> None:
        await super()._fire(trigger)
        self.fire_count += 1

    async def _backup_host(self, checkpoint_id: int) -> ResticBackupSummary:
        return _fake_summary(checkpoint_id)


def _fake_hydration(
    sample_checkpoints_dir: str, sample_working_dir: str
) -> HydrationResult:
    return HydrationResult(
        sample_checkpoints_dir=sample_checkpoints_dir,
        sample_working_dir=sample_working_dir,
        host_restic=Path("/fake/restic"),
        host_repo=f"{sample_checkpoints_dir}/host",
        restic_password="test-pwd",
        host=_HostHydrationResult(),
    )


def _counting(config: ResolvedCheckpointConfig, dirs: _Dirs) -> _CountingCheckpointer:
    cp = _CountingCheckpointer(
        config=config,
        hydration=_fake_hydration(dirs.checkpoints, dirs.working),
        resume_checkpoint=None,
    )
    # Policy tests drive `tick()`/`checkpoint()` without going through
    # `span_session()`, so the first-span lazy init for `_events_consumed`
    # never fires. Seed it here so `_write_host_context` can slice.
    cp._events_consumed = 0
    return cp


# --- turn-based -----------------------------------------------------------


async def test_turn_interval_fires_at_each_threshold(dirs: _Dirs) -> None:
    # First tick is informational (boundary before turn 1) — doesn't
    # count toward the threshold. With every=3, fires happen on ticks
    # 4, 7, 10 — capturing 3 turns each. 10 ticks → 3 fires.
    cp = _counting(ResolvedCheckpointConfig(trigger=TurnInterval(every=3)), dirs)
    for _ in range(10):
        await cp.tick()
    assert cp.fire_count == 3


async def test_turn_interval_resets_counter_on_fire(dirs: _Dirs) -> None:
    cp = _counting(ResolvedCheckpointConfig(trigger=TurnInterval(every=4)), dirs)
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
        cp = _counting(
            ResolvedCheckpointConfig(trigger=TimeInterval(every=timedelta(seconds=10))),
            dirs,
        )
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
        cp = _counting(
            ResolvedCheckpointConfig(trigger=TokenInterval(every=1000)),
            dirs,
        )
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
    cp = _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs)
    for _ in range(50):
        await cp.tick()
    assert cp.fire_count == 0


async def test_checkpoint_method_fires(dirs: _Dirs) -> None:
    cp = _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs)
    await cp.tick()
    await cp.checkpoint()
    await cp.checkpoint()
    assert cp.fire_count == 2


# --- CheckpointEvent emission ---------------------------------------------


async def test_fire_emits_checkpoint_event(dirs: _Dirs) -> None:
    """Successful fire appends a `CheckpointEvent` carrying the sidecar."""
    from inspect_ai.event._checkpoint import CheckpointEvent

    cp = _counting(ResolvedCheckpointConfig(trigger=Manual()), dirs)
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
    # Flattened sidecar fields carry full per-repo info; with no real
    # restic the stub values from `_CountingCheckpointer._backup_host`
    # round-trip.
    assert first.host.snapshot_id.startswith("fake-snap-")


def test_synthesize_trailing_checkpoint_event(tmp_path: Path) -> None:
    """Hydrate reconstructs the trailing CheckpointEvent from a sidecar."""
    from datetime import datetime, timezone

    from inspect_ai.event._checkpoint import CheckpointEvent
    from inspect_ai.util._checkpoint._layout import CheckpointDetails, SnapshotDetails
    from inspect_ai.util._checkpoint.hydrate import (
        _synthesize_trailing_checkpoint_event,
    )

    sample_dir = tmp_path / "1__0"
    sample_dir.mkdir()
    sidecar = CheckpointDetails(
        checkpoint_id=7,
        trigger="turn",
        turn=42,
        created_at=datetime(2026, 5, 17, 18, 0, tzinfo=timezone.utc),
        duration_ms=123,
        size_bytes=456,
        host=SnapshotDetails(snapshot_id="abc", size_bytes=456, duration_ms=100),
        sandboxes={},
    )
    (sample_dir / "ckpt-00007.json").write_text(sidecar.model_dump_json())

    event = _synthesize_trailing_checkpoint_event(str(sample_dir), 7)

    assert isinstance(event, CheckpointEvent)
    assert event.checkpoint_id == 7
    assert event.trigger == "turn"
    assert event.turn == 42
    assert event.host.snapshot_id == "abc"
    # Synthesized event's timestamp matches the sidecar's original
    # creation time — indistinguishable from a live emit.
    assert event.timestamp == sidecar.created_at


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
        "inspect_ai.util._checkpoint._layout.working_dir.inspect_cache_dir",
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


async def test_fire_writes_sample_json_and_sidecars(
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
    assert (sample_dir / "sample.json").is_file()
    sidecars = sorted(p.name for p in sample_dir.glob("ckpt-*.json"))
    assert sidecars == ["ckpt-00001.json", "ckpt-00002.json"]

    sample_working = tmp_path / "cache/checkpoints/test/s7__2"
    assert sample_working.is_dir()
    assert (sample_working / "events.json").is_file()
    assert (sample_working / "events_data.json").is_file()
    assert (sample_working / "attachments.json").is_file()
    assert (sample_working / "store.json").is_file()


# === _write_host_context: condensed events round-trip =======================


def _wrap_in_checkpoint_span(checkpoint_id: int, events: list[Event]) -> list[Event]:
    """Wrap a list of events in `span_begin/span_end` of type "checkpoint".

    `_write_host_context`'s filter (`_filter_persisted_events`) keeps only
    events inside checkpoint / prior_run spans + CheckpointEvents. Tests
    that drive `_write_host_context` directly with raw events need to
    bracket them so they survive the filter.
    """
    span_id = f"test-ckpt-{checkpoint_id}"
    return [
        SpanBeginEvent(
            id=span_id, name=f"checkpoint {checkpoint_id}", type="checkpoint"
        ),
        *events,
        SpanEndEvent(id=span_id),
    ]


async def test_write_host_context_condenses_and_round_trips(tmp_path: Path) -> None:
    """Pooled ModelEvent inputs round-trip via expand_events; pool < total slots."""
    msg_sys: ChatMessage = ChatMessageSystem(content="sys")
    msg_u1: ChatMessage = ChatMessageUser(content="q1")
    msg_a1: ChatMessage = ChatMessageAssistant(content="a1")
    msg_u2: ChatMessage = ChatMessageUser(content="q2")
    msg_a2: ChatMessage = ChatMessageAssistant(content="a2")
    messages: list[ChatMessage] = [msg_sys, msg_u1, msg_a1, msg_u2, msg_a2]

    def _model_event(input_msgs: list[ChatMessage]) -> ModelEvent:
        return ModelEvent(
            model="test",
            input=input_msgs,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(),
        )

    # Each ModelEvent carries the full prior history — 2 + 4 + 5 = 11 input
    # slots across 5 unique messages. Wrapped in a checkpoint span so the
    # write_host_context filter keeps them.
    events: list[Event] = _wrap_in_checkpoint_span(
        1,
        [
            _model_event([msg_sys, msg_u1]),
            _model_event([msg_sys, msg_u1, msg_a1, msg_u2]),
            _model_event(messages),
        ],
    )

    work = tmp_path / "work"
    work.mkdir()
    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration("/tmp/cp-test/ckpts", "/tmp/cp-test/work"),
        resume_checkpoint=None,
    )
    cp._events_consumed = 0
    await cp._write_host_context(str(work), events, {}, Store())

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
    base = Path("/tmp/cp-test")
    defaults: dict[str, object] = {
        "config": ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        "hydration": _fake_hydration(str(base / "ckpts"), str(base / "work")),
        "resume_checkpoint": None,
    }
    defaults.update(kwargs)
    cp = _EnteredCheckpointer(**defaults)  # type: ignore[arg-type]
    # In real use, `_events_consumed` is set lazily by the first
    # `_open_next_span()` call. Tests bypass that by driving
    # `_write_host_context` directly, so seed the precondition here.
    cp._events_consumed = 0
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


async def test_track_single_key_writes_file(tmp_path: Path) -> None:
    """Registered callback's return value lands in agent_state.json."""
    work = tmp_path / "work"
    work.mkdir()
    cp = _make_cp()
    value = 3
    cp.track("attempt_count", lambda: value, 0)
    await cp._write_host_context(str(work), [], {}, Store())
    assert json.loads((work / "agent_state.json").read_text()) == {"attempt_count": 3}


async def test_track_messages_via_track(tmp_path: Path) -> None:
    """Messages persist via `track('messages', ...)` — Pydantic model lists serialize."""
    work = tmp_path / "work"
    work.mkdir()
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
    await cp._write_host_context(str(work), [], {}, Store())

    state = json.loads((work / "agent_state.json").read_text())
    assert "messages" in state
    assert [m["role"] for m in state["messages"]] == ["system", "user"]
    assert [m["content"] for m in state["messages"]] == ["sys", "hi"]


async def test_track_multiple_keys_merge(tmp_path: Path) -> None:
    """Multiple registered keys merge into one top-level dict."""
    work = tmp_path / "work"
    work.mkdir()
    cp = _make_cp()
    cp.track("attempt_count", lambda: 3, 0)
    cp.track("phase", lambda: "explore", "")
    await cp._write_host_context(str(work), [], {}, Store())
    assert json.loads((work / "agent_state.json").read_text()) == {
        "attempt_count": 3,
        "phase": "explore",
    }


async def test_track_not_registered_no_file(tmp_path: Path) -> None:
    """Without any callback, agent_state.json is not written."""
    work = tmp_path / "work"
    work.mkdir()
    cp = _make_cp()
    await cp._write_host_context(str(work), [], {}, Store())
    assert not (work / "agent_state.json").exists()


def test_track_noop_session() -> None:
    """`_NoopCheckpointer.track()` returns initial_value and never registers."""
    cp = _NoopCheckpointer()
    out = cp.track("attempt_count", lambda: 42, 0)
    assert out == 0


def test_is_resuming_noop_false() -> None:
    assert _NoopCheckpointer().is_resuming is False


def test_is_resuming_reflects_resume_checkpoint() -> None:
    from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint

    assert _make_cp().is_resuming is False
    assert (
        _make_cp(
            resume_checkpoint=ResumeCheckpoint(sample_checkpoints_dir="/x"),
        ).is_resuming
        is True
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

    fake_env = MagicMock()
    fake_sample_state = MagicMock(restic_password="pwd")

    with (
        patch(
            "inspect_ai.util._checkpoint.hydrate.ensure_sample_checkpoints_dir",
            new=AsyncMock(return_value=str(tmp_path / "ckpts" / "s__0")),
        ) as ensure_ckpt,
        patch(
            "inspect_ai.util._checkpoint.hydrate.ensure_sample_working_dir",
            new=AsyncMock(return_value=str(tmp_path / "work" / "s__0")),
        ) as ensure_work,
        patch(
            "inspect_ai.util._checkpoint.hydrate.ensure_sample_json",
            new=AsyncMock(return_value=fake_sample_state),
        ) as ensure_sample_json_mock,
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
        # construction did NOT touch any I/O
        for m in (
            ensure_ckpt,
            ensure_work,
            ensure_sample_json_mock,
            resolve,
            init_host,
            get_sandbox,
            inject,
            init_sandbox,
        ):
            m.assert_not_called()

        async with setup as cp:
            assert isinstance(cp, _EnteredCheckpointer)
            # __aenter__ ran every I/O step exactly once
            ensure_ckpt.assert_awaited_once()
            ensure_work.assert_awaited_once()
            ensure_sample_json_mock.assert_awaited_once()
            resolve.assert_awaited_once()
            init_host.assert_awaited_once()
            get_sandbox.assert_called_once_with("web")
            inject.assert_awaited_once_with(fake_env)
            init_sandbox.assert_awaited_once_with(fake_env, "pwd")

        # re-entering returns the cached _CheckpointerSetup — no extra I/O calls
        async with setup as cp2:
            assert cp2 is cp
            ensure_ckpt.assert_awaited_once()
            init_sandbox.assert_awaited_once()


async def test_write_host_context_persists_attachments(tmp_path: Path) -> None:
    """transcript.attachments survives the checkpoint as attachments.json."""
    attachments = {"abc123": "data:image/png;base64,iVBORw0", "def456": "long-text"}

    work = tmp_path / "work"
    work.mkdir()
    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration("/tmp/cp-test/ckpts", "/tmp/cp-test/work"),
        resume_checkpoint=None,
    )
    cp._events_consumed = 0
    await cp._write_host_context(str(work), [], attachments, Store())

    assert json.loads((work / "attachments.json").read_text()) == attachments


async def test_write_host_context_accumulates_across_fires(tmp_path: Path) -> None:
    """Each fire processes only the new event slice; pool + events grow append-only."""
    msg_sys: ChatMessage = ChatMessageSystem(content="sys")
    msg_u1: ChatMessage = ChatMessageUser(content="q1")
    msg_a1: ChatMessage = ChatMessageAssistant(content="a1")
    msg_u2: ChatMessage = ChatMessageUser(content="q2")

    def _model_event(input_msgs: list[ChatMessage]) -> ModelEvent:
        return ModelEvent(
            model="test",
            input=input_msgs,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(),
        )

    # Each fire's events wrapped in a checkpoint span so the
    # write_host_context filter keeps them.
    fire1_events: list[Event] = _wrap_in_checkpoint_span(
        1,
        [
            _model_event([msg_sys, msg_u1]),
            _model_event([msg_sys, msg_u1, msg_a1]),
        ],
    )
    # Fire 2 cumulatively contains fire 1's events + a new checkpoint span
    # with one more model event. The two prior events stay condensed-as-is.
    fire2_events: list[Event] = [
        *fire1_events,
        *_wrap_in_checkpoint_span(2, [_model_event([msg_sys, msg_u1, msg_a1, msg_u2])]),
    ]

    work = tmp_path / "work"
    work.mkdir()
    cp = _EnteredCheckpointer(
        config=ResolvedCheckpointConfig(trigger=TurnInterval(every=1)),
        hydration=_fake_hydration("/tmp/cp-test/ckpts", "/tmp/cp-test/work"),
        resume_checkpoint=None,
    )
    cp._events_consumed = 0

    await cp._write_host_context(str(work), fire1_events, {}, Store())
    pool_after_1 = json.loads((work / "events_data.json").read_text())["messages"]
    events_after_1 = json.loads((work / "events.json").read_text())
    assert len(pool_after_1) == 3  # sys, u1, a1
    # Fire 1's persisted events: [span_begin_1, model_1, model_2, span_end_1].
    assert len(events_after_1) == 4
    assert cp._events_consumed == len(fire1_events)

    await cp._write_host_context(str(work), fire2_events, {}, Store())
    pool_after_2 = json.loads((work / "events_data.json").read_text())["messages"]
    events_after_2 = json.loads((work / "events.json").read_text())
    # Append-only: pool grew by exactly one (u2); first 3 entries unchanged.
    assert pool_after_2[:3] == pool_after_1
    assert len(pool_after_2) == 4
    # Events grew by 3 (span_begin_2 + model_3 + span_end_2 = checkpoint 2's
    # wrap); the first 4 are byte-identical to fire 1's persisted output.
    assert events_after_2[:4] == events_after_1
    assert len(events_after_2) == 7
    assert cp._events_consumed == len(fire2_events)

    # Full round-trip still works on the cumulative output.
    expanded = expand_events(
        (work / "events.json").read_text(),
        (work / "events_data.json").read_text(),
    )
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert [len(e.input) for e in model_events] == [2, 3, 4]
