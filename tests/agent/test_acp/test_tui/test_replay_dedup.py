"""Replay-dedup regression tests for Phase 6.

On reconnect the server's ``session/load`` rebind runs the standard
replay-on-attach flow (per ``agent-acp.md`` Phase 10), which re-streams
the last 100 events to the now-reconnected client. The client has
already processed those events for the pre-disconnect period; without
dedup the re-streamed chunks would double the rendered text and the
re-streamed score / span events would mount duplicate chips.

Mechanism: server stamps :data:`REPLAY_META_KEY` on the outer
``SessionNotification.field_meta`` for every replay notification.
Client tracks ``_replay_reset_message_ids`` (set cleared by
:meth:`SessionState.mark_replay_started` at each session/load); on
chunk arrival with the marker, the FIRST chunk per message_id resets
segments, subsequent chunks append normally. Works for ALL chunk types
(assistant content, reasoning, user, system) since the marker is on
the outer notification.

Tested invariants:

- Assistant content-only message (no completion marker) doesn't double.
- Assistant chunked content (3 chunks + completion) doesn't double.
- Mid-flight assistant message doesn't double.
- User chunk doesn't double.
- System chunk doesn't double.
- ``mark_replay_started`` clears the per-replay set so subsequent
  reconnects get a fresh dedup pass.
- Replay marker on an unrelated message_id doesn't affect other groups.
- ``consume_inspect_event``: raw event uuid dedup (separate mechanism,
  uses ``BaseEvent.uuid`` directly).
- Regression: tool calls, plan updates, score chips already idempotent.
"""

from __future__ import annotations

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    PlanEntry,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)

from inspect_ai.agent._acp.inspect_ext import (
    MESSAGE_ROLE_META_KEY,
    MODEL_EVENT_COMPLETE_META_KEY,
    MODEL_EVENT_PENDING_META_KEY,
    REPLAY_META_KEY,
)
from inspect_ai.agent._acp.tui.state import (
    MessageGroup,
    ScoreChip,
    SessionState,
    ToolCallState,
)

# ---------------------------------------------------------------------------
# Helpers — outer ``field_meta`` carries the REPLAY marker (matches the
# wire shape produced by ``Forwarders._stamp_replay_marker``).
# ---------------------------------------------------------------------------


def _agent_chunk(
    text: str,
    *,
    message_id: str = "m1",
    pending: bool = False,
    complete: bool = False,
    is_replay: bool = False,
) -> SessionNotification:
    meta: dict[str, object] = {}
    if pending:
        meta[MODEL_EVENT_PENDING_META_KEY] = True
    if complete:
        meta[MODEL_EVENT_COMPLETE_META_KEY] = True
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta=meta or None,
    )
    outer_meta = {REPLAY_META_KEY: True} if is_replay else None
    return SessionNotification(session_id="sid", update=chunk, field_meta=outer_meta)


def _user_chunk(
    text: str,
    *,
    message_id: str = "u1",
    is_replay: bool = False,
) -> SessionNotification:
    chunk = UserMessageChunk(
        session_update="user_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
    )
    outer_meta = {REPLAY_META_KEY: True} if is_replay else None
    return SessionNotification(session_id="sid", update=chunk, field_meta=outer_meta)


def _system_chunk(
    text: str,
    *,
    message_id: str = "s1",
    is_replay: bool = False,
) -> SessionNotification:
    # The server routes SYSTEM messages through UserMessageChunk with
    # an inner ``inspect.message_role = "system"`` marker — ACP has no
    # native system role.
    chunk = UserMessageChunk(
        session_update="user_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta={MESSAGE_ROLE_META_KEY: "system"},
    )
    outer_meta = {REPLAY_META_KEY: True} if is_replay else None
    return SessionNotification(session_id="sid", update=chunk, field_meta=outer_meta)


def _tool_start(tool_call_id: str = "tc-1") -> SessionNotification:
    start = ToolCallStart(
        session_update="tool_call",
        tool_call_id=tool_call_id,
        title="bash ls",
        status="in_progress",
        raw_input={"command": "ls"},
    )
    return SessionNotification(session_id="sid", update=start)


def _tool_progress(
    tool_call_id: str = "tc-1", *, status: str = "completed"
) -> SessionNotification:
    prog = ToolCallProgress(
        session_update="tool_call_update",
        tool_call_id=tool_call_id,
        status=status,  # type: ignore[arg-type]
        raw_output="ok",
    )
    return SessionNotification(session_id="sid", update=prog)


def _plan_update(entries: list[tuple[str, str]]) -> SessionNotification:
    plan = AgentPlanUpdate(
        session_update="plan",
        entries=[
            PlanEntry(content=content, status=status, priority="medium")  # type: ignore[arg-type]
            for content, status in entries
        ],
    )
    return SessionNotification(session_id="sid", update=plan)


def _score_event(uuid: str, *, value: str = "C", scorer: str = "match") -> dict:
    return {
        "event": "score",
        "uuid": uuid,
        "timestamp": "2024-01-01T00:00:00Z",
        "scorer": scorer,
        "score": {"value": value, "explanation": "ok"},
    }


def _span_begin(uuid: str, span_id: str, name: str, span_type: str) -> dict:
    return {
        "event": "span_begin",
        "uuid": uuid,
        "id": span_id,
        "name": name,
        "type": span_type,
    }


# ---------------------------------------------------------------------------
# Chunk replay — assistant content (the common case the reviewer flagged)
# ---------------------------------------------------------------------------


def test_assistant_content_only_replay_does_not_double() -> None:
    """Content-only assistant replay (no completion marker) — the reviewer's case.

    The mapper only emits ``inspect.model_event_complete`` on the
    no-content / tool-only path; normal assistant text replays
    arrive WITHOUT it, so a heuristic based on the completion marker
    would miss this case. The explicit replay marker covers it.
    """
    state = SessionState()
    # Live: simple content delivery, no completion marker (mapper
    # doesn't emit one for content-producing messages).
    state.consume(_agent_chunk("Hello", message_id="m1"))
    assert state._messages_by_id["m1"].text == "Hello"

    # Reconnect → server replays the snapshot.
    state.mark_replay_started()
    state.consume(_agent_chunk("Hello", message_id="m1", is_replay=True))
    # Single delivery shape, not "HelloHello".
    assert state._messages_by_id["m1"].text == "Hello"


def test_assistant_chunked_content_replay_does_not_double() -> None:
    """Multi-chunk assistant content replay rebuilds cleanly across all chunks.

    Live: three content chunks. Replay: same three chunks. Without
    dedup the text would double; with the per-message_id reset on
    the first replay chunk, all three rebuild against an empty
    segment.
    """
    state = SessionState()
    state.consume(_agent_chunk("Hel", message_id="m1"))
    state.consume(_agent_chunk("lo ", message_id="m1"))
    state.consume(_agent_chunk("world", message_id="m1"))
    assert state._messages_by_id["m1"].text == "Hello world"

    state.mark_replay_started()
    state.consume(_agent_chunk("Hel", message_id="m1", is_replay=True))
    # First replay chunk reset segments, then appended "Hel".
    assert state._messages_by_id["m1"].text == "Hel"
    state.consume(_agent_chunk("lo ", message_id="m1", is_replay=True))
    assert state._messages_by_id["m1"].text == "Hello "
    state.consume(_agent_chunk("world", message_id="m1", is_replay=True))
    # Rebuilt to single-delivery shape.
    assert state._messages_by_id["m1"].text == "Hello world"


def test_user_chunk_replay_does_not_double() -> None:
    """User message replay — the reviewer's other example case."""
    state = SessionState()
    state.consume(_user_chunk("Question", message_id="u1"))
    assert state._messages_by_id["u1"].text == "Question"

    state.mark_replay_started()
    state.consume(_user_chunk("Question", message_id="u1", is_replay=True))
    # Single delivery shape, not "QuestionQuestion".
    assert state._messages_by_id["u1"].text == "Question"


def test_system_chunk_replay_does_not_double() -> None:
    """System message replay (routed through UserMessageChunk + meta)."""
    state = SessionState()
    state.consume(_system_chunk("System prompt", message_id="s1"))
    assert state._messages_by_id["s1"].text == "System prompt"

    state.mark_replay_started()
    state.consume(_system_chunk("System prompt", message_id="s1", is_replay=True))
    assert state._messages_by_id["s1"].text == "System prompt"


def test_replay_with_completion_marker_path_still_works() -> None:
    """Tool-only / no-content path (mapper DOES emit completion marker).

    The marker handling is unchanged by the new dedup mechanism;
    pending/complete state still flips correctly on replay. This
    test pins that contract.
    """
    state = SessionState()
    # Live: empty pending then completion (no content — tool-only ModelEvent).
    state.consume(_agent_chunk("", message_id="m1", pending=True))
    state.consume(_agent_chunk("", message_id="m1", complete=True))
    assert state._messages_by_id["m1"].pending is False

    # Replay.
    state.mark_replay_started()
    state.consume(_agent_chunk("", message_id="m1", pending=True, is_replay=True))
    # Segments stay empty (replay reset on first chunk; chunk was empty content).
    assert state._messages_by_id["m1"].text == ""
    state.consume(_agent_chunk("", message_id="m1", complete=True, is_replay=True))
    # Pending cleared by the completion marker.
    assert state._messages_by_id["m1"].pending is False


def test_replay_marker_required_for_dedup_trigger() -> None:
    """Without the replay marker, a chunk for an existing id appends as normal.

    This guards against a regression where dedup fires on live
    forwarding (which would lose content during retries / aliased
    chunks).
    """
    state = SessionState()
    state.consume(_agent_chunk("first", message_id="m1"))
    # Second non-replay chunk for the same id — should append, not reset.
    # (Live wouldn't typically do this, but the test pins the contract.)
    state.consume(_agent_chunk(" continued", message_id="m1"))
    assert state._messages_by_id["m1"].text == "first continued"


def test_replay_only_resets_once_per_message_id_per_replay() -> None:
    """First replay chunk for an id resets; subsequent chunks append."""
    state = SessionState()
    state.consume(_agent_chunk("Hello world", message_id="m1"))

    state.mark_replay_started()
    state.consume(_agent_chunk("Hel", message_id="m1", is_replay=True))
    state.consume(_agent_chunk("lo ", message_id="m1", is_replay=True))
    state.consume(_agent_chunk("world", message_id="m1", is_replay=True))
    assert state._messages_by_id["m1"].text == "Hello world"
    # Confirm the id was tracked.
    assert "m1" in state._replay_reset_message_ids


def test_mark_replay_started_clears_set_for_next_reconnect() -> None:
    """Each reconnect must reset the per-replay tracking afresh."""
    state = SessionState()
    state.consume(_agent_chunk("Hello", message_id="m1"))

    # First reconnect.
    state.mark_replay_started()
    state.consume(_agent_chunk("Hello", message_id="m1", is_replay=True))
    assert "m1" in state._replay_reset_message_ids

    # Second reconnect — the tracking set must be cleared so m1's
    # next replay chunk resets again.
    state.mark_replay_started()
    assert state._replay_reset_message_ids == set()
    state.consume(_agent_chunk("Hello", message_id="m1", is_replay=True))
    assert state._messages_by_id["m1"].text == "Hello"


def test_replay_does_not_affect_unrelated_messages() -> None:
    """Replay of m1 must not touch m2's segments."""
    state = SessionState()
    state.consume(_agent_chunk("from-m1", message_id="m1"))
    state.consume(_agent_chunk("from-m2", message_id="m2"))

    state.mark_replay_started()
    state.consume(_agent_chunk("from-m1", message_id="m1", is_replay=True))
    assert state._messages_by_id["m1"].text == "from-m1"
    # m2 untouched.
    assert state._messages_by_id["m2"].text == "from-m2"


def test_replay_does_not_affect_new_messages() -> None:
    """A brand-new message_id replays into a fresh group (no prior to reset)."""
    state = SessionState()
    state.consume(_agent_chunk("first", message_id="m1"))

    state.mark_replay_started()
    # New message in replay — should create a fresh group.
    state.consume(_agent_chunk("brand-new", message_id="m2", is_replay=True))
    groups = [i for i in state.items if isinstance(i, MessageGroup)]
    assert len(groups) == 2
    assert groups[0].text == "first"
    assert groups[1].text == "brand-new"


# ---------------------------------------------------------------------------
# Raw inspect event replay (separate uuid-based mechanism)
# ---------------------------------------------------------------------------


def test_raw_event_with_seen_uuid_is_silently_dropped() -> None:
    """A score event with a previously-processed uuid produces no second chip."""
    state = SessionState()
    state.consume_inspect_event(_score_event("score-uuid-1"))
    chips = [i for i in state.items if isinstance(i, ScoreChip)]
    assert len(chips) == 1
    # Replay — same uuid arrives again.
    state.consume_inspect_event(_score_event("score-uuid-1"))
    chips = [i for i in state.items if isinstance(i, ScoreChip)]
    assert len(chips) == 1, "duplicate score event must not double-mount"


def test_raw_event_with_new_uuid_after_replay_still_processes() -> None:
    """The dedup set doesn't block legitimate new events sharing scorer name."""
    state = SessionState()
    state.consume_inspect_event(_score_event("uuid-A", scorer="match"))
    state.consume_inspect_event(_score_event("uuid-A"))  # replay drop
    state.consume_inspect_event(_score_event("uuid-B", scorer="match"))  # NEW
    chips = [i for i in state.items if isinstance(i, ScoreChip)]
    assert len(chips) == 2


def test_raw_event_without_uuid_is_processed_unconditionally() -> None:
    """Defensive: events lacking a uuid skip the dedup check.

    Wire events should always carry a uuid (``BaseEvent.uuid`` is
    not Optional), but if a malformed payload lands we'd rather
    over-process than silently swallow it.
    """
    state = SessionState()
    no_uuid = {
        "event": "score",
        "timestamp": "2024-01-01T00:00:00Z",
        "scorer": "match",
        "score": {"value": "C", "explanation": "ok"},
    }
    state.consume_inspect_event(no_uuid)
    state.consume_inspect_event(no_uuid)
    chips = [i for i in state.items if isinstance(i, ScoreChip)]
    # Both processed — fail-open rather than fail-silent.
    assert len(chips) == 2


def test_span_begin_replay_does_not_remount_indicator() -> None:
    """Per-scorer indicator must not duplicate when its begin event replays."""
    state = SessionState()
    # First span_begin mounts an indicator.
    state.consume_inspect_event(
        _span_begin(
            uuid="span-begin-1", span_id="span-1", name="match", span_type="scorer"
        )
    )
    assert state._scoring_indicator is not None
    # Replay the same span_begin — should be a no-op (dedup by uuid).
    state.consume_inspect_event(
        _span_begin(
            uuid="span-begin-1", span_id="span-1", name="match", span_type="scorer"
        )
    )
    # Still exactly one indicator (the original, not a remount).
    scoring_chips = [
        i for i in state.items if isinstance(i, ScoreChip) and i.span_id == "span-1"
    ]
    assert len(scoring_chips) == 1


# ---------------------------------------------------------------------------
# Regression: id-keyed paths are already idempotent
# ---------------------------------------------------------------------------


def test_tool_call_replay_is_already_idempotent() -> None:
    """Replaying ``tool_call_start`` for an existing tool id updates in place."""
    state = SessionState()
    state.consume(_tool_start("tc-1"))
    state.consume(_tool_progress("tc-1", status="completed"))
    assert "tc-1" in state._tool_calls_by_id
    tc_before = state._tool_calls_by_id["tc-1"]
    assert tc_before.status == "completed"

    # Replay.
    state.consume(_tool_start("tc-1"))
    state.consume(_tool_progress("tc-1", status="completed"))

    # Same single entry; no duplicates.
    tools = [i for i in state.items if isinstance(i, ToolCallState)]
    assert len(tools) == 1
    assert tools[0].tool_call_id == "tc-1"


def test_plan_update_replay_is_full_replacement() -> None:
    """AgentPlanUpdate is a full replacement; replay just overwrites."""
    state = SessionState()
    state.consume(_plan_update([("step1", "pending"), ("step2", "in_progress")]))
    assert state.plan_entries is not None
    assert len(state.plan_entries) == 2

    # Replay.
    state.consume(_plan_update([("step1", "pending"), ("step2", "in_progress")]))
    assert state.plan_entries is not None
    assert len(state.plan_entries) == 2
    contents = [e.content for e in state.plan_entries]
    assert contents == ["step1", "step2"]
