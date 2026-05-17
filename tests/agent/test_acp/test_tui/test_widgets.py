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

from inspect_ai.agent._acp.tui.state import (
    MessageGroup,
    Segment,
    SessionState,
    StatusState,
    ToolCallState,
)
from inspect_ai.agent._acp.tui.widgets import (
    MessageWidget,
    ToolCallWidget,
    TranscriptWidget,
)
from inspect_ai.agent._acp.tui.widgets._formatting import (
    format_duration as _format_duration,
)
from inspect_ai.agent._acp.tui.widgets.message import _ReasoningBlock

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


# Stand-in for ACP's TextContentBlock / ContentToolCallContent —
# tool-call tests only need the duck-typed ``type`` and ``text``
# attributes the widget reads, so a tiny pair of classes keeps the
# tests independent of the wire-schema layout. Hoisted to module
# scope so mypy doesn't see four duplicate definitions across
# nested test functions (no-redef noise).
class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeContentBlock:
    type = "content"

    def __init__(self, text: str) -> None:
        self.content = _FakeTextBlock(text)


# ---------------------------------------------------------------------------
# MessageWidget
# ---------------------------------------------------------------------------


def _segment_text(widget: Static) -> str:
    """Extract the source markdown from a Static rendering Rich Markdown.

    Segment statics wrap a :class:`rich.markdown.Markdown` instance now
    (so fenced code blocks render formatted instead of showing raw
    backticks). ``Static.render()`` returns a ``RichVisual`` whose
    ``_renderable`` is the wrapped Markdown; reach in for its source.
    """
    visual = widget.render()
    renderable = getattr(visual, "_renderable", visual)
    if hasattr(renderable, "markup"):
        return str(renderable.markup)
    return str(renderable)


def _chip_plain(chip: Static) -> str:
    """Render the chip's markup to plain text for substring assertions."""
    from rich.text import Text

    return Text.from_markup(str(chip.content)).plain


@skip_if_trio
@pytest.mark.anyio
async def test_user_message_renders_user_chip_with_source_suffix() -> None:
    group = MessageGroup(
        message_id="m1",
        role="user",
        user_source="input",
        segments=[Segment(kind="text", text="hello")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        chip = mw.query_one(".chip", Static)
        # Source rides as dim provenance after the role word — same
        # treatment as "assistant · model".
        assert "user · input" in _chip_plain(chip)
        # Body text is rendered inside a _CollapsibleContent (the
        # same widget tool output uses) so long messages get the
        # ``… N more lines`` expander treatment.
        from inspect_ai.agent._acp.tui.widgets._collapsible import (
            CollapsibleContent as _CollapsibleContent,
        )

        ccs = list(mw.query(_CollapsibleContent))
        assert any("hello" in cc._full_text for cc in ccs)


@skip_if_trio
@pytest.mark.anyio
async def test_user_message_without_source_shows_bare_user_chip() -> None:
    """When ChatMessageUser.source is None the chip drops the suffix."""
    group = MessageGroup(
        message_id="m1",
        role="user",
        segments=[Segment(kind="text", text="hi")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        chip = _chip_plain(mw.query_one(".chip", Static))
        assert chip.strip() == "user"


@skip_if_trio
@pytest.mark.anyio
async def test_system_message_renders_system_chip() -> None:
    """System messages share the user-bubble surface with a distinct chip."""
    group = MessageGroup(
        message_id="m1",
        role="system",
        segments=[Segment(kind="text", text="you are a helpful agent")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        chip = _chip_plain(mw.query_one(".chip", Static))
        assert chip.strip() == "system"


@skip_if_trio
@pytest.mark.anyio
async def test_operator_user_message_gets_operator_class() -> None:
    """``user_source='operator'`` adds the ``.operator`` CSS class.

    Pinned because the CSS rule that swaps the user clay background
    for plum keys off this class. A regression that drops the class
    would silently re-render operator messages with the dataset-input
    color.
    """
    group = MessageGroup(
        message_id="m1",
        role="user",
        user_source="operator",
        segments=[Segment(kind="text", text="skip ahead")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        assert mw.has_class("user")
        assert mw.has_class("operator")


@skip_if_trio
@pytest.mark.anyio
async def test_long_message_text_gets_truncation_note() -> None:
    """Text segments past the per-message line cap show ``… N more lines``.

    Without the cap, a long agent response would push the rest of
    the transcript off-screen. The collapsible expander gives the
    operator an opt-in to see the full content.
    """
    from inspect_ai.agent._acp.tui.widgets._collapsible import (
        CollapsibleContent as _CollapsibleContent,
    )
    from inspect_ai.agent._acp.tui.widgets.message import (
        _MESSAGE_TEXT_MAX_LINES,
    )

    over_cap = "\n".join(f"line {n}" for n in range(_MESSAGE_TEXT_MAX_LINES + 5))
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="text", text=over_cap)],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        cc = mw.query_one(_CollapsibleContent)
        # Note widget is present and reports the elided line count.
        note = cc.query_one("#cc-note", Static)
        plain = str(note.content)
        assert "5 more lines" in plain


@skip_if_trio
@pytest.mark.anyio
async def test_short_message_text_omits_truncation_note() -> None:
    """Messages under the cap render without the expander affordance."""
    from inspect_ai.agent._acp.tui.widgets._collapsible import (
        CollapsibleContent as _CollapsibleContent,
    )

    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="text", text="line 1\nline 2\nline 3")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        cc = mw.query_one(_CollapsibleContent)
        notes = list(cc.query("#cc-note"))
        assert notes == []


@skip_if_trio
@pytest.mark.anyio
async def test_dataset_user_message_does_not_get_operator_class() -> None:
    """Only ``operator`` source flips the plum-background class."""
    group = MessageGroup(
        message_id="m1",
        role="user",
        user_source="input",
        segments=[Segment(kind="text", text="from dataset")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        assert mw.has_class("user")
        assert not mw.has_class("operator")


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
        assert "assistant · my-model" in _chip_plain(chip)


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
        assert "assistant · session-model" in _chip_plain(chip)


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
        header = w.query_one(".header", Static)
        # Header is markup-rendered: tool name bold, args dim. Render
        # to plain text so we can assert on what the user actually sees.
        rendered = header.render_str(str(header.content)).plain
        assert "📄" in rendered
        assert "read /etc/hosts" in rendered
        # And the raw markup distinguishes name from args.
        raw = str(header.content)
        assert "[bold]read[/bold]" in raw
        assert "[dim]/etc/hosts[/dim]" in raw


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_header_omits_dim_when_no_args() -> None:
    state = ToolCallState(
        tool_call_id="tc-1",
        title="update_plan",
        kind="edit",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        raw = str(w.query_one(".header", Static).content)
        assert "[bold]update_plan[/bold]" in raw
        assert "[dim]" not in raw


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_renders_plan_entries_from_raw_input() -> None:
    """update_plan tool: show the plan checklist from raw_input."""
    state = ToolCallState(
        tool_call_id="tc-1",
        title="update_plan",
        kind="edit",
        status="in_progress",
        raw_input={
            "plan": [
                {"content": "step one", "status": "completed"},
                {"content": "step two", "status": "in_progress"},
                {"content": "step three", "status": "pending"},
            ]
        },
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        entries = [str(e.content) for e in w.query(".plan-entry")]
        assert any("[x] step one" in e for e in entries)
        assert any("[~] step two" in e for e in entries)
        assert any("[ ] step three" in e for e in entries)


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_plan_uses_inspect_step_key() -> None:
    """Inspect's ``update_plan`` tool stores text under ``step``, not ``content``.

    Previously we only checked ``content`` / ``text``, so plan entries
    rendered with empty bodies (`` [x] `` with nothing after) for real
    Inspect agent runs.
    """
    state = ToolCallState(
        tool_call_id="tc-1",
        title="update_plan",
        kind="edit",
        status="completed",
        raw_input={
            "plan": [
                {"step": "Read existing tests", "status": "completed"},
                {"step": "Add new test", "status": "in_progress"},
            ]
        },
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        entries = [str(e.content) for e in w.query(".plan-entry")]
        assert any("[x] Read existing tests" in e for e in entries)
        assert any("[~] Add new test" in e for e in entries)


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_truncates_long_content_with_indicator() -> None:
    """Outputs over the line cap show only N lines + ``… M more lines``."""
    long_output = "\n".join(f"line {i}" for i in range(30))
    content_block = type(
        "Content",
        (),
        {
            "type": "content",
            "content": type("TextBlock", (), {"type": "text", "text": long_output})(),
        },
    )()
    state = ToolCallState(
        tool_call_id="tc-1",
        title="bash ls",
        kind="other",
        status="completed",
        content=[content_block],
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        notes = [str(n.content) for n in w.query(".truncation-note")]
        assert any("more line" in n for n in notes)
        # 30 lines, cap is 15 → 15 elided.
        assert any("15" in n for n in notes)


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_truncated_content_expands_on_click() -> None:
    """Clicking the more-lines indicator swaps in the full text + drops the note."""
    from inspect_ai.agent._acp.tui.widgets._collapsible import (
        CollapsibleContent as _CollapsibleContent,
    )

    long_output = "\n".join(f"line {i}" for i in range(30))
    content_block = type(
        "Content",
        (),
        {
            "type": "content",
            "content": type("TextBlock", (), {"type": "text", "text": long_output})(),
        },
    )()
    state = ToolCallState(
        tool_call_id="tc-2",
        title="bash ls",
        kind="other",
        status="completed",
        content=[content_block],
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        collapsible = w.query_one(_CollapsibleContent)
        assert len(w.query(".truncation-note")) == 1
        collapsible.on_click()
        await pilot.pause()
        # Note removed, body now holds the full content.
        assert len(w.query(".truncation-note")) == 0
        # Idempotency: clicking again after expansion does nothing.
        collapsible.on_click()
        await pilot.pause()
        assert len(w.query(".truncation-note")) == 0


@skip_if_trio
@pytest.mark.anyio
async def test_reasoning_block_click_toggles_expand() -> None:
    """Reviewer: clicking a reasoning block should toggle expand/collapse."""
    from inspect_ai.agent._acp.tui.widgets.message import _ReasoningBlock

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
        # Drive the click handler directly — the on_click method is
        # what Textual calls when the user clicks anywhere on the
        # widget; mirrors what a real mouse click would do.
        block.on_click()
        await pilot.pause()
        assert not block.has_class("collapsed")


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
# SessionHeaderWidget
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_session_header_strips_first_path_segment_from_task() -> None:
    """``inspect_harbor/terminal_bench_2_0`` → ``terminal_bench_2_0``.

    The suite prefix is constant across rows and eats horizontal
    space the header can't afford.
    """
    from pathlib import Path

    from inspect_ai.agent._acp.discovery import TargetAddress
    from inspect_ai.agent._acp.tui.client import SessionRow
    from inspect_ai.agent._acp.tui.widgets.header import SessionHeaderWidget

    row = SessionRow(
        eval_id="e1",
        session_id="sess-1",
        task="inspect_harbor/terminal_bench_2_0",
        sample_id="winning-avg-corewars",
        epoch=1,
        agent_name="react",
        started_at=0.0,
        target=TargetAddress(socket_path=Path("/tmp/test.sock")),
    )
    app = _harness(lambda: SessionHeaderWidget(row))
    async with app.run_test() as pilot:
        await pilot.pause()
        meta = _chip_plain(app.query_one("#meta-text", Static))
        assert "task: terminal_bench_2_0" in meta
        assert "inspect_harbor" not in meta


@skip_if_trio
@pytest.mark.anyio
async def test_session_header_tokens_chip_updates_via_set_usage() -> None:
    """``set_usage`` re-renders the meta row with a tokens chip.

    Uses dim labels + normal-weight values — same hierarchy as the
    other meta fields. Tokens chip omits the denominator when context
    size is unknown.
    """
    from pathlib import Path

    from inspect_ai.agent._acp.discovery import TargetAddress
    from inspect_ai.agent._acp.tui.client import SessionRow
    from inspect_ai.agent._acp.tui.state import UsageState
    from inspect_ai.agent._acp.tui.widgets.header import SessionHeaderWidget

    row = SessionRow(
        eval_id="e1",
        session_id="sess-1",
        task="suite/task",
        sample_id="s1",
        epoch=1,
        agent_name="react",
        started_at=0.0,
        target=TargetAddress(socket_path=Path("/tmp/test.sock")),
    )
    app = _harness(lambda: SessionHeaderWidget(row))
    async with app.run_test() as pilot:
        await pilot.pause()
        header = app.query_one(SessionHeaderWidget)
        assert "tokens" not in _chip_plain(header.query_one("#meta-text", Static))
        header.set_usage(UsageState(used=12_400, size=200_000))
        await pilot.pause()
        meta = _chip_plain(header.query_one("#meta-text", Static))
        # Used-only — context window denominator dropped.
        assert "tokens 12K" in meta
        assert "/" not in meta.split("tokens", 1)[1]


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
async def test_tool_call_appended_content_preserves_existing_widget() -> None:
    """Appending a content item must not tear down already-mounted items.

    The previous wholesale-rebuild path made every existing content
    block flash whenever a new block arrived. The append-only path
    keeps the first widget's identity stable; only the new block is
    mounted.
    """
    tool = ToolCallState(
        tool_call_id="tc-1",
        title="bash ls",
        status="in_progress",
        content=[_FakeContentBlock("first")],
    )

    app = _harness(lambda: ToolCallWidget(tool))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ToolCallWidget)
        body = widget.query_one(".body")
        original_wrappers = list(body.query(".content-item"))
        assert len(original_wrappers) == 1
        first_wrapper = original_wrappers[0]

        # Append a second content item — should mount a new wrapper
        # without disturbing the first one.
        tool.content = [_FakeContentBlock("first"), _FakeContentBlock("second")]
        widget.update_state(tool)
        await pilot.pause()

        wrappers = list(body.query(".content-item"))
        assert len(wrappers) == 2
        assert wrappers[0] is first_wrapper, (
            "first content wrapper was remounted (would flash on every chunk)"
        )


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_same_length_content_replacement_repaints() -> None:
    """ACP progress content has REPLACE semantics — same-length swaps repaint.

    Regression for P2 from review: the previous length-only
    fingerprint missed ``"abc" → "xyz"`` style replacements, so the
    body kept the stale text. The hash-based fingerprint now picks
    up content changes regardless of length.
    """
    tool = ToolCallState(
        tool_call_id="tc-1",
        title="bash ls",
        status="in_progress",
        content=[_FakeContentBlock("abc")],
    )

    app = _harness(lambda: ToolCallWidget(tool))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ToolCallWidget)
        from inspect_ai.agent._acp.tui.widgets._collapsible import (
            CollapsibleContent as _CollapsibleContent,
        )

        cc_before = widget.query_one(_CollapsibleContent)
        assert cc_before._full_text == "abc"

        # Same-length replace — must trigger a repaint.
        tool.content = [_FakeContentBlock("xyz")]
        widget.update_state(tool)
        await pilot.pause()

        cc_after = widget.query_one(_CollapsibleContent)
        # Widget identity preserved (in-place update path), but text
        # actually swapped.
        assert cc_after is cc_before
        assert cc_after._full_text == "xyz"


@skip_if_trio
@pytest.mark.anyio
async def test_transcript_auto_scrolls_when_tool_output_grows_at_same_status() -> None:
    """Streaming tool output should follow live-tail at unchanged status.

    Regression for P3 from review: the transcript's fingerprint was
    just ``item.status``, so growing content with unchanged status
    didn't flip ``content_changed`` and the auto-scroll never fired.
    This drives TranscriptWidget.refresh_from() end-to-end with a
    ``scroll_end`` spy so the actual scroll-on-grow path is pinned,
    not just the fingerprint helper.
    """
    tool = ToolCallState(
        tool_call_id="tc-1",
        title="bash long",
        status="in_progress",
        content=[_FakeContentBlock("first chunk")],
    )
    state = SessionState()
    state._tool_calls_by_id["tc-1"] = tool
    state.items.append(tool)

    app = _harness(TranscriptWidget)
    async with app.run_test() as pilot:
        await pilot.pause()
        tr = app.query_one(TranscriptWidget)
        # Initial mount of the tool card — auto-scroll legitimately
        # fires here too because the widget appears for the first
        # time. Reset the spy AFTER the initial paint settles so the
        # assertion below only counts the scroll triggered by the
        # content-growth refresh.
        tr.refresh_from(state)
        await pilot.pause()

        scroll_calls: list[None] = []
        original_scroll_end = tr.scroll_end

        def _spy(*args: object, **kwargs: object) -> object:
            scroll_calls.append(None)
            return original_scroll_end(*args, **kwargs)

        tr.scroll_end = _spy

        # Grow the content — status stays ``in_progress``. With the
        # length-only fingerprint this used to be invisible to the
        # transcript and ``content_changed`` stayed False; the
        # comprehensive fingerprint should detect the change and the
        # auto-scroll path should run.
        tool.content = [_FakeContentBlock("first chunk\nsecond chunk\nthird chunk")]
        tr.refresh_from(state)
        # ``call_after_refresh`` schedules the scroll for after the
        # next refresh cycle — pause twice to let it fire.
        await pilot.pause()
        await pilot.pause()

        assert scroll_calls, (
            "TranscriptWidget.scroll_end was not invoked after the tool's "
            "content grew — auto-scroll regressed and live-tail tool output "
            "would silently stop following the bottom of the transcript"
        )


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_skips_body_rebuild_when_state_unchanged() -> None:
    """A no-op refresh must not touch the body at all.

    Notifications fire often (pending signals, sibling-message chunks);
    if the tool's state hasn't actually changed, update_state should
    leave the mounted body widgets untouched. Pins that the
    fingerprint-gate in ToolCallWidget keeps a no-op cheap.
    """
    from inspect_ai.agent._acp.tui.widgets._collapsible import (
        CollapsibleContent as _CollapsibleContent,
    )

    tool = ToolCallState(
        tool_call_id="tc-1",
        title="bash ls",
        status="in_progress",
        content=[_FakeContentBlock("hello")],
    )

    app = _harness(lambda: ToolCallWidget(tool))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ToolCallWidget)
        body = widget.query_one(".body")
        original_wrappers = list(body.query(".content-item"))
        assert len(original_wrappers) == 1
        original_wrapper = original_wrappers[0]
        original_inner = list(original_wrapper.children)
        # Capture the inner CollapsibleContent identity too — the
        # check above only sees the wrapper layer.
        assert isinstance(original_inner[0], _CollapsibleContent)

        # Same state — should be a no-op for the body.
        widget.update_state(tool)
        await pilot.pause()

        new_wrappers = list(body.query(".content-item"))
        assert len(new_wrappers) == 1
        assert new_wrappers[0] is original_wrapper
        assert list(new_wrappers[0].children) == original_inner


@skip_if_trio
@pytest.mark.anyio
async def test_transcript_updates_message_in_place_when_segments_extend() -> None:
    """Streaming chunks must extend the existing MessageWidget in place.

    Re-mounting would tear the bubble down and rebuild it on every
    chunk, producing a visible flash. The widget identity must be
    preserved across updates; only the inner segment content changes.
    """
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
        # in-place update (no remount).
        group.segments[-1].text = "hi there"
        tr.refresh_from(state)
        await pilot.pause()
        same_widget = tr.children[0]
        assert same_widget is first_widget
        from inspect_ai.agent._acp.tui.widgets._collapsible import (
            CollapsibleContent as _CollapsibleContent,
        )

        body_text = " ".join(
            cc._full_text for cc in same_widget.query(_CollapsibleContent)
        )
        assert "hi there" in body_text


# ---------------------------------------------------------------------------
# Status formatters (pure functions)
# ---------------------------------------------------------------------------


def test_status_state_enum_membership_is_phase_2_only() -> None:
    """Sanity guard: Phase 2 ships three states; later phases add more."""
    members = {s.value for s in StatusState}
    assert members == {"awaiting_input", "generating", "calling_tools"}
