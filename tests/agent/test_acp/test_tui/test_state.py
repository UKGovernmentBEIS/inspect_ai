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

from inspect_ai.agent._acp._tui._state import (
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


def test_current_model_tracks_most_recent_chunk() -> None:
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
    """Phase 2 ignores Plan / Mode / Config updates. Subscriber shouldn't fire."""
    from acp.schema import AgentPlanUpdate, PlanEntry

    state = SessionState()
    calls: list[int] = []
    state.subscribe(lambda: calls.append(1))
    plan = AgentPlanUpdate(
        session_update="plan",
        entries=[PlanEntry(content="x", status="pending", priority="medium")],
    )
    state.consume(SessionNotification(session_id="sid", update=plan))
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
