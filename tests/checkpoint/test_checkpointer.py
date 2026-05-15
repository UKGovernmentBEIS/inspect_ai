"""Policy + outer-facade tests for the checkpointer.

The policy tests drive ``_Checkpointer`` directly with prepared dirs
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

from inspect_ai.event._model import ModelEvent
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
    CheckpointConfig,
    TimeInterval,
    TurnInterval,
    checkpointer,
)
from inspect_ai.util._checkpoint.checkpointer import _NoopCheckpointer
from inspect_ai.util._checkpoint.checkpointer_impl import _Checkpointer
from inspect_ai.util._checkpoint.layout import CheckpointTriggerKind
from inspect_ai.util._checkpoint.restic import ResticBackupSummary
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


@contextmanager
def _patch_sample_runtime() -> Iterator[None]:
    """Patch sample_state() and transcript() for tests that drive _fire.

    `_Checkpointer._fire` reads ``sample_state().store`` and
    ``transcript().events`` directly from ContextVars. Tests that
    construct `_Checkpointer` outside a real sample run need stand-ins.
    """
    from types import SimpleNamespace

    from inspect_ai.util._store import Store

    fake_state = SimpleNamespace(store=Store())
    fake_transcript = SimpleNamespace(events=[], attachments={})
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
    with _patch_sample_runtime():
        yield _Dirs(checkpoints=str(checkpoints), working=str(working))


class _CountingCheckpointer(_Checkpointer):
    """Counts fires on top of the real fire path; stubs out restic."""

    fire_count: int = 0

    async def _fire(self, trigger: CheckpointTriggerKind) -> None:
        await super()._fire(trigger)
        self.fire_count += 1

    async def _backup_host(self) -> ResticBackupSummary:
        return _fake_summary(self._next_checkpoint_id)


def _counting(config: CheckpointConfig, dirs: _Dirs) -> _CountingCheckpointer:
    cp = _CountingCheckpointer(
        config=config,
        log_location="/tmp/t.eval",
        sample_id="s",
        epoch=0,
        eval_id="e",
    )
    # Bypass __aenter__: pre-seed the I/O-derived state that the fire
    # path reads. Tests drive cp.tick()/cp.checkpoint() directly without
    # going through the async ctx mgr.
    from inspect_ai.util._checkpoint.checkpointer_impl import _LiveState

    cp._live = _LiveState(
        sample_checkpoints_dir=dirs.checkpoints,
        sample_working_dir=dirs.working,
        host_restic=Path("/fake/restic"),
        host_repo=f"{dirs.checkpoints}/host",
        restic_password="test-pwd",
    )
    return cp


# --- turn-based -----------------------------------------------------------


async def test_turn_interval_fires_at_each_threshold(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(trigger=TurnInterval(every=3)), dirs)
    for _ in range(9):
        await cp.tick()
    assert cp.fire_count == 3


async def test_turn_interval_resets_counter_on_fire(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(trigger=TurnInterval(every=4)), dirs)
    for _ in range(3):
        await cp.tick()
    assert cp.fire_count == 0
    await cp.tick()
    assert cp.fire_count == 1
    # counter reset; next fire requires another 4 ticks
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
            CheckpointConfig(trigger=TimeInterval(every=timedelta(seconds=10))), dirs
        )
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


# --- manual ---------------------------------------------------------------


async def test_manual_policy_tick_never_fires(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(trigger="manual"), dirs)
    for _ in range(50):
        await cp.tick()
    assert cp.fire_count == 0


async def test_checkpoint_method_fires(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(trigger="manual"), dirs)
    await cp.tick()
    await cp.checkpoint()
    await cp.checkpoint()
    assert cp.fire_count == 2


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
    checkpoint: CheckpointConfig | None = None
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
        "inspect_ai.util._checkpoint.working_dir.inspect_cache_dir",
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

    async def fake_init_host_repo(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_run_host_backup(
        *_args: object, **_kwargs: object
    ) -> ResticBackupSummary:
        return _fake_summary(checkpoint_id=1)

    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.resolve_restic",
            side_effect=fake_resolve,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.init_host_repo",
            side_effect=fake_init_host_repo,
        ),
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.run_host_backup",
            side_effect=fake_run_host_backup,
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
        _patch_sample_runtime(),
        _patch_checkpointing_enabled(),
    ):
        yield fake


# --- disabled (None config) -----------------------------------------------


async def test_none_config_works_without_active_sample() -> None:
    """`checkpointer()` with no ambient config yields a no-op session."""
    with _patch_sample_active(None):
        async with checkpointer() as cp:
            for _ in range(5):
                await cp.tick()
            await cp.checkpoint()


# --- no active sample → no-op ---------------------------------------------


async def test_aenter_without_active_sample_noops() -> None:
    """No ActiveSample means no checkpointing — `checkpointer()` is a no-op."""
    with _patch_sample_active(None):
        async with checkpointer() as cp:
            for _ in range(5):
                await cp.tick()
            await cp.checkpoint()


# === e2e: outer facade through to disk =====================================


async def test_fire_writes_manifest_and_sidecars(
    active_sample: _FakeActiveSample, tmp_path: Path
) -> None:
    """Driving the outer checkpointer end-to-end writes destination + working tree."""
    active_sample.sample.id = "s7"
    active_sample.epoch = 2
    active_sample.checkpoint = CheckpointConfig(trigger=TurnInterval(every=2))

    # Inject a real checkpointer into the fake, mirroring what
    # `task_run_sample` does in production before opening `active_sample`.
    from inspect_ai.util._checkpoint.checkpointer_impl import build_impl

    assert active_sample.sample.id is not None
    assert active_sample.eval_id is not None
    active_sample.checkpointer = build_impl(
        config=active_sample.checkpoint,
        log_location=active_sample.log_location,
        sample_id=active_sample.sample.id,
        epoch=active_sample.epoch,
        eval_id=active_sample.eval_id,
    )

    async with checkpointer() as cp:
        await cp.tick()  # turn 1, no fire
        await cp.tick()  # turn 2, fires
        await cp.tick()  # turn 3, no fire
        await cp.tick()  # turn 4, fires

    log = Path(active_sample.log_location)
    eval_dir = log.parent / f"{log.stem}.checkpoints"
    assert (eval_dir / "manifest.json").is_file()
    sample_dir = eval_dir / "s7__2"
    sidecars = sorted(p.name for p in sample_dir.glob("ckpt-*.json"))
    assert sidecars == ["ckpt-00001.json", "ckpt-00002.json"]

    sample_working = tmp_path / "cache/checkpoints/test/s7__2"
    assert sample_working.is_dir()
    assert (sample_working / "events.json").is_file()
    assert (sample_working / "events_data.json").is_file()
    assert (sample_working / "attachments.json").is_file()
    assert (sample_working / "store.json").is_file()


# === _write_host_context: condensed events round-trip =======================


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

    # Each event carries the full prior history — 2 + 4 + 5 = 11 input slots
    # across 5 unique messages.
    events = [
        _model_event([msg_sys, msg_u1]),
        _model_event([msg_sys, msg_u1, msg_a1, msg_u2]),
        _model_event(messages),
    ]

    work = tmp_path / "work"
    work.mkdir()
    cp = _Checkpointer(
        config=CheckpointConfig(trigger=TurnInterval(every=1)),
        log_location="/tmp/t.eval",
        sample_id="s",
        epoch=0,
        eval_id="e",
    )
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


def _make_cp(**kwargs: object) -> _Checkpointer:
    return _Checkpointer(
        config=CheckpointConfig(trigger=TurnInterval(every=1)),
        log_location="/tmp/t.eval",
        sample_id="s",
        epoch=0,
        eval_id="e",
        **kwargs,  # type: ignore[arg-type]
    )


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
    cp.track("messages", lambda: messages, messages)
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


async def test_aenter_defers_io_setup(tmp_path: Path) -> None:
    """All I/O setup (incl. sandbox loop) runs in __aenter__, not __init__."""
    from unittest.mock import AsyncMock, MagicMock

    cp = _Checkpointer(
        config=CheckpointConfig(
            trigger=TurnInterval(every=1),
            sandbox_paths={"web": ["/var/www"]},
        ),
        log_location=str(tmp_path / "t.eval"),
        sample_id="s",
        epoch=0,
        eval_id="e",
    )

    fake_env = MagicMock()
    fake_manifest = MagicMock(restic_password="pwd")

    with (
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.ensure_sample_checkpoints_dir",
            new=AsyncMock(return_value=str(tmp_path / "ckpts" / "s__0")),
        ) as ensure_ckpt,
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.ensure_sample_working_dir",
            new=AsyncMock(return_value=str(tmp_path / "work" / "s__0")),
        ) as ensure_work,
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.read_eval_manifest",
            new=AsyncMock(return_value=fake_manifest),
        ) as read_manifest,
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.resolve_restic",
            new=AsyncMock(return_value=Path("/fake/restic")),
        ) as resolve,
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.init_host_repo",
            new=AsyncMock(),
        ) as init_host,
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.sandbox",
            return_value=fake_env,
        ) as get_sandbox,
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.inject_restic",
            new=AsyncMock(),
        ) as inject,
        patch(
            "inspect_ai.util._checkpoint.checkpointer_impl.init_sandbox_repo",
            new=AsyncMock(),
        ) as init_sandbox,
    ):
        # construction did NOT touch any I/O
        for m in (
            ensure_ckpt,
            ensure_work,
            read_manifest,
            resolve,
            init_host,
            get_sandbox,
            inject,
            init_sandbox,
        ):
            m.assert_not_called()

        async with cp:
            # __aenter__ ran every I/O step exactly once
            ensure_ckpt.assert_awaited_once()
            ensure_work.assert_awaited_once()
            read_manifest.assert_awaited_once()
            resolve.assert_awaited_once()
            init_host.assert_awaited_once()
            get_sandbox.assert_called_once_with("web")
            inject.assert_awaited_once_with(fake_env)
            init_sandbox.assert_awaited_once_with(fake_env, "pwd")

        # re-entering is idempotent — no extra calls
        async with cp:
            ensure_ckpt.assert_awaited_once()
            init_sandbox.assert_awaited_once()


async def test_write_host_context_persists_attachments(tmp_path: Path) -> None:
    """transcript.attachments survives the checkpoint as attachments.json."""
    attachments = {"abc123": "data:image/png;base64,iVBORw0", "def456": "long-text"}

    work = tmp_path / "work"
    work.mkdir()
    cp = _Checkpointer(
        config=CheckpointConfig(trigger=TurnInterval(every=1)),
        log_location="/tmp/t.eval",
        sample_id="s",
        epoch=0,
        eval_id="e",
    )
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

    fire1_events = [
        _model_event([msg_sys, msg_u1]),
        _model_event([msg_sys, msg_u1, msg_a1]),
    ]
    # Fire 2 appends one more event; the prior two stay condensed-as-is.
    fire2_events = [*fire1_events, _model_event([msg_sys, msg_u1, msg_a1, msg_u2])]

    work = tmp_path / "work"
    work.mkdir()
    cp = _Checkpointer(
        config=CheckpointConfig(trigger=TurnInterval(every=1)),
        log_location="/tmp/t.eval",
        sample_id="s",
        epoch=0,
        eval_id="e",
    )

    await cp._write_host_context(str(work), fire1_events, {}, Store())
    pool_after_1 = json.loads((work / "events_data.json").read_text())["messages"]
    events_after_1 = json.loads((work / "events.json").read_text())
    assert len(pool_after_1) == 3  # sys, u1, a1
    assert len(events_after_1) == 2
    assert cp._events_consumed == 2

    await cp._write_host_context(str(work), fire2_events, {}, Store())
    pool_after_2 = json.loads((work / "events_data.json").read_text())["messages"]
    events_after_2 = json.loads((work / "events.json").read_text())
    # Append-only: pool grew by exactly one (u2); first 3 entries unchanged.
    assert pool_after_2[:3] == pool_after_1
    assert len(pool_after_2) == 4
    # Events grew by one; the first two are byte-identical to fire 1.
    assert events_after_2[:2] == events_after_1
    assert len(events_after_2) == 3
    assert cp._events_consumed == 3

    # Full round-trip still works on the cumulative output.
    expanded = expand_events(
        (work / "events.json").read_text(),
        (work / "events_data.json").read_text(),
    )
    model_events = [e for e in expanded if isinstance(e, ModelEvent)]
    assert [len(e.input) for e in model_events] == [2, 3, 4]
