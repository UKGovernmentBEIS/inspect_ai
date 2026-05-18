"""Tests for the Phase 2 TUI SessionState consumer.

Unit-level: feeds synthetic ACP notifications, asserts state shape and
derived signals. No event loop, no pilot.
"""

from __future__ import annotations

from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    ImageContentBlock,
    SessionInfoUpdate,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)

from inspect_ai.agent._acp.tui.state import (
    MessageGroup,
    Segment,
    SessionState,
    StatusState,
    ToolCallState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_chunk(
    text: str,
    *,
    message_id: str | None = "mid-1",
    model: str | None = "phase2/model",
) -> SessionNotification:
    meta: dict[str, str] = {}
    if model is not None:
        meta["inspect.model"] = model
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta=meta or None,
    )
    return SessionNotification(session_id="sid", update=chunk)


def _thought_chunk(
    text: str, *, message_id: str | None = "mid-1"
) -> SessionNotification:
    chunk = AgentThoughtChunk(
        session_update="agent_thought_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
    )
    return SessionNotification(session_id="sid", update=chunk)


def _user_chunk(text: str, *, message_id: str = "mu-1") -> SessionNotification:
    chunk = UserMessageChunk(
        session_update="user_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
    )
    return SessionNotification(session_id="sid", update=chunk)


def _tool_start(
    tool_call_id: str = "tc-1",
    *,
    title: str = "bash ls",
    status: str = "in_progress",
    raw_input: dict | None = None,
) -> SessionNotification:
    start = ToolCallStart(
        session_update="tool_call",
        tool_call_id=tool_call_id,
        title=title,
        status=status,  # type: ignore[arg-type]
        raw_input=raw_input or {"command": "ls"},
    )
    return SessionNotification(session_id="sid", update=start)


def _tool_progress(
    tool_call_id: str = "tc-1",
    *,
    status: str = "completed",
    raw_output: str | None = "ok",
) -> SessionNotification:
    prog = ToolCallProgress(
        session_update="tool_call_update",
        tool_call_id=tool_call_id,
        status=status,  # type: ignore[arg-type]
        raw_output=raw_output,
    )
    return SessionNotification(session_id="sid", update=prog)


def _usage(used: int, size: int) -> SessionNotification:
    upd = UsageUpdate(session_update="usage_update", used=used, size=size)
    return SessionNotification(session_id="sid", update=upd)


def _session_info(title: str | None) -> SessionNotification:
    upd = SessionInfoUpdate(session_update="session_info_update", title=title)
    return SessionNotification(session_id="sid", update=upd)


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---------------------------------------------------------------------------
# Chunk grouping
# ---------------------------------------------------------------------------


def test_chunks_with_same_message_id_concatenate_into_one_group() -> None:
    state = SessionState()
    state.consume(_agent_chunk("hello ", message_id="m1"))
    state.consume(_agent_chunk("world", message_id="m1"))
    assert len(state.items) == 1
    group = state.items[0]
    assert isinstance(group, MessageGroup)
    assert group.text == "hello world"
    assert group.role == "assistant"


def test_chunks_with_different_message_ids_create_separate_groups() -> None:
    state = SessionState()
    state.consume(_agent_chunk("first", message_id="m1"))
    state.consume(_agent_chunk("second", message_id="m2"))
    assert len(state.items) == 2
    groups = [i for i in state.items if isinstance(i, MessageGroup)]
    assert [g.text for g in groups] == ["first", "second"]


def test_missing_message_id_falls_back_to_per_chunk_isolation() -> None:
    """Pre-A1 servers emit chunks with no message_id.

    Without a grouping key we'd collapse unrelated content into one
    bubble. Fall back to one group per chunk so the display still
    makes sense.
    """
    state = SessionState()
    state.consume(_agent_chunk("a", message_id=None))
    state.consume(_agent_chunk("b", message_id=None))
    assert len(state.items) == 2


def test_user_chunks_render_as_user_role() -> None:
    state = SessionState()
    state.consume(_user_chunk("ping"))
    group = state.items[0]
    assert isinstance(group, MessageGroup)
    assert group.role == "user"


def test_thought_chunk_renders_as_assistant_with_reasoning_segment() -> None:
    """Reasoning is a SEGMENT KIND inside an assistant turn, not a top-level role."""
    state = SessionState()
    state.consume(_thought_chunk("hmm"))
    group = state.items[0]
    assert isinstance(group, MessageGroup)
    assert group.role == "assistant"
    assert group.segments == [Segment(kind="reasoning", text="hmm")]
    assert group.reasoning_text == "hmm"
    assert group.text == ""  # no text segment yet


def test_reasoning_and_text_with_same_message_id_are_one_group_with_two_segments() -> (
    None
):
    """Reviewer P1: thought + text chunks under one message_id stay grouped.

    AgentThoughtChunk + AgentMessageChunk from one ModelEvent share
    message_id (router A1). They must land in ONE assistant MessageGroup
    as separate segments, not collapse into one role-fixed bubble.
    """
    state = SessionState()
    state.consume(_thought_chunk("planning...", message_id="m1"))
    state.consume(_agent_chunk("here's the result", message_id="m1"))
    assert len(state.items) == 1
    group = state.items[0]
    assert isinstance(group, MessageGroup)
    assert group.role == "assistant"
    assert group.segments == [
        Segment(kind="reasoning", text="planning..."),
        Segment(kind="text", text="here's the result"),
    ]
    assert group.reasoning_text == "planning..."
    assert group.text == "here's the result"


def test_interleaved_reasoning_text_preserves_arrival_order() -> None:
    """Interleaved reasoning/text chunks render in arrival order.

    A real model can interleave: think → respond → think more → respond
    more. Segments must preserve that order so the renderer shows the
    real interleave.
    """
    state = SessionState()
    state.consume(_thought_chunk("plan: A", message_id="m1"))
    state.consume(_agent_chunk("answer A", message_id="m1"))
    state.consume(_thought_chunk("reconsidering...", message_id="m1"))
    state.consume(_agent_chunk("actually B", message_id="m1"))
    group = state.items[0]
    assert isinstance(group, MessageGroup)
    assert [s.kind for s in group.segments] == [
        "reasoning",
        "text",
        "reasoning",
        "text",
    ]
    assert [s.text for s in group.segments] == [
        "plan: A",
        "answer A",
        "reconsidering...",
        "actually B",
    ]


def test_adjacent_same_kind_chunks_extend_last_segment() -> None:
    """Adjacent same-kind chunks compact into a single segment.

    Multi-chunk streaming of the same kind compacts into one segment,
    not many small ones (cleaner for the renderer).
    """
    state = SessionState()
    state.consume(_agent_chunk("hello ", message_id="m1"))
    state.consume(_agent_chunk("world", message_id="m1"))
    group = state.items[0]
    assert isinstance(group, MessageGroup)
    assert group.segments == [Segment(kind="text", text="hello world")]


def test_picker_meta_chunks_are_suppressed() -> None:
    """Bind / picker confirmation notifications restate the meta row — drop them.

    The server sends a ``SessionNotification`` whose OUTER field_meta
    carries the picker meta key on bind ("Bound to <task> / sample
    <s>"). Our TUI already shows that data in the meta row, so the
    duplicate would push real content down with no value. Other ACP
    clients still receive the text; we just hide it locally.
    """
    state = SessionState()
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(
            type="text", text="Bound to my_task / sample s1 / epoch 0 [uuid-a]."
        ),
    )
    notif = SessionNotification(session_id="sid", update=chunk)
    notif.field_meta = {
        "inspect.picker.targets": [
            {"sessionId": "uuid-a", "task": "my_task", "sampleId": "s1", "epoch": 0}
        ]
    }
    state.consume(notif)
    assert state.items == []


def test_image_content_block_renders_as_placeholder() -> None:
    state = SessionState()
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=ImageContentBlock(type="image", data="ZmFrZQ==", mime_type="image/png"),
        message_id="m1",
    )
    state.consume(SessionNotification(session_id="sid", update=chunk))
    group = state.items[0]
    assert isinstance(group, MessageGroup)
    assert group.text == "[image]"


# ---------------------------------------------------------------------------
# Model attribution from _meta
# ---------------------------------------------------------------------------


def test_current_model_tracks_most_recent_agent_chunk() -> None:
    state = SessionState()
    state.consume(_agent_chunk("a", message_id="m1", model="m-1"))
    assert state.current_model == "m-1"
    state.consume(_agent_chunk("b", message_id="m2", model="m-2"))
    assert state.current_model == "m-2"


def test_chunk_without_model_meta_leaves_current_unchanged() -> None:
    state = SessionState()
    state.consume(_agent_chunk("a", message_id="m1", model="m-1"))
    state.consume(_user_chunk("ping"))  # no meta
    assert state.current_model == "m-1"


def test_message_group_records_originating_model() -> None:
    state = SessionState()
    state.consume(_agent_chunk("a", message_id="m1", model="m-1"))
    state.consume(_agent_chunk("b", message_id="m2", model="m-2"))
    groups = [i for i in state.items if isinstance(i, MessageGroup)]
    assert groups[0].model == "m-1"
    assert groups[1].model == "m-2"


# ---------------------------------------------------------------------------
# Tool-call merge
# ---------------------------------------------------------------------------


def test_tool_start_creates_state_in_items() -> None:
    state = SessionState()
    state.consume(_tool_start("tc-1", title="bash ls"))
    assert len(state.items) == 1
    tc = state.items[0]
    assert isinstance(tc, ToolCallState)
    assert tc.title == "bash ls"
    assert tc.status == "in_progress"
    assert tc.end_time is None


def test_tool_progress_merges_into_existing_state() -> None:
    state = SessionState()
    state.consume(_tool_start("tc-1"))
    state.consume(_tool_progress("tc-1", status="completed", raw_output="output"))
    # Still one item — progress merges in place, doesn't append.
    assert len(state.items) == 1
    tc = state.items[0]
    assert isinstance(tc, ToolCallState)
    assert tc.status == "completed"
    assert tc.raw_output == "output"
    assert tc.end_time is not None
    assert tc.duration_seconds is not None


def test_tool_progress_replaces_content_per_acp_semantics() -> None:
    """progress.content REPLACES start.content per ACP semantics.

    The server explicitly prepends the input view when sending result
    blocks so nothing is lost on the wire — client mirrors that with
    full replacement. progress.content=None means "no update".
    """
    state = SessionState()
    start = ToolCallStart(
        session_update="tool_call",
        tool_call_id="tc-1",
        title="bash",
        status="in_progress",
        content=[],  # empty start content
    )
    state.consume(SessionNotification(session_id="sid", update=start))
    prog = ToolCallProgress(
        session_update="tool_call_update",
        tool_call_id="tc-1",
        status="completed",
        content=None,  # no content → stays as-is, not cleared
    )
    state.consume(SessionNotification(session_id="sid", update=prog))
    tc = state.items[0]
    assert isinstance(tc, ToolCallState)
    assert tc.content == []  # not overwritten by None


def test_failed_tool_progress_marks_terminal() -> None:
    state = SessionState()
    state.consume(_tool_start("tc-1"))
    state.consume(_tool_progress("tc-1", status="failed"))
    tc = state.items[0]
    assert isinstance(tc, ToolCallState)
    assert tc.status == "failed"
    assert tc.is_terminal
    assert tc.end_time is not None


def test_out_of_order_progress_without_start_creates_state() -> None:
    """Defensive: progress arrives without a prior start (replay edge case)."""
    state = SessionState()
    state.consume(_tool_progress("tc-1", status="completed"))
    assert len(state.items) == 1
    tc = state.items[0]
    assert isinstance(tc, ToolCallState)
    assert tc.status == "completed"


def test_duration_captured_at_terminal_status() -> None:
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_tool_start("tc-1"))
    clock.advance(1.5)
    state.consume(_tool_progress("tc-1", status="completed"))
    tc = state.items[0]
    assert isinstance(tc, ToolCallState)
    assert tc.duration_seconds == 1.5


def test_in_flight_tool_has_no_duration() -> None:
    state = SessionState()
    state.consume(_tool_start("tc-1"))
    tc = state.items[0]
    assert isinstance(tc, ToolCallState)
    assert tc.duration_seconds is None


# ---------------------------------------------------------------------------
# Usage / SessionInfo
# ---------------------------------------------------------------------------


def test_usage_update_replaces_state() -> None:
    state = SessionState()
    assert state.usage is None
    state.consume(_usage(100, 200000))
    assert state.usage is not None
    assert state.usage.used == 100
    assert state.usage.size == 200000
    state.consume(_usage(500, 200000))
    assert state.usage.used == 500


def test_session_info_title_set_and_explicit_null_clears() -> None:
    state = SessionState()
    state.consume(_session_info("task / s1 / epoch 0"))
    assert state.session_title == "task / s1 / epoch 0"
    # Explicit null IS the destructive clear per ACP schema.
    state.consume(_session_info(None))
    assert state.session_title is None


def test_session_info_omitting_title_does_not_clear() -> None:
    """Reviewer P2: omitted title field must not wipe a set title.

    An update carrying only other fields (e.g. updated_at) must NOT
    wipe a previously-set title. Pydantic gives ``title=None`` both
    when explicitly null AND when the field is omitted — distinguish
    via ``model_fields_set``.
    """
    state = SessionState()
    state.consume(_session_info("real title"))
    assert state.session_title == "real title"
    # Build a SessionInfoUpdate where ONLY updated_at is set; title omitted.
    upd = SessionInfoUpdate(
        session_update="session_info_update", updated_at="2026-05-16T00:00:00Z"
    )
    state.consume(SessionNotification(session_id="sid", update=upd))
    assert state.session_title == "real title"  # not cleared


# ---------------------------------------------------------------------------
# Status state machine
# ---------------------------------------------------------------------------


def test_initial_status_is_awaiting_input() -> None:
    state = SessionState()
    assert state.status == StatusState.AWAITING_INPUT


def test_recent_chunk_yields_generating() -> None:
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_agent_chunk("a", message_id="m1"))
    assert state.status == StatusState.GENERATING


def test_chunk_then_quiescence_yields_awaiting() -> None:
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_agent_chunk("a", message_id="m1"))
    clock.advance(3.0)  # past the 2s quiescence window
    assert state.status == StatusState.AWAITING_INPUT


def test_in_flight_tool_overrides_generating() -> None:
    """Tools in flight always win — even right after a chunk."""
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_agent_chunk("a", message_id="m1"))  # would be Generating
    state.consume(_tool_start("tc-1"))
    assert state.status == StatusState.CALLING_TOOLS


def test_calling_tools_persists_until_all_tools_terminal() -> None:
    state = SessionState()
    state.consume(_tool_start("tc-1"))
    state.consume(_tool_start("tc-2"))
    assert state.tools_in_flight == 2
    state.consume(_tool_progress("tc-1", status="completed"))
    assert state.tools_in_flight == 1
    mid_status: StatusState = state.status
    assert mid_status == StatusState.CALLING_TOOLS
    state.consume(_tool_progress("tc-2", status="completed"))
    assert state.tools_in_flight == 0
    # After last tool terminates and chunks are stale → Awaiting.
    final_status: StatusState = state.status
    assert final_status == StatusState.AWAITING_INPUT


def test_failed_tool_does_not_stay_in_flight() -> None:
    state = SessionState()
    state.consume(_tool_start("tc-1"))
    state.consume(_tool_progress("tc-1", status="failed"))
    assert state.tools_in_flight == 0


def _pending_signal(message_id: str = "mid-1") -> SessionNotification:
    """An empty AgentMessageChunk carrying the pending-event meta flag."""
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=""),
        message_id=message_id,
        field_meta={
            "inspect.model": "phase2/model",
            "inspect.model_event_pending": True,
        },
    )
    return SessionNotification(session_id="sid", update=chunk)


def _completion_marker(message_id: str = "mid-1") -> SessionNotification:
    """An empty AgentMessageChunk carrying the completion meta flag."""
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=""),
        message_id=message_id,
        field_meta={
            "inspect.model": "phase2/model",
            "inspect.model_event_complete": True,
        },
    )
    return SessionNotification(session_id="sid", update=chunk)


def test_pending_signal_holds_status_at_generating_past_quiescence() -> None:
    """Pending tracker holds GENERATING across the full model latency.

    Otherwise the status row would fall back to AWAITING after the 2s
    quiescence window even though the model is still generating.
    """
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_pending_signal())
    # Advance way past the quiescence window — would normally fall back
    # to AWAITING_INPUT but the pending marker holds us at GENERATING.
    clock.advance(30.0)
    assert state.status == StatusState.GENERATING


def test_pending_signal_cleared_by_real_content_agent_chunk() -> None:
    """First real content chunk closes the pending tracker.

    Quiescence then takes over for the inter-chunk gap.
    """
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_pending_signal("m1"))
    assert state.status == StatusState.GENERATING
    state.consume(_agent_chunk("hello", message_id="m1"))
    # Still generating right after content (within quiescence).
    assert state.status == StatusState.GENERATING
    # After quiescence, no more pending, no recent chunks → awaiting.
    # Bind via a fresh local so mypy doesn't carry the GENERATING
    # narrowing from the earlier assert into this comparison.
    clock.advance(3.0)
    later: StatusState = state.status
    assert later == StatusState.AWAITING_INPUT


def test_pending_signal_cleared_by_completion_marker() -> None:
    """Tool-only response: completion marker closes the pending tracker."""
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_pending_signal("m1"))
    assert state.status == StatusState.GENERATING
    state.consume(_completion_marker("m1"))
    # No content, no in-flight tools — past quiescence we're back to awaiting.
    clock.advance(3.0)
    later: StatusState = state.status
    assert later == StatusState.AWAITING_INPUT


def test_consecutive_empty_pending_signals_collapse_as_retry() -> None:
    """Stacked empty assistant bubbles for retries fold into one group.

    The first pending → no content → second pending (different
    message_id) lands. The state recognises the previous item as an
    empty assistant group for the same model and bumps the retry
    counter instead of stacking another empty bubble.
    """
    state = SessionState()
    state.consume(_pending_signal("m1"))
    state.consume(_pending_signal("m2"))
    state.consume(_pending_signal("m3"))
    # All three pending signals collapsed into ONE bubble.
    assert len(state.items) == 1
    group = state.items[0]
    from inspect_ai.agent._acp.tui.state import MessageGroup

    assert isinstance(group, MessageGroup)
    # First attempt + 2 retries.
    assert group.retries == 2
    assert group.pending is True


def test_retry_completion_marker_targets_collapsed_group() -> None:
    """A retry's completion marker / late content flows into the alias target."""
    state = SessionState()
    state.consume(_pending_signal("m1"))
    state.consume(_pending_signal("m2"))
    # m2's completion marker should clear pending on the shared group.
    state.consume(_completion_marker("m2"))
    assert len(state.items) == 1
    group = state.items[0]
    from inspect_ai.agent._acp.tui.state import MessageGroup

    assert isinstance(group, MessageGroup)
    assert group.retries == 1
    assert group.pending is False


def test_content_chunk_after_pending_does_not_collapse_as_retry() -> None:
    """An assistant with content followed by a new pending is a fresh turn."""
    state = SessionState()
    state.consume(_pending_signal("m1"))
    state.consume(_agent_chunk("hello", message_id="m1"))
    # m1 now has content — a subsequent pending is a NEW turn, not a retry.
    state.consume(_pending_signal("m2"))
    assert len(state.items) == 2


def test_pending_signal_creates_visible_assistant_block() -> None:
    """The empty pending chunk creates the MessageGroup eagerly.

    Lets the chip render even before any content arrives so the user
    sees an assistant block is in flight.
    """
    state = SessionState()
    state.consume(_pending_signal("m1"))
    assert len(state.items) == 1
    item = state.items[0]
    from inspect_ai.agent._acp.tui.state import MessageGroup

    assert isinstance(item, MessageGroup)
    assert item.role == "assistant"
    assert item.model == "phase2/model"
    # No segments yet — content fills in on the complete phase.
    assert item.segments == []


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------


def test_subscriber_fires_on_each_state_change() -> None:
    state = SessionState()
    calls: list[int] = []
    state.subscribe(lambda: calls.append(1))
    state.consume(_agent_chunk("a", message_id="m1"))
    state.consume(_tool_start("tc-1"))
    state.consume(_usage(10, 100))
    assert len(calls) == 3


def test_subscriber_unsubscribe_stops_further_calls() -> None:
    state = SessionState()
    calls: list[int] = []
    unsub = state.subscribe(lambda: calls.append(1))
    state.consume(_agent_chunk("a", message_id="m1"))
    unsub()
    state.consume(_agent_chunk("b", message_id="m2"))
    assert len(calls) == 1


def test_failing_subscriber_does_not_break_others() -> None:
    state = SessionState()
    calls: list[int] = []

    def _boom() -> None:
        raise RuntimeError("oops")

    state.subscribe(_boom)
    state.subscribe(lambda: calls.append(1))
    state.consume(_agent_chunk("a", message_id="m1"))
    assert len(calls) == 1


def test_unknown_update_kind_does_not_notify() -> None:
    """SessionUpdate variants the state doesn't model are silently ignored.

    Picked ``CurrentModeUpdate`` as the representative "we don't model
    this" variant — ``AgentPlanUpdate`` *is* handled now that the
    plan strip widget consumes it, so it can't serve as the
    unsupported-kind canary any more.
    """
    from acp.schema import CurrentModeUpdate

    state = SessionState()
    calls: list[int] = []
    state.subscribe(lambda: calls.append(1))
    mode = CurrentModeUpdate(
        session_update="current_mode_update",
        current_mode_id="some-mode",
    )
    state.consume(SessionNotification(session_id="sid", update=mode))
    assert calls == []


# ---------------------------------------------------------------------------
# Interleaved transcript order (the canonical Phase 2 display case)
# ---------------------------------------------------------------------------


def test_messages_and_tool_calls_preserve_arrival_order() -> None:
    state = SessionState()
    state.consume(_agent_chunk("thinking...", message_id="m1"))
    state.consume(_tool_start("tc-1", title="bash"))
    state.consume(_tool_progress("tc-1", status="completed"))
    state.consume(_agent_chunk("done", message_id="m2"))
    # Order: assistant msg, tool call (single item), assistant msg.
    kinds = [type(item).__name__ for item in state.items]
    assert kinds == ["MessageGroup", "ToolCallState", "MessageGroup"]


# ---------------------------------------------------------------------------
# Windowing — state-side cap on retained assistant turns
# ---------------------------------------------------------------------------


def _assistant_count(state: SessionState) -> int:
    return sum(
        1
        for item in state.items
        if isinstance(item, MessageGroup) and item.role == "assistant"
    )


def test_turn_cap_drops_oldest_assistant_groups_past_limit() -> None:
    """Once we exceed _MAX_ASSISTANT_TURNS the oldest exchanges evict.

    Build 20 assistant groups (each with one tool call between for
    realism); the kept window should be exactly the 15 most recent
    assistants plus everything chronologically newer.
    """
    from inspect_ai.agent._acp.tui.state import _MAX_ASSISTANT_TURNS

    state = SessionState()
    state.consume(_user_chunk("kick off", message_id="mu-0"))
    for n in range(20):
        state.consume(_agent_chunk(f"step {n}", message_id=f"ma-{n}"))
        state.consume(_tool_start(f"tc-{n}", title=f"bash step{n}"))
        state.consume(_tool_progress(f"tc-{n}", status="completed"))
    assert _assistant_count(state) == _MAX_ASSISTANT_TURNS
    # Oldest assistant kept should be step 5 (since we dropped 0–4).
    first_assistant = next(
        item
        for item in state.items
        if isinstance(item, MessageGroup) and item.role == "assistant"
    )
    assert first_assistant.text == "step 5"
    # The earliest assistant + its paired tool call were both evicted.
    assert "ma-0" not in state._messages_by_id
    assert "tc-0" not in state._tool_calls_by_id
    # And kept ones remain reachable through the index.
    assert "ma-5" in state._messages_by_id
    assert "tc-5" in state._tool_calls_by_id


def test_turn_cap_retains_user_prompt_preceding_oldest_kept_assistant() -> None:
    """User prompt right before the oldest kept assistant is retained.

    Keeps the window starting with a real user→assistant pair rather
    than an orphan response.
    """
    from inspect_ai.agent._acp.tui.state import _MAX_ASSISTANT_TURNS

    state = SessionState()
    # Each turn starts with its own user message so the user prompts
    # are interleaved, not all bunched at the top.
    for n in range(_MAX_ASSISTANT_TURNS + 3):
        state.consume(_user_chunk(f"prompt {n}", message_id=f"mu-{n}"))
        state.consume(_agent_chunk(f"reply {n}", message_id=f"ma-{n}"))
    # First item after the cap kicks in should be a USER group —
    # specifically the prompt that triggered the oldest kept assistant.
    first = state.items[0]
    assert isinstance(first, MessageGroup) and first.role == "user"
    # And its sibling assistant is right after it.
    assert isinstance(state.items[1], MessageGroup)
    assert state.items[1].role == "assistant"


def test_turn_cap_strips_aliases_for_evicted_groups() -> None:
    """Retry aliases pointing at evicted message_ids must be cleared.

    Otherwise late chunks for those ids would silently route into
    deleted state.
    """
    from inspect_ai.agent._acp.tui.state import _MAX_ASSISTANT_TURNS

    state = SessionState()
    # Seed an alias by simulating a retry on the first turn.
    state._message_id_aliases["retry-of-ma-0"] = "ma-0"
    for n in range(_MAX_ASSISTANT_TURNS + 1):
        state.consume(_agent_chunk(f"step {n}", message_id=f"ma-{n}"))
    # ma-0 was evicted; the alias should be gone too.
    assert "ma-0" not in state._messages_by_id
    assert "retry-of-ma-0" not in state._message_id_aliases


def test_turn_cap_below_limit_is_a_noop() -> None:
    """Under the cap, nothing is evicted — index identity preserved."""
    from inspect_ai.agent._acp.tui.state import _MAX_ASSISTANT_TURNS

    state = SessionState()
    for n in range(_MAX_ASSISTANT_TURNS):
        state.consume(_agent_chunk(f"step {n}", message_id=f"ma-{n}"))
    assert _assistant_count(state) == _MAX_ASSISTANT_TURNS
    # All groups still indexed.
    for n in range(_MAX_ASSISTANT_TURNS):
        assert f"ma-{n}" in state._messages_by_id


# ---------------------------------------------------------------------------
# mark_interrupted — operator-driven optimistic clearing
# ---------------------------------------------------------------------------


def _pending_agent_chunk(message_id: str = "pending-1") -> SessionNotification:
    """Build the exact 'generation started' marker the server emits.

    Carries ``inspect.model_event_pending=True`` in field_meta so the
    state consumer registers it as a pending signal (sets
    ``_pending_message_ids``) — same path real server traffic uses.
    """
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=""),
        message_id=message_id,
        field_meta={"inspect.model_event_pending": True},
    )
    return SessionNotification(session_id="sid", update=chunk)


def test_mark_interrupted_drops_empty_pending_groups() -> None:
    """A pending bubble with no streamed content is removed entirely."""
    state = SessionState()
    state.consume(_pending_agent_chunk("pending-1"))
    assert state.status == StatusState.GENERATING
    assert "pending-1" in state._messages_by_id
    assert any(
        isinstance(item, MessageGroup) and item.message_id == "pending-1"
        for item in state.items
    )

    state.mark_interrupted()

    # mypy narrows `state.status` to GENERATING from the assert above,
    # but `mark_interrupted` resets it back to AWAITING_INPUT —
    # mypy can't model the state mutation across calls.
    assert state.status == StatusState.AWAITING_INPUT  # type: ignore[comparison-overlap]
    assert state._pending_message_ids == set()
    # The empty placeholder bubble is gone — both the items list and
    # the lookup index drop it.
    assert "pending-1" not in state._messages_by_id
    assert not any(
        isinstance(item, MessageGroup) and item.message_id == "pending-1"
        for item in state.items
    )


def test_mark_interrupted_keeps_pending_groups_with_partial_content() -> None:
    """If text streamed before the cancel, keep the bubble but drop pending."""
    state = SessionState()
    state.consume(_pending_agent_chunk("pending-2"))
    # Partial content arrives — pending=False after _append_segment but
    # we re-pend to mimic a quick second model_event_pending re-signal
    # (router emits one per ModelEvent retry; mid-stream cancel can
    # leave the group with content AND pending=True).
    state.consume(_agent_chunk("partial reply", message_id="pending-2"))
    state._pending_message_ids.add("pending-2")
    state._messages_by_id["pending-2"].pending = True

    state.mark_interrupted()

    assert state.status == StatusState.AWAITING_INPUT
    assert state._pending_message_ids == set()
    # Bubble is preserved with its partial content; just no longer pending.
    group = state._messages_by_id["pending-2"]
    assert group.pending is False
    assert group.segments and group.segments[0].text == "partial reply"


def test_mark_interrupted_drops_retry_aliases_for_dropped_groups() -> None:
    """Aliases pointing at dropped empty groups must not linger."""
    state = SessionState()
    state.consume(_pending_agent_chunk("pending-3"))
    state._message_id_aliases["retry-of-3"] = "pending-3"

    state.mark_interrupted()

    assert "pending-3" not in state._messages_by_id
    assert "retry-of-3" not in state._message_id_aliases


def _complete_marker_agent_chunk(message_id: str) -> SessionNotification:
    """Mimic the server's late completion marker for a cancelled ModelEvent.

    Router's ``_map_model_event`` empty branch emits this when a
    pending ModelEvent flips to ``pending=False`` with no output.
    """
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=""),
        message_id=message_id,
        field_meta={"inspect.model_event_complete": True},
    )
    return SessionNotification(session_id="sid", update=chunk)


def test_late_completion_marker_for_dropped_group_is_ignored() -> None:
    """A late server completion marker must not resurrect the dropped bubble.

    Repro for the reported regression: ``mark_interrupted`` drops the
    empty pending bubble (good); then the server-side cancel processing
    re-emits the ModelEvent with pending=False and the router converts
    it into an empty AgentMessageChunk with ``inspect.model_event_complete``
    meta. Without suppression that chunk created a fresh assistant
    group with no segments and no spinner — exactly the lingering empty
    bar we were trying to remove.
    """
    state = SessionState()
    state.consume(_pending_agent_chunk("pending-late"))
    state.mark_interrupted()
    assert "pending-late" not in state._messages_by_id

    state.consume(_complete_marker_agent_chunk("pending-late"))

    # Suppressed — no resurrection.
    assert "pending-late" not in state._messages_by_id
    assert not any(isinstance(item, MessageGroup) for item in state.items)


def test_new_pending_for_different_message_id_still_works() -> None:
    """Suppression must be scoped to the SPECIFIC dropped id, not blanket."""
    state = SessionState()
    state.consume(_pending_agent_chunk("pending-old"))
    state.mark_interrupted()

    # A new turn starts — new ModelEvent uuid → new message_id. The
    # spinner bubble must appear normally.
    state.consume(_pending_agent_chunk("pending-new"))

    assert "pending-new" in state._messages_by_id
    assert state.status == StatusState.GENERATING
    assert state._messages_by_id["pending-new"].pending is True


def test_late_completion_marker_under_retry_alias_is_ignored() -> None:
    """Tombstone must cover retry-collapse alias keys, not just canonical ids.

    Setup: a pending group exists at canonical id ``canonical-1`` and
    a retry-collapse alias maps ``retry-1`` → ``canonical-1`` (would
    happen if the model retried and the client collapsed both attempts
    into one bubble). Operator hits Esc → ``mark_interrupted`` drops
    the group, the alias mapping disappears with it. If the server's
    late completion marker travels under the RETRY id, the alias
    lookup fails (no longer present) and the resolved id is the raw
    retry id — which must still be tombstoned, or a ghost bubble
    appears.
    """
    state = SessionState()
    state.consume(_pending_agent_chunk("canonical-1"))
    state._message_id_aliases["retry-1"] = "canonical-1"

    state.mark_interrupted()

    # Both the canonical id AND the alias key are tombstoned.
    assert "canonical-1" in state._dropped_message_ids
    assert "retry-1" in state._dropped_message_ids

    # Late completion marker under the retry id must NOT resurrect.
    state.consume(_complete_marker_agent_chunk("retry-1"))
    assert "retry-1" not in state._messages_by_id
    assert "canonical-1" not in state._messages_by_id
    assert not any(isinstance(item, MessageGroup) for item in state.items)


def test_drop_message_groups_returns_alias_keys_too() -> None:
    """The helper exposes the full set of message_ids late chunks can use."""
    state = SessionState()
    state.consume(_pending_agent_chunk("canonical-2"))
    state._message_id_aliases["alias-A"] = "canonical-2"
    state._message_id_aliases["alias-B"] = "canonical-2"
    # Decoy: an alias pointing somewhere unrelated must NOT be included.
    state._message_id_aliases["alias-C"] = "some-other-group"

    returned = state._drop_message_groups(["canonical-2"])

    assert returned == {"canonical-2", "alias-A", "alias-B"}
    # Decoy alias preserved.
    assert state._message_id_aliases.get("alias-C") == "some-other-group"


def test_mark_interrupted_marks_in_flight_tools_failed() -> None:
    clock = _FakeClock(start=2000.0)
    state = SessionState(now=clock)
    state.consume(_tool_start("tc-1"))
    state.consume(_tool_start("tc-2"))
    assert state.tools_in_flight == 2
    assert state.status == StatusState.CALLING_TOOLS

    clock.t = 2010.0
    state.mark_interrupted()

    assert state.tools_in_flight == 0
    # mypy narrowed `status` to CALLING_TOOLS from the earlier assert;
    # `mark_interrupted` resets it but mypy can't track that mutation.
    assert state.status == StatusState.AWAITING_INPUT  # type: ignore[comparison-overlap]
    tc1 = state._tool_calls_by_id["tc-1"]
    tc2 = state._tool_calls_by_id["tc-2"]
    assert tc1.status == "failed"
    assert tc2.status == "failed"
    # end_time stamped from the clock so the card stops spinning and
    # the duration freezes at the cancel instant rather than continuing.
    assert tc1.end_time == 2010.0
    assert tc2.end_time == 2010.0


def test_mark_interrupted_does_not_touch_terminal_tools() -> None:
    """Already-completed tools must not be flipped to failed."""
    state = SessionState()
    state.consume(_tool_start("tc-done"))
    state.consume(_tool_progress("tc-done", status="completed"))
    state.consume(_tool_start("tc-live"))
    assert state._tool_calls_by_id["tc-done"].status == "completed"

    state.mark_interrupted()

    # Completed stays completed; only the in-flight one was flipped.
    assert state._tool_calls_by_id["tc-done"].status == "completed"
    assert state._tool_calls_by_id["tc-live"].status == "failed"


def test_mark_interrupted_resets_quiescence_timer() -> None:
    """The chunk-quiescence GENERATING branch must not re-assert itself.

    Without resetting ``_last_chunk_at`` the status pill would stay on
    GENERATING for the rest of the quiescence window (driven by chunk
    activity, not pending signals) even after we cleared everything.
    """
    clock = _FakeClock(start=500.0)
    state = SessionState(now=clock)
    state.consume(_agent_chunk("hi"))
    assert state._last_chunk_at is not None
    # Inside the quiescence window the chunk activity drives GENERATING
    # even though no pending message id is registered.
    assert state.status == StatusState.GENERATING

    state.mark_interrupted()

    assert state._last_chunk_at is None
    assert state.status == StatusState.AWAITING_INPUT


def test_mark_interrupted_notifies_subscribers_once() -> None:
    state = SessionState()
    state.consume(_pending_agent_chunk("p1"))
    state.consume(_tool_start("tc-1"))
    fires: list[int] = []
    state.subscribe(lambda: fires.append(1))

    state.mark_interrupted()

    assert sum(fires) == 1


def test_mark_interrupted_with_nothing_inflight_still_records_residue() -> None:
    """Hitting Esc with nothing in flight still flips ``_interrupted``.

    The lifecycle indicator needs to reflect that the operator did
    press Esc, even if there was no in-flight work to actually
    tear down — so subscribers fire once, the flag flips, and the
    derived lifecycle becomes ``interrupted``.
    """
    state = SessionState()
    fires: list[int] = []
    state.subscribe(lambda: fires.append(1))

    state.mark_interrupted()

    assert fires == [1]
    assert state.lifecycle == "interrupted"


def test_lifecycle_initial_is_idle() -> None:
    """At session start the resting lifecycle is ``idle`` (pill hidden)."""
    state = SessionState()
    assert state.lifecycle == "idle"


def test_lifecycle_running_while_pending_signal_active() -> None:
    """Pending model event flips lifecycle to ``running``."""
    state = SessionState()
    state.consume(_pending_signal("m1"))
    assert state.lifecycle == "running"


def test_lifecycle_running_while_tool_in_flight() -> None:
    """An in-flight tool call alone keeps lifecycle ``running``."""
    state = SessionState()
    state.consume(_tool_start(status="in_progress"))
    assert state.lifecycle == "running"


def test_lifecycle_back_to_idle_after_natural_turn_end() -> None:
    """Resting state between turns (past quiescence) is ``idle`` — NOT ``complete``.

    ``complete`` is reserved for the server-side session end
    (transport disconnect). A natural turn ending on a still-live
    session is just back to idle once the running-quiescence tail
    expires.
    """
    clock = _FakeClock()
    state = SessionState(now=clock)
    state.consume(_pending_signal("m1"))
    state.consume(_agent_chunk("hi", message_id="m1"))
    clock.t += 2.5  # past _RUNNING_QUIESCENCE_SECONDS
    assert state.lifecycle == "idle"


def test_lifecycle_complete_only_after_mark_complete_and_sticky() -> None:
    """``mark_complete`` is the only path to ``complete``, and it sticks.

    Sticky-ness matters: after the server-side session ends, late
    chunks that might still arrive on the wire must not unstick the
    indicator — the run is over and the UI is read-only from that
    point on.
    """
    state = SessionState()
    state.mark_complete()
    assert state.lifecycle == "complete"
    # A subsequent (e.g. last-flush) chunk arriving on the dying
    # connection must not flip us back to ``running``.
    state.consume(_pending_signal("m1"))
    assert state.lifecycle == "complete"


def test_lifecycle_interrupted_persists_after_mark_interrupted() -> None:
    """Esc during a turn leaves lifecycle at ``interrupted`` until next chunk."""
    state = SessionState()
    state.consume(_pending_signal("m1"))
    state.consume(_agent_chunk("partial", message_id="m1"))
    state.mark_interrupted()
    assert state.lifecycle == "interrupted"


def test_lifecycle_interrupted_clears_on_next_real_agent_chunk() -> None:
    """A fresh non-dropped chunk for a NEW group flips lifecycle back to running."""
    state = SessionState()
    state.consume(_pending_signal("m1"))
    state.consume(_agent_chunk("partial", message_id="m1"))
    state.mark_interrupted()
    assert state.lifecycle == "interrupted"
    state.consume(_pending_signal("m2"))
    # mypy narrowed `lifecycle` to "interrupted" above; the new pending
    # signal flips it back to "running" but that's a state mutation.
    assert state.lifecycle == "running"  # type: ignore[comparison-overlap]


def test_lifecycle_running_persists_through_quiescence_tail() -> None:
    """Sub-second gap between in-flight signals must not flicker the pill.

    Reproduces the original strobing complaint: model event completes,
    has_active_work briefly drops to False, then the next tool call
    starts. Without the quiescence tail the pill would flip
    ``running → idle → running`` in the gap. With it, ``running``
    persists for the tail window.
    """
    clock = _FakeClock()
    state = SessionState(now=clock)

    state.consume(_pending_signal("m1"))
    assert state.lifecycle == "running"
    # Pending completes (e.g. via content chunk that closes the
    # pending window). ``has_active_work`` is now False, but we're
    # still within the quiescence tail.
    state.consume(_agent_chunk("hi", message_id="m1"))
    clock.t += 0.5
    assert state.lifecycle == "running", (
        "expected the quiescence tail to keep the pill on running"
    )


def test_lifecycle_falls_to_idle_after_quiescence_window_expires() -> None:
    """After the tail expires with no fresh activity, lifecycle is idle."""
    clock = _FakeClock()
    state = SessionState(now=clock)

    state.consume(_pending_signal("m1"))
    state.consume(_agent_chunk("hi", message_id="m1"))
    clock.t += 2.5  # past _RUNNING_QUIESCENCE_SECONDS
    assert state.lifecycle == "idle"


def test_lifecycle_interrupted_wins_over_running_quiescence_tail() -> None:
    """Esc inside the tail window reads as ``interrupted``, not warm-running.

    Without explicit priority, the post-Esc state (has_active_work
    False, _interrupted True, _last_running_at still recent) could
    have fallen back into the quiescence-tail ``running`` branch and
    swallowed the interrupt signal.
    """
    clock = _FakeClock()
    state = SessionState(now=clock)

    state.consume(_pending_signal("m1"))
    state.consume(_agent_chunk("partial", message_id="m1"))
    # We're now in the quiescence tail.
    state.mark_interrupted()
    assert state.lifecycle == "interrupted"


def test_lifecycle_tail_stamped_when_long_pending_completes() -> None:
    """Pending that runs >2s before completing still gets a fresh tail.

    Regression: stamping only when ``has_active_work`` was True AFTER
    the update meant the update that *ended* the only active work
    left a stale stamp (from the pending signal seconds earlier).
    The lifecycle then skipped the quiescence tail and fell straight
    to ``idle`` the moment generation completed — flickering the
    pill at every long turn boundary.
    """
    clock = _FakeClock()
    state = SessionState(now=clock)

    state.consume(_pending_signal("m1"))
    assert state.lifecycle == "running"

    # Sit on the pending for longer than the quiescence window.
    clock.t += 5.0
    assert state.lifecycle == "running"  # has_active_work covers it

    # Completion chunk arrives — has_active_work flips to False, but
    # the tail should re-stamp NOW so we stay on running for the
    # full quiescence window after the actual end of work.
    state.consume(_agent_chunk("done", message_id="m1"))
    assert state.lifecycle == "running"

    # Half a tail in, still running.
    clock.t += 1.0
    assert state.lifecycle == "running"

    # Past the tail, falls to idle as expected.
    clock.t += 2.0
    # mypy narrowed `lifecycle` to "running" earlier; the clock-driven
    # expiry flips it to "idle" but mypy can't model time-based mutation.
    assert state.lifecycle == "idle"  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# Plan state — AgentPlanUpdate consumption + derived helpers
# ---------------------------------------------------------------------------


def _plan_update(
    *entries: tuple[str, str],
) -> SessionNotification:
    """Build a SessionNotification carrying an AgentPlanUpdate.

    ``entries`` is a list of ``(content, status)`` tuples — keeps the
    test call sites compact and readable.
    """
    from acp.schema import AgentPlanUpdate, PlanEntry

    plan_entries = [
        PlanEntry(content=content, status=status, priority="medium")  # type: ignore[arg-type]
        for content, status in entries
    ]
    return SessionNotification(
        session_id="sid",
        update=AgentPlanUpdate(session_update="plan", entries=plan_entries),
    )


def test_plan_entries_initially_none() -> None:
    """Default state: no plan, derived counts return zero."""
    state = SessionState()
    assert state.plan_entries is None
    assert state.plan_done_count == 0
    assert state.plan_total_count == 0
    assert state.plan_current_entry is None


def test_plan_first_update_populates_entries() -> None:
    state = SessionState()
    state.consume(
        _plan_update(
            ("write tests", "completed"),
            ("ship feature", "in_progress"),
            ("celebrate", "pending"),
        )
    )
    assert state.plan_entries is not None
    assert [e.content for e in state.plan_entries] == [
        "write tests",
        "ship feature",
        "celebrate",
    ]
    assert state.plan_done_count == 1
    assert state.plan_total_count == 3


def test_plan_subsequent_update_replaces_previous_entries() -> None:
    """ACP plan updates are full replacement, not deltas."""
    state = SessionState()
    state.consume(_plan_update(("old task", "in_progress")))
    state.consume(_plan_update(("new task A", "completed"), ("new task B", "pending")))
    assert state.plan_entries is not None
    assert [e.content for e in state.plan_entries] == ["new task A", "new task B"]


def test_plan_consume_notifies_subscriber() -> None:
    state = SessionState()
    calls: list[int] = []
    state.subscribe(lambda: calls.append(1))
    state.consume(_plan_update(("only", "pending")))
    assert calls == [1]


def test_plan_current_prefers_in_progress_over_pending() -> None:
    """A row explicitly marked in_progress beats the first pending row."""
    state = SessionState()
    state.consume(
        _plan_update(
            ("first pending", "pending"),
            ("the active one", "in_progress"),
            ("later pending", "pending"),
        )
    )
    current = state.plan_current_entry
    assert current is not None
    assert current.content == "the active one"
    assert current.status == "in_progress"


def test_plan_current_falls_back_to_first_pending_when_none_running() -> None:
    state = SessionState()
    state.consume(
        _plan_update(
            ("done one", "completed"),
            ("first up", "pending"),
            ("later up", "pending"),
        )
    )
    current = state.plan_current_entry
    assert current is not None
    assert current.content == "first up"


def test_plan_current_index_matches_plan_current_entry() -> None:
    """``plan_current_index`` and ``plan_current_entry`` point at the same row.

    Both surfaces (strip + overlay) read these — they must agree.
    Cover the tricky case where a pending row precedes the
    in_progress row: index 1, not index 0.
    """
    state = SessionState()
    state.consume(
        _plan_update(
            ("first pending", "pending"),
            ("the active one", "in_progress"),
            ("later pending", "pending"),
        )
    )
    assert state.plan_current_index == 1
    current = state.plan_current_entry
    assert current is not None
    assert state.plan_entries is not None
    assert state.plan_entries[state.plan_current_index] is current


def test_plan_current_index_none_when_all_completed() -> None:
    state = SessionState()
    state.consume(_plan_update(("a", "completed"), ("b", "completed")))
    assert state.plan_current_index is None
    assert state.plan_current_entry is None


def test_plan_current_index_none_when_no_plan() -> None:
    state = SessionState()
    assert state.plan_current_index is None


def test_plan_current_is_none_when_all_completed() -> None:
    state = SessionState()
    state.consume(_plan_update(("a", "completed"), ("b", "completed")))
    assert state.plan_current_entry is None
    # Tally still reflects the finished work.
    assert state.plan_done_count == 2
    assert state.plan_total_count == 2


def test_plan_entries_decoupled_from_payload_list() -> None:
    """The state stores a copy; mutating the caller's list won't drift state."""
    from acp.schema import AgentPlanUpdate, PlanEntry

    entries = [PlanEntry(content="x", status="pending", priority="medium")]
    state = SessionState()
    state.consume(
        SessionNotification(
            session_id="sid",
            update=AgentPlanUpdate(session_update="plan", entries=entries),
        )
    )
    entries.append(PlanEntry(content="y", status="pending", priority="medium"))
    # State's snapshot stays length 1 even though the caller's list grew.
    assert state.plan_entries is not None
    assert len(state.plan_entries) == 1
    assert state.plan_entries[0].content == "x"
