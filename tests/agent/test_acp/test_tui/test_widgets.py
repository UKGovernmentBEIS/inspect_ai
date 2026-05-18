"""Pilot tests for the Phase 2 conversation widgets.

Module-level ``pytestmark = slow`` per the design-doc convention:
Pilot tests pay the Textual app-bootstrap cost; the fast unit loop
should stay sub-second.
"""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.containers import Vertical
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
        assert chip.strip() == "• user"


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
        assert chip.strip() == "• system"


@skip_if_trio
@pytest.mark.anyio
async def test_operator_user_message_gets_operator_class() -> None:
    """``user_source='operator'`` adds the ``.operator`` CSS class.

    The class is no longer load-bearing for background colour
    (backgrounds were removed; chip colour now carries operator-vs-
    input identity), but kept as a marker hook so future styling
    can target operator messages without restructuring composition.
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
    """Reasoning is a standalone click-to-expand block — no CollapsibleContent.

    Pins three decisions:
    - collapsed by default; only the ``reasoning`` link is visible
    - the link carries the same italic + underline + muted treatment
      ``CollapsibleContent.truncation-note`` uses, so the affordance
      reads consistently
    - no ``CollapsibleContent`` inside (no ``…N more lines`` text);
      the widget owns its own click-to-toggle expand via ``on_click``
    """
    from inspect_ai.agent._acp.tui.widgets._collapsible import CollapsibleContent

    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[
            Segment(kind="reasoning", text="thinking line 1\nthinking line 2"),
            Segment(kind="text", text="answer"),
        ],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        reasoning_blocks = list(mw.query(_ReasoningBlock))
        assert len(reasoning_blocks) == 1
        block = reasoning_blocks[0]
        # Collapsed by default — body is hidden, only the link shows.
        assert block.has_class("collapsed")
        # Standalone widget — no CollapsibleContent wrapper, no "...
        # more lines" text.
        assert len(list(block.query(CollapsibleContent))) == 0
        # Link is present with the shared truncation-note treatment.
        link = block.query_one(".reasoning-link", Static)
        assert str(link.content) == "reasoning"
        # Body is mounted (so it's ready to reveal) but hidden via the
        # ``.collapsed`` class — assert it exists at all.
        assert len(list(block.query(".reasoning-body"))) == 1
        # No ^E binding leftover, no action_toggle_reasoning method.
        assert all(getattr(b, "key", None) != "ctrl+e" for b in block.BINDINGS)
        assert not hasattr(block, "action_toggle_reasoning")


@skip_if_trio
@pytest.mark.anyio
async def test_reasoning_block_collapsed_has_no_bottom_margin() -> None:
    """Collapsed reasoning sits flush — no margin, nothing below to push apart."""
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[
            Segment(kind="reasoning", text="thoughts"),
            Segment(kind="text", text="answer"),
        ],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(_ReasoningBlock)
        assert block.has_class("collapsed")
        assert block.styles.margin.bottom == 0


@skip_if_trio
@pytest.mark.anyio
async def test_reasoning_block_expanded_with_trailing_text_has_bottom_margin() -> None:
    """Expanded reasoning + following text → 1-row gap separates them."""
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[
            Segment(kind="reasoning", text="thoughts"),
            Segment(kind="text", text="answer"),
        ],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(_ReasoningBlock)
        block.on_click()
        await pilot.pause()
        assert not block.has_class("collapsed")
        assert block.styles.margin.bottom == 1


@skip_if_trio
@pytest.mark.anyio
async def test_reasoning_block_expanded_as_last_child_has_no_bottom_margin() -> None:
    """Reasoning-only message: expanded reasoning is :last-child → no margin.

    The 1-row gap would just stack against the message's own
    ``margin-bottom: 1`` and read as a wasted blank row.
    """
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="reasoning", text="thoughts")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(_ReasoningBlock)
        block.on_click()
        await pilot.pause()
        assert not block.has_class("collapsed")
        assert block.styles.margin.bottom == 0


@skip_if_trio
@pytest.mark.anyio
async def test_reasoning_block_click_toggles() -> None:
    """Click expands; click again collapses back to the resting link."""
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
        block.on_click()
        await pilot.pause()
        assert not block.has_class("collapsed")
        # Second click collapses back to the hidden state.
        block.on_click()
        await pilot.pause()
        assert block.has_class("collapsed")


@skip_if_trio
@pytest.mark.anyio
async def test_message_widget_has_bottom_margin_between_items() -> None:
    """Messages reserve a 1-row bottom margin for neighbour separation.

    Without it the next message or tool-call card sits flush against
    the message, which reads as one continuous block.
    """
    group = MessageGroup(message_id="m1", role="assistant")
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        assert mw.styles.margin.bottom == 1


# ---------------------------------------------------------------------------
# ToolCallWidget
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_renders_bullet_and_title() -> None:
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
        # Header is markup-rendered: coloured bullet, tool name bold,
        # args dim. Render to plain text so we can assert on what the
        # user actually sees.
        rendered = header.render_str(str(header.content)).plain
        assert rendered.startswith("• ")
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
        # The scroll is now debounced — pause long enough for the
        # debounce timer to expire AND for the pending callback to
        # actually run (one tick after the timer fires).
        from inspect_ai.agent._acp.tui.widgets.transcript import (
            _SCROLL_DEBOUNCE_SECONDS,
        )

        await pilot.pause(_SCROLL_DEBOUNCE_SECONDS + 0.05)
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


# ---------------------------------------------------------------------------
# Layout palette + spacing
# ---------------------------------------------------------------------------


def test_palette_is_role_to_color_only_no_backgrounds() -> None:
    """Pins the simplified palette: role identity rides on the chip colour.

    Backgrounds were dropped after the coloured header + indented body
    proved enough to distinguish speakers — change with intent.
    ``_PALETTE`` is now ``role -> hex string``, not a nested dict.
    """
    from inspect_ai.agent._acp.tui.widgets.message import _PALETTE

    assert set(_PALETTE.keys()) == {"system", "user", "operator", "assistant"}
    for role, fg in _PALETTE.items():
        assert isinstance(fg, str), f"{role} should map to a hex string"
        assert fg.startswith("#"), f"{role} fg should be a hex literal"


@skip_if_trio
@pytest.mark.anyio
async def test_message_widget_has_no_background_for_any_role() -> None:
    """No role tints the background — the chip colour carries identity.

    Textual reports an untinted widget as a transparent ``Color``;
    any of the previous hex backgrounds (e.g. ``#262d35``) would
    have been opaque, so ``is_transparent`` is the regression guard.
    """
    cases = [
        MessageGroup(message_id="m1", role="system"),
        MessageGroup(message_id="m2", role="user", user_source="input"),
        MessageGroup(message_id="m3", role="user", user_source="operator"),
        MessageGroup(message_id="m4", role="assistant"),
    ]
    for group in cases:
        app = _harness(lambda g=group: MessageWidget(g))
        async with app.run_test() as pilot:
            await pilot.pause()
            mw = app.query_one(MessageWidget)
            assert mw.styles.background.is_transparent, (
                f"{group.role}: unexpected background {mw.styles.background!r}"
            )


@skip_if_trio
@pytest.mark.anyio
async def test_chip_markup_applies_role_color_to_bullet_and_role_word() -> None:
    """Per-role colour from _PALETTE wraps both the bullet and the role word.

    Pins the palette decisions — a future tweak that accidentally
    drops the colour from either the bullet or the role word will
    fail this assertion. Test reads RAW markup (not plain text)
    because the colour is what we're validating.
    """
    from inspect_ai.agent._acp.tui.widgets.message import _PALETTE

    cases = [
        ("system", MessageGroup(message_id="m1", role="system"), "system"),
        (
            "user",
            MessageGroup(message_id="m2", role="user", user_source="input"),
            "user",
        ),
        (
            "operator",
            MessageGroup(message_id="m3", role="user", user_source="operator"),
            "user",
        ),
        ("assistant", MessageGroup(message_id="m4", role="assistant"), "assistant"),
    ]
    for key, group, role_word in cases:
        fg = _PALETTE[key]
        app = _harness(lambda g=group: MessageWidget(g))
        async with app.run_test() as pilot:
            await pilot.pause()
            chip = app.query_one(MessageWidget).query_one(".chip", Static)
            raw = str(chip.content)
            assert f"[{fg}]" in raw, f"{key}: bullet missing {fg} in {raw!r}"
            assert f"[bold {fg}]{role_word}[/]" in raw, (
                f"{key}: role word missing colour in {raw!r}"
            )


@skip_if_trio
@pytest.mark.anyio
async def test_message_body_has_left_padding_aligning_with_role_word() -> None:
    """Body padding-left == 2 so content sits under the role word, not the bullet."""
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[Segment(kind="text", text="answer")],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one(MessageWidget).query_one(".body", Vertical)
        assert body.styles.padding.left == 2


@skip_if_trio
@pytest.mark.anyio
async def test_message_widget_does_not_mount_segment_spacers() -> None:
    """Reasoning → text transitions sit flush — no 1-row spacer widget."""
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        segments=[
            Segment(kind="reasoning", text="planning"),
            Segment(kind="text", text="here we go"),
        ],
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        mw = app.query_one(MessageWidget)
        assert len(list(mw.query(".segment-spacer"))) == 0
        # And the body never gets the ``with-content`` toggle class.
        body = mw.query_one(".body", Vertical)
        assert not body.has_class("with-content")


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_header_has_blank_row_below_title() -> None:
    """Header reserves a 1-row gap before the first body item.

    Without it the code block / plan / output sits flush against the
    title, which reads as one continuous block rather than "title,
    then body".
    """
    state = ToolCallState(
        tool_call_id="tc-1",
        title="read /etc/hosts",
        kind="read",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        header = app.query_one(ToolCallWidget).query_one(".header", Static)
        assert header.styles.padding.bottom == 1


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_body_is_indented_under_tool_name() -> None:
    """Body has ``padding-left: 2`` — content lines up under the tool name (not the bullet).

    Parallel to MessageWidget's body indent: bullet sits in its own
    column, body sits under the role/tool word.
    """
    from textual.containers import Vertical

    state = ToolCallState(
        tool_call_id="tc-1",
        title="read /etc/hosts",
        kind="read",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.query_one(ToolCallWidget).query_one(".body", Vertical)
        assert body.styles.padding.left == 2


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_footer_is_indented_under_tool_name() -> None:
    """Footer also indents under the tool name so the whole row reads as one column."""
    state = ToolCallState(
        tool_call_id="tc-1",
        title="bash ls",
        kind="execute",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(ToolCallWidget).query_one(".footer", Static)
        assert footer.styles.padding.left == 2


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_has_no_border() -> None:
    """No card border — status is carried by the footer glyph alone.

    Pins the visual decision that tool calls share the message
    widget's flush layout rather than being chrome-wrapped cards.
    """
    state = ToolCallState(
        tool_call_id="tc-1",
        title="bash ls",
        kind="execute",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(ToolCallWidget)
        # styles.border is a Border-tuple-like; "none" / empty type
        # is the absence-of-border signal across status classes.
        for edge in ("top", "right", "bottom", "left"):
            border_type = getattr(w.styles.border, edge)[0]
            assert border_type in ("", "none", None), (
                f"{edge} border should be absent, got {border_type!r}"
            )


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_header_uses_tool_bullet_color() -> None:
    """Bullet in the header carries ``_TOOL_BULLET_COLOR`` markup.

    Pins the palette decision so a future tweak is intentional.
    """
    from inspect_ai.agent._acp.tui.widgets.tool_call import _TOOL_BULLET_COLOR

    state = ToolCallState(
        tool_call_id="tc-1",
        title="bash ls",
        kind="execute",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        raw = str(app.query_one(ToolCallWidget).query_one(".header", Static).content)
        assert f"[{_TOOL_BULLET_COLOR}]•[/]" in raw


@skip_if_trio
@pytest.mark.anyio
async def test_tool_call_footer_does_not_repeat_esc_to_interrupt_hint() -> None:
    """The cancel hint lives in the composer placeholder, not per-tool.

    Pins the single-source-of-truth decision: while
    ``lifecycle == "running"`` the placeholder reads
    "type a message · esc to interrupt", so repeating the hint on
    every tool-call card is noise.
    """
    state = ToolCallState(
        tool_call_id="tc-1",
        title="bash",
        kind="execute",
        status="in_progress",
    )
    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(ToolCallWidget).query_one(".footer", Static)
        assert "esc to interrupt" not in str(footer.content)


@skip_if_trio
@pytest.mark.anyio
async def test_assistant_chip_does_not_repeat_esc_to_interrupt_hint() -> None:
    """Same single-source-of-truth rule for the assistant chip."""
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        model="my-model",
        pending=True,
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        chip = app.query_one(MessageWidget).query_one(".chip", Static)
        assert "esc to interrupt" not in str(chip.content)


@skip_if_trio
@pytest.mark.anyio
async def test_completed_assistant_chip_drops_retry_and_elapsed() -> None:
    """When pending flips False, retry counter + elapsed disappear.

    Once the generation is done, the live progress indicators are
    historical noise (and elapsed would keep growing on every
    subsequent re-render since pending_started_at never resets).
    """
    import time as _time

    group = MessageGroup(
        message_id="m1",
        role="assistant",
        model="my-model",
        pending=False,
        retries=3,
        pending_started_at=_time.monotonic() - 5.0,
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = str(app.query_one(MessageWidget).query_one(".chip", Static).content)
        assert "retry" not in rendered
        assert "(" not in rendered  # no parens-note at all
        # And no elapsed marker either — the "· " dot-separator should
        # only appear before the model name.
        assert rendered.count("·") == 1


# ---------------------------------------------------------------------------
# Inline approval section
# ---------------------------------------------------------------------------


def _approval_request(
    tool_call_id: str = "tc-1",
    *,
    title: str = "bash ls",
    options: list[tuple[str, str]] | None = None,
    content_blocks=None,
):
    """Build a RequestPermissionRequest for pilot tests."""
    from acp.schema import (
        ContentToolCallContent,
        PermissionOption,
        RequestPermissionRequest,
        TextContentBlock,
        ToolCallUpdate,
    )

    opts_pairs = options or [("approve", "allow_once"), ("reject", "reject_once")]
    perm_options = [
        PermissionOption(
            option_id=oid,
            name=oid.capitalize(),
            kind=kind,  # type: ignore[arg-type]
        )
        for oid, kind in opts_pairs
    ]
    if content_blocks is None:
        content_blocks = [
            ContentToolCallContent(
                type="content",
                content=TextContentBlock(type="text", text="**Assistant**\n\nrun ls"),
            ),
        ]
    tc = ToolCallUpdate(
        tool_call_id=tool_call_id,
        title=title,
        status="pending",
        raw_input={"command": "ls"},
        content=content_blocks,
    )
    return RequestPermissionRequest(
        session_id="sid", tool_call=tc, options=perm_options
    )


def _pending_approval(req, event=None):
    import asyncio

    from inspect_ai.agent._acp.tui.state import PendingApproval

    return PendingApproval(request=req, event=event or asyncio.Event())


@skip_if_trio
@pytest.mark.anyio
async def test_approval_content_renders_diff_content_variant() -> None:
    """A ``FileEditToolCallContent`` block in the request renders as a diff."""
    from acp.schema import FileEditToolCallContent

    from inspect_ai.agent._acp.tui.widgets.tool_call import _ApprovalContent

    diff = FileEditToolCallContent(
        type="diff",
        path="/tmp/a.txt",
        old_text="alpha\nbeta",
        new_text="gamma\ndelta",
    )
    req = _approval_request(content_blocks=[diff])
    state = ToolCallState(tool_call_id="tc-1", title="edit", status="pending")
    state.pending_approval = _pending_approval(req)

    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        section = app.query_one(_ApprovalContent)
        old_lines = [str(s.content) for s in section.query(".diff-old")]
        new_lines = [str(s.content) for s in section.query(".diff-new")]
        headers = [str(s.content) for s in section.query(".diff-header")]
        # Confirm diff renderer was invoked — not a stringified blob.
        assert any("alpha" in line for line in old_lines)
        assert any("gamma" in line for line in new_lines)
        assert any("/tmp/a.txt" in h for h in headers)


@skip_if_trio
@pytest.mark.anyio
async def test_approval_content_renders_terminal_content_variant() -> None:
    """A ``TerminalToolCallContent`` block in the request renders as terminal placeholder."""
    from acp.schema import TerminalToolCallContent

    from inspect_ai.agent._acp.tui.widgets.tool_call import _ApprovalContent

    term = TerminalToolCallContent(type="terminal", terminal_id="t-42")
    req = _approval_request(content_blocks=[term])
    state = ToolCallState(tool_call_id="tc-1", title="bash", status="pending")
    state.pending_approval = _pending_approval(req)

    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        section = app.query_one(_ApprovalContent)
        body_text = " ".join(str(s.content) for s in section.query(".body-content"))
        assert "[terminal: t-42]" in body_text


@skip_if_trio
@pytest.mark.anyio
async def test_decision_appears_on_footer_after_resolve() -> None:
    """After resolve_approval, the content section unmounts and the decision suffixes the footer.

    Compact layout: the post-resolution decision (``approved by
    you`` / ``denied by you`` / ``cancelled``) appears inline on
    the same row as the tool's status glyph + duration. Saves a
    row vs. a separate summary line, and groups "what happened
    with this tool call" (it ran AND who approved it) in one
    anchor.
    """
    from inspect_ai.agent._acp.tui.widgets.tool_call import _ApprovalContent

    state = ToolCallState(tool_call_id="tc-1", title="bash", status="pending")
    state.pending_approval = _pending_approval(_approval_request())

    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ToolCallWidget)
        # Content section mounted while pending.
        assert len(widget.query(_ApprovalContent)) == 1
        # Footer has NO decision suffix yet.
        footer_before = str(widget.query_one(".footer", Static).content)
        assert "approved by you" not in footer_before
        assert "denied" not in footer_before

        # Mutate state and re-apply (mirrors what SessionScreen does
        # after state.resolve_approval).
        state.pending_approval = None
        state.last_approval_decision = "approved"
        widget.update_state(state)
        await pilot.pause()

        # Content section gone.
        assert len(widget.query(_ApprovalContent)) == 0
        # No separate summary widget either — decision lives on
        # the footer now.
        assert len(widget.query(".decision-summary")) == 0
        # Decision suffix renders on the footer row.
        footer_after = str(widget.query_one(".footer", Static).content)
        assert "approved by you" in footer_after


def test_fingerprint_changes_when_pending_approval_is_set() -> None:
    """Setting ``pending_approval`` flips the tool fingerprint.

    Pinned regression: without including approval state in the
    fingerprint, the TranscriptWidget's mounted-snapshot gate
    skips ``update_state()`` when ONLY approval state changes —
    leaving the inline approval section unmounted on a card that
    received a permission request between status updates.
    """
    from inspect_ai.agent._acp.tui.state import ToolCallState
    from inspect_ai.agent._acp.tui.widgets._fingerprint import (
        tool_state_fingerprint,
    )

    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    before = tool_state_fingerprint(tc)

    # Mimic the wire shape consume_approval_request would attach.
    tc.pending_approval = _pending_approval(_approval_request())
    after = tool_state_fingerprint(tc)
    assert before != after


def test_fingerprint_changes_when_pending_clears_to_decided() -> None:
    """Clearing ``pending_approval`` + setting ``last_approval_decision`` flips the fingerprint.

    Without this, the operator's button click would resolve the
    state but the card would never re-render — buttons stay
    visible until some other state change (status/content) happens
    to invalidate the snapshot.
    """
    from inspect_ai.agent._acp.tui.state import ToolCallState
    from inspect_ai.agent._acp.tui.widgets._fingerprint import (
        tool_state_fingerprint,
    )

    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    tc.pending_approval = _pending_approval(_approval_request())
    pending_sig = tool_state_fingerprint(tc)

    tc.pending_approval = None
    tc.last_approval_decision = "approved"
    resolved_sig = tool_state_fingerprint(tc)
    assert pending_sig != resolved_sig


def test_fingerprint_changes_between_different_decisions() -> None:
    """Different post-resolution decision labels yield distinct fingerprints.

    The footer's coloured decision suffix is user-visible — a
    transition from ``approved`` to ``denied`` (e.g. via a
    follow-up tool call's resolve path) must invalidate the
    snapshot so the suffix re-renders.
    """
    from inspect_ai.agent._acp.tui.state import ToolCallState
    from inspect_ai.agent._acp.tui.widgets._fingerprint import (
        tool_state_fingerprint,
    )

    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="completed")
    tc.last_approval_decision = "approved"
    approved_sig = tool_state_fingerprint(tc)
    tc.last_approval_decision = "denied"
    denied_sig = tool_state_fingerprint(tc)
    assert approved_sig != denied_sig


def test_is_separator_block_matches_producer_shape() -> None:
    """``_is_separator_block`` recognises the exact wire shape ``_separator_block`` emits.

    Pinned because the recogniser drives a CSS-class choice that
    tightens the spacing around the rule. If the producer changes
    the separator's text and the recogniser doesn't follow, the
    rule reverts to the wide-margin wrapper and the operator sees
    a double-spaced divider.
    """
    from acp.schema import ContentToolCallContent, TextContentBlock

    from inspect_ai.agent._acp.tui.widgets.tool_call import _is_separator_block

    # The exact shape emitted by ``approval/_human/acp.py:_separator_block``.
    sep = ContentToolCallContent(
        type="content",
        content=TextContentBlock(type="text", text="---"),
    )
    assert _is_separator_block(sep) is True

    # Tolerant of surrounding whitespace too — defensive against
    # historical / future producers that wrap with \n.
    sep_with_ws = ContentToolCallContent(
        type="content",
        content=TextContentBlock(type="text", text="\n---\n"),
    )
    assert _is_separator_block(sep_with_ws) is True

    # Non-separator content blocks return False.
    normal = ContentToolCallContent(
        type="content",
        content=TextContentBlock(type="text", text="**Assistant**\n\nhello"),
    )
    assert _is_separator_block(normal) is False

    # Diff / terminal variants are never separators.
    from acp.schema import FileEditToolCallContent

    diff = FileEditToolCallContent(
        type="diff", path="/tmp/a.txt", old_text="x", new_text="y"
    )
    assert _is_separator_block(diff) is False


@skip_if_trio
@pytest.mark.anyio
async def test_approval_area_sizes_to_content_not_remaining_space() -> None:
    """``#approval-area`` Vertical takes its content's height, not ``1fr``.

    Pinned regression: Textual's ``Vertical`` defaults to ``height: 1fr``
    (fills available space). Without an explicit ``height: auto`` on the
    approval-area wrapper, the area claimed the rest of the card's
    available vertical space, pushing the tool's body content down
    past a giant empty gap.

    Asserted with slack: a few rows for child margins is fine, but
    egregious expansion (the 1fr-fills-screen bug) is not.
    """
    from textual.containers import Vertical

    # Resolved state — approval area is EMPTY (decision lives on
    # the footer now). With the 1fr bug the area would still claim
    # the rest of the screen even with no children; with the fix
    # it collapses to zero rows.
    state_done = ToolCallState(
        tool_call_id="tc-done", title="bash", status="in_progress"
    )
    state_done.last_approval_decision = "approved"
    app = _harness(lambda: ToolCallWidget(state_done))
    async with app.run_test() as pilot:
        await pilot.pause()
        area = app.query_one("#approval-area", Vertical)
        # Hard ceiling: a couple of rows max. The 1fr-runaway bug
        # would put us at 20+.
        assert area.region.height <= 2, (
            f"#approval-area height ({area.region.height}) is way "
            f"larger than its empty content — the Vertical's 1fr "
            f"default is back."
        )

    # Pending state — approval section is mounted. Content here is
    # naturally taller (intro + content blocks + buttons), but the
    # area should still match what the section actually renders, not
    # expand beyond it. Slack accounts for the section's own
    # margin-bottom.
    state_pending = ToolCallState(
        tool_call_id="tc-pend", title="bash", status="pending"
    )
    state_pending.pending_approval = _pending_approval(_approval_request())
    app = _harness(lambda: ToolCallWidget(state_pending))
    async with app.run_test() as pilot:
        await pilot.pause()
        area = app.query_one("#approval-area", Vertical)
        content_height = sum(child.region.height for child in area.children)
        # Slack of 3 rows for any margins (margin-bottom on the
        # section + any wrapper padding); a 1fr runaway would
        # exceed this by an order of magnitude.
        assert area.region.height <= content_height + 3, (
            f"#approval-area height ({area.region.height}) exceeds "
            f"its content height ({content_height}) by more than the "
            f"margin slack — the Vertical's 1fr default is back."
        )


@skip_if_trio
@pytest.mark.anyio
async def test_tool_card_has_approval_css_class_while_pending() -> None:
    """The ``.approval`` CSS class is added to the card while pending_approval is set."""
    state = ToolCallState(tool_call_id="tc-1", title="bash", status="pending")
    state.pending_approval = _pending_approval(_approval_request())

    app = _harness(lambda: ToolCallWidget(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ToolCallWidget)
        assert "approval" in widget.classes

        # Mutate state → class removed.
        state.pending_approval = None
        state.last_approval_decision = "approved"
        widget.update_state(state)
        await pilot.pause()
        assert "approval" not in widget.classes


# ---------------------------------------------------------------------------
# Composer-area approval bar (_ApprovalBar)
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_approval_bar_hidden_when_no_pending() -> None:
    """Bar carries the ``-hidden`` class when no approval is pending."""
    from inspect_ai.agent._acp.tui.widgets.approval_bar import _ApprovalBar

    state = SessionState()
    app = _harness(lambda: _ApprovalBar(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        assert "-hidden" in bar.classes


@skip_if_trio
@pytest.mark.anyio
async def test_approval_bar_visible_when_pending_arrives() -> None:
    """``consume_approval_request`` makes the bar visible via its subscription."""
    from inspect_ai.agent._acp.tui.widgets.approval_bar import _ApprovalBar

    state = SessionState()
    app = _harness(lambda: _ApprovalBar(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        assert "-hidden" in bar.classes

        state.consume_approval_request(_pending_approval(_approval_request()))
        await pilot.pause()
        assert "-hidden" not in bar.classes


@skip_if_trio
@pytest.mark.anyio
async def test_approval_bar_mounts_action_per_option() -> None:
    """One ``_ApprovalAction`` per option with the standard ``approve-opt-<id>`` ids."""
    from inspect_ai.agent._acp.tui.widgets.approval_bar import (
        _ApprovalAction,
        _ApprovalBar,
    )

    state = SessionState()
    state.consume_approval_request(
        _pending_approval(
            _approval_request(
                options=[
                    ("approve", "allow_once"),
                    ("reject", "reject_once"),
                    ("terminate", "reject_always"),
                ],
            )
        )
    )
    app = _harness(lambda: _ApprovalBar(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        ids = [a.id for a in bar.query(_ApprovalAction)]
        assert ids == [
            "approve-opt-approve",
            "approve-opt-reject",
            "approve-opt-terminate",
        ]


@skip_if_trio
@pytest.mark.anyio
async def test_approval_bar_first_action_is_focused_on_mount() -> None:
    """First action focused so Tab+Enter works without a click."""
    from inspect_ai.agent._acp.tui.widgets.approval_bar import (
        _ApprovalAction,
        _ApprovalBar,
    )

    state = SessionState()
    state.consume_approval_request(_pending_approval(_approval_request()))
    app = _harness(lambda: _ApprovalBar(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        first = bar.query(_ApprovalAction).first()
        assert first is not None
        # Textual's focus chain may not have transferred yet under
        # the test event loop — accept either the widget's own focus
        # flag or the app-level focused pointer.
        assert first.has_focus or app.focused is first


@skip_if_trio
@pytest.mark.anyio
async def test_approval_bar_clicking_action_posts_decision_message() -> None:
    """Pilot-click on Approve → ``ApprovalDecisionRequested`` bubbles up; state resolves."""
    from inspect_ai.agent._acp.tui.widgets.approval_bar import _ApprovalBar
    from inspect_ai.agent._acp.tui.widgets.tool_call import ApprovalDecisionRequested

    state = SessionState()
    pending = _pending_approval(_approval_request())
    state.consume_approval_request(pending)
    tc = state._tool_calls_by_id["tc-1"]

    received: list[ApprovalDecisionRequested] = []

    class _ActionHostApp(App[None]):
        def compose(self) -> ComposeResult:
            yield _ApprovalBar(state)

        def on_approval_decision_requested(
            self, message: ApprovalDecisionRequested
        ) -> None:
            received.append(message)
            state.resolve_approval(message.tool_call_id, option_id=message.option_id)
            message.stop()

    app = _ActionHostApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        await pilot.click(bar.query_one("#approve-opt-approve"))
        await pilot.pause()

    assert len(received) == 1
    assert received[0].option_id == "approve"
    assert received[0].tool_call_id == "tc-1"
    assert tc.pending_approval is None
    assert tc.last_approval_decision == "approved"
    assert pending.event.is_set()
    assert pending.chosen_option_id == "approve"


@skip_if_trio
@pytest.mark.anyio
async def test_approval_bar_hides_after_resolve() -> None:
    """Resolving the pending approval re-hides the bar via the state subscription."""
    from inspect_ai.agent._acp.tui.widgets.approval_bar import _ApprovalBar

    state = SessionState()
    state.consume_approval_request(_pending_approval(_approval_request()))
    app = _harness(lambda: _ApprovalBar(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        assert "-hidden" not in bar.classes

        state.resolve_approval("tc-1", option_id="approve")
        await pilot.pause()
        assert "-hidden" in bar.classes


@skip_if_trio
@pytest.mark.anyio
async def test_approval_action_pressed_carries_mounted_tool_call_id() -> None:
    """``Pressed`` carries the tool_call_id active at mount time.

    Pinned because the bar previously dispatched via
    ``current_pending_tool_call_id()`` at handler time, which races
    when parallel approvals queue up: a click on the FIRST approval
    could resolve as if it applied to the SECOND if the first cleared
    between click capture and message dispatch.
    """
    from inspect_ai.agent._acp.tui.widgets.approval_bar import (
        _ApprovalAction,
        _ApprovalBar,
    )

    state = SessionState()
    state.consume_approval_request(_pending_approval(_approval_request("tc-1")))
    app = _harness(lambda: _ApprovalBar(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        action = bar.query_one("#approve-opt-approve", _ApprovalAction)
        # The action's bound tool_call_id should match its mount-time
        # request, not a fresh state lookup.
        assert action._tool_call_id == "tc-1"
        # The Pressed message built by action_press carries the same id.
        msg = _ApprovalAction.Pressed(action._tool_call_id, action._option_id)
        assert msg.tool_call_id == "tc-1"
        assert msg.option_id == "approve"


@skip_if_trio
@pytest.mark.anyio
async def test_approval_bar_drops_stale_press_for_resolved_tool_call() -> None:
    """The bar's handler must drop a press whose carried id no longer matches.

    Pinned because a queued click / Enter that lands after the first
    approval already resolved would otherwise apply to the NEXT
    pending approval (different tool_call_id) — silently approving
    something the operator never clicked on.

    Validation point: ``on_approval_action_pressed`` compares
    ``event.tool_call_id`` to ``state.current_pending_tool_call_id()``
    and short-circuits before posting an
    :class:`ApprovalDecisionRequested`. We exercise that gate by
    spying on ``post_message`` so we don't depend on the message bus
    plumbing for the assertion.
    """
    from inspect_ai.agent._acp.tui.widgets.approval_bar import (
        _ApprovalAction,
        _ApprovalBar,
    )
    from inspect_ai.agent._acp.tui.widgets.tool_call import ApprovalDecisionRequested

    state = SessionState()
    state.consume_approval_request(_pending_approval(_approval_request("tc-1")))

    app = _harness(lambda: _ApprovalBar(state))
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(_ApprovalBar)
        action_tc1 = bar.query_one("#approve-opt-approve", _ApprovalAction)
        assert action_tc1._tool_call_id == "tc-1"

        # Resolve tc-1 out of band (e.g. a fast keystroke or a second
        # client's response). The bar will re-render with no pending,
        # but a press that was already in flight could still land
        # carrying tc-1's id.
        state.resolve_approval("tc-1", option_id="approve")
        await pilot.pause()
        assert state.current_pending_tool_call_id() is None

        # Spy on post_message so we can assert the handler does NOT
        # fan out an ApprovalDecisionRequested for the stale press.
        posted: list[object] = []
        original_post = bar.post_message

        def _spy(message: object) -> bool:
            posted.append(message)
            return original_post(message)

        bar.post_message = _spy

        bar.on_approval_action_pressed(_ApprovalAction.Pressed("tc-1", "approve"))

        # The handler must early-return without posting anything.
        decisions = [m for m in posted if isinstance(m, ApprovalDecisionRequested)]
        assert decisions == [], (
            f"Stale press for resolved tc-1 was not dropped; posted={decisions!r}"
        )


@skip_if_trio
@pytest.mark.anyio
async def test_pending_assistant_chip_shows_retry_counter() -> None:
    """When retries > 0 and pending, the chip shows ``(retry N)`` alone.

    The "esc to interrupt" hint moved to the composer placeholder
    (single source of truth) — only the retry counter remains in
    the chip's parens-note.
    """
    group = MessageGroup(
        message_id="m1",
        role="assistant",
        model="my-model",
        pending=True,
        retries=3,
    )
    app = _harness(lambda: MessageWidget(group))
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = str(app.query_one(MessageWidget).query_one(".chip", Static).content)
        assert "(retry 3)" in rendered
        assert "esc to interrupt" not in rendered
