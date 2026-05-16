"""Pilot tests for the Phase 2 conversation widgets.

Module-level ``pytestmark = slow`` per the design-doc convention:
Pilot tests pay the Textual app-bootstrap cost; the fast unit loop
should stay sub-second.
"""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widgets import Static

from inspect_ai.agent._acp._tui._state import (
    MessageGroup,
    Segment,
    SessionState,
    StatusState,
    ToolCallState,
)
from inspect_ai.agent._acp._tui._widgets import (
    MessageWidget,
    StatusRowWidget,
    ToolCallWidget,
    TranscriptWidget,
)
from inspect_ai.agent._acp._tui._widgets._message import _ReasoningBlock
from inspect_ai.agent._acp._tui._widgets._tool_call import _format_duration

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Pure-function helpers (don't need an app at all but live with peers)
# ---------------------------------------------------------------------------


def test_format_duration_sub_second_uses_one_decimal() -> None:
    assert _format_duration(0.2) == "0.2s"
    assert _format_duration(0.0) == "0.0s"


def test_format_duration_seconds_to_minutes() -> None:
    assert _format_duration(1.0) == "1s"
    assert _format_duration(59.7) == "59s"
    assert _format_duration(60.0) == "1m 00s"
    assert _format_duration(64.0) == "1m 04s"


def test_format_duration_minutes_to_hours() -> None:
    assert _format_duration(3600.0) == "1h 00m"
    assert _format_duration(3720.0) == "1h 02m"


def test_format_duration_none_returns_em_dash() -> None:
    assert _format_duration(None) == "—"


# ---------------------------------------------------------------------------
# Single-widget harness
# ---------------------------------------------------------------------------


def _harness(widget_factory):
    """Build a one-shot Textual app that hosts a single widget.

    Returns a callable instead of constructing an App at import time so
    pytest collection stays fast. ``widget_factory`` is a zero-arg
    callable returning the widget to mount.
    """

    class _OneWidgetApp(App[None]):
        def compose(self) -> ComposeResult:
            yield widget_factory()

    return _OneWidgetApp()


# ---------------------------------------------------------------------------
# MessageWidget
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_user_message_renders_user_chip() -> None:
    group = MessageGroup(
        message_id="m1", role="user", segments=[Segment(kind="text", text="hello")]
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        chip = mw.query_one(".chip", Static)
        assert "user · dataset_input" in str(chip.content)
        # Body shows the text.
        bodies = list(mw.query(".segment-text"))
        assert any("hello" in str(b.content) for b in bodies)


@skip_if_trio
@pytest.mark.anyio
async def test_assistant_message_shows_group_model_chip() -> None:
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="text", text="hi")],
        model="my-model",
    )
    app = _harness(lambda: MessageWidget(group, current_model="other-model"))
    async with app.run_test() as pilot:
        await pilot.pause()
        chip = app.query_one(MessageWidget).query_one(".chip", Static)
        # Group's own model wins over the session-wide fallback.
        assert "assistant · my-model" in str(chip.content)


@skip_if_trio
@pytest.mark.anyio
async def test_assistant_falls_back_to_current_model_when_group_missing() -> None:
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="text", text="hi")],
        model=None,
    )
    app = _harness(lambda: MessageWidget(group, current_model="session-model"))
    async with app.run_test() as pilot:
        await pilot.pause()
        chip = app.query_one(MessageWidget).query_one(".chip", Static)
        assert "assistant · session-model" in str(chip.content)


@skip_if_trio
@pytest.mark.anyio
async def test_assistant_with_reasoning_segment_mounts_reasoning_block() -> None:
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[
            Segment(kind="reasoning", text="thinking..."),
            Segment(kind="text", text="answer"),
        ],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        reasoning_blocks = list(mw.query(_ReasoningBlock))
        assert len(reasoning_blocks) == 1
        # Collapsed by default — body has the `display: none` class on
        # the parent. We check the CSS class.
        assert reasoning_blocks[0].has_class("collapsed")


@skip_if_trio
@pytest.mark.anyio
async def test_reasoning_block_toggle_action_expands() -> None:
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="reasoning", text="thoughts")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(_ReasoningBlock)
        assert block.has_class("collapsed")
        block.action_toggle_reasoning()
        await pilot.pause()
        assert not block.has_class("collapsed")
        block.action_toggle_reasoning()
        await pilot.pause()
        assert block.has_class("collapsed")


# ---------------------------------------------------------------------------
# ToolCallWidget
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_renders_kind_icon_and_title() -> None:
    state = ToolCallState(
        tool_call_id="tc-1",
        title="read /etc/hosts",
        kind="read",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        header_text = str(w.query_one(".header", Static).content)
        assert "📄" in header_text
        assert "read /etc/hosts" in header_text


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_tick_advances_in_flight_duration() -> None:
    """Reviewer P3: in-flight tools must visibly tick without a state mutation.

    SessionScreen's periodic timer calls ``tick_duration`` on each
    in-flight card so the elapsed value advances; once terminal, the
    method short-circuits to avoid DOM churn.
    """
    state = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        first_footer = str(w.query_one(".footer", Static).content)
        # Force the elapsed value forward by rewinding start_time.
        state.start_time -= 5.0
        w.tick_duration()
        await pilot.pause()
        second_footer = str(w.query_one(".footer", Static).content)
        assert first_footer != second_footer
        # Once terminal, tick_duration is a no-op (final duration stays).
        state.status = "completed"
        state.end_time = state.start_time + 5.0
        w.update_state(state)
        await pilot.pause()
        terminal_footer = str(w.query_one(".footer", Static).content)
        state.end_time = state.start_time + 999.0  # would change duration
        w.tick_duration()
        await pilot.pause()
        assert str(w.query_one(".footer", Static).content) == terminal_footer


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_status_class_follows_state() -> None:
    state = ToolCallState(tool_call_id="tc-1", status="in_progress")
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        assert w.has_class("in-flight")
        # Mutate the underlying state and re-update — mirrors how the
        # transcript widget triggers in-place updates on progress.
        state.status = "completed"
        state.end_time = state.start_time + 0.42
        w.update_state(state)
        await pilot.pause()
        assert w.has_class("completed")
        assert not w.has_class("in-flight")


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_diff_content_renders_old_and_new_lines() -> None:
    diff_block = type(
        "Diff",
        (),
        {
            "type": "diff",
            "path": "/tmp/a.txt",
            "old_text": "alpha\nbeta",
            "new_text": "gamma\ndelta",
        },
    )()
    state = ToolCallState(
        tool_call_id="tc-1",
        title="edit a.txt",
        kind="edit",
        status="completed",
        content=[diff_block],
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        # Three header/old/new line classes; check we got at least one
        # of each plus the file path.
        old_lines = [str(s.content) for s in w.query(".diff-old")]
        new_lines = [str(s.content) for s in w.query(".diff-new")]
        headers = [str(s.content) for s in w.query(".diff-header")]
        assert any("alpha" in s for s in old_lines)
        assert any("beta" in s for s in old_lines)
        assert any("gamma" in s for s in new_lines)
        assert any("delta" in s for s in new_lines)
        assert any("/tmp/a.txt" in h for h in headers)


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_terminal_content_renders_placeholder() -> None:
    terminal_block = type("Term", (), {"type": "terminal", "terminal_id": "t-99"})()
    state = ToolCallState(
        tool_call_id="tc-2",
        title="bash",
        status="in_progress",
        content=[terminal_block],
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        body_text = " ".join(str(s.content) for s in w.query(".body-content"))
        assert "[terminal: t-99]" in body_text


# ---------------------------------------------------------------------------
# StatusRowWidget
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_status_row_pill_changes_class_with_state() -> None:
    state = SessionState()
    app = _harness(StatusRowWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        row = app.query_one(StatusRowWidget)
        pill = row.query_one("#pill", Static)
        # Initial: sage (Awaiting input).
        assert pill.has_class("sage")
        # Force a tool to go in-flight → pill should become teal.
        state._tool_calls_by_id["x"] = ToolCallState(
            tool_call_id="x", status="in_progress"
        )
        state.items.append(state._tool_calls_by_id["x"])
        row.refresh_from(state)
        await pilot.pause()
        assert pill.has_class("teal")
        assert "Calling tools" in str(pill.content)


@skip_if_trio
@pytest.mark.anyio
async def test_status_row_chips_render_model_tokens_and_tools() -> None:
    state = SessionState()
    state.current_model = "gpt-5"
    # Inject usage + a tool in flight.
    from inspect_ai.agent._acp._tui._state import UsageState

    state.usage = UsageState(used=12_400, size=200_000)
    state._tool_calls_by_id["x"] = ToolCallState(tool_call_id="x", status="in_progress")
    state.items.append(state._tool_calls_by_id["x"])

    app = _harness(StatusRowWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        row = app.query_one(StatusRowWidget)
        row.refresh_from(state)
        await pilot.pause()
        chips = {c.id: str(c.content) for c in row.query(".chip")}
        assert "model gpt-5" in chips["chip-model"]
        # 12_400 → "12K" via _format_tokens (>= 10, drops decimal).
        assert "tokens 12K / 200K" in chips["chip-tokens"]
        assert "1 tool in flight" in chips["chip-tools"]


@skip_if_trio
@pytest.mark.anyio
async def test_status_row_tools_chip_pluralizes() -> None:
    state = SessionState()
    for i in range(3):
        tid = f"t{i}"
        state._tool_calls_by_id[tid] = ToolCallState(
            tool_call_id=tid, status="in_progress"
        )
        state.items.append(state._tool_calls_by_id[tid])
    app = _harness(StatusRowWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        row = app.query_one(StatusRowWidget)
        row.refresh_from(state)
        await pilot.pause()
        assert "3 tools in flight" in str(row.query_one("#chip-tools", Static).content)


@skip_if_trio
@pytest.mark.anyio
async def test_status_row_tokens_chip_omits_denominator_when_size_unknown() -> None:
    state = SessionState()
    from inspect_ai.agent._acp._tui._state import UsageState

    state.usage = UsageState(used=900, size=0)
    app = _harness(StatusRowWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        row = app.query_one(StatusRowWidget)
        row.refresh_from(state)
        await pilot.pause()
        text = str(row.query_one("#chip-tokens", Static).content)
        assert text == "tokens 900"


# ---------------------------------------------------------------------------
# TranscriptWidget
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_transcript_mounts_message_then_tool_in_arrival_order() -> None:
    state = SessionState()
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="text", text="hi")],
    )
    tool = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    state._messages_by_id["m1"] = group
    state._tool_calls_by_id["tc-1"] = tool
    state.items.extend([group, tool])

    app = _harness(TranscriptWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        tr = app.query_one(TranscriptWidget)
        tr.refresh_from(state)
        await pilot.pause()
        assert isinstance(tr.children[0], MessageWidget)
        assert isinstance(tr.children[1], ToolCallWidget)


@skip_if_trio
@pytest.mark.anyio
async def test_transcript_updates_tool_in_place_without_remount() -> None:
    state = SessionState()
    tool = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    state._tool_calls_by_id["tc-1"] = tool
    state.items.append(tool)

    app = _harness(TranscriptWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        tr = app.query_one(TranscriptWidget)
        tr.refresh_from(state)
        await pilot.pause()
        original = tr.children[0]
        # Move the tool to completed; refresh should mutate in place.
        tool.status = "completed"
        tool.end_time = tool.start_time + 0.1
        tr.refresh_from(state)
        await pilot.pause()
        # Same widget instance — proof we didn't remount.
        assert tr.children[0] is original
        assert original.has_class("completed")


@skip_if_trio
@pytest.mark.anyio
async def test_transcript_remounts_message_when_segments_extend() -> None:
    state = SessionState()
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="text", text="hi")],
    )
    state._messages_by_id["m1"] = group
    state.items.append(group)

    app = _harness(TranscriptWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        tr = app.query_one(TranscriptWidget)
        tr.refresh_from(state)
        await pilot.pause()
        first_widget = tr.children[0]

        # Extend the group: a longer last-segment text triggers
        # remount via the fingerprint check.
        group.segments[-1].text = "hi there"
        tr.refresh_from(state)
        await pilot.pause()
        new_widget = tr.children[0]
        assert new_widget is not first_widget
        body_text = " ".join(str(s.content) for s in new_widget.query(".segment-text"))
        assert "hi there" in body_text


# ---------------------------------------------------------------------------
# Status formatters (pure functions)
# ---------------------------------------------------------------------------


def test_status_state_enum_membership_is_phase_2_only() -> None:
    """Sanity guard: Phase 2 ships three states; later phases add more."""
    members = {s.value for s in StatusState}
    assert members == {"awaiting_input", "generating", "calling_tools"}
