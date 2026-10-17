from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import cast

import pytest
from rich.console import Console, Group

from inspect_ai._display.textual.widgets.transcript import (
    TranscriptView,
    render_sentinel_event,
)
from inspect_ai.dataset import Sample
from inspect_ai.event import Event, InfoEvent, SentinelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log._samples import ActiveSample
from inspect_ai.log._transcript import Transcript


class _Sample:
    id = "sample"

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript


@pytest.mark.anyio
async def test_textual_transcript_view_uses_resident_events(monkeypatch) -> None:
    sample_init = SampleInitEvent(sample=Sample(input="input", id="sample"), state={})
    evicted = InfoEvent(data="evicted")
    resident = InfoEvent(data="resident")
    transcript = Transcript(
        [sample_init, evicted, resident], bounded=True, resident_tail=1
    )
    rendered_events: Sequence[Event] | None = None

    async def remove_children(self: TranscriptView) -> None:
        pass

    async def mount_all(self: TranscriptView, widgets: object) -> None:
        pass

    @asynccontextmanager
    async def batch(self: TranscriptView) -> AsyncIterator[None]:
        yield

    def scroll_end(self: TranscriptView, animate: bool = False) -> None:
        pass

    def widgets_for_events(
        self: TranscriptView, events: Sequence[Event]
    ) -> list[object]:
        nonlocal rendered_events
        rendered_events = events
        return []

    monkeypatch.setattr(TranscriptView, "remove_children", remove_children)
    monkeypatch.setattr(TranscriptView, "mount_all", mount_all)
    monkeypatch.setattr(TranscriptView, "_widgets_for_events", widgets_for_events)
    monkeypatch.setattr(TranscriptView, "batch", batch)
    monkeypatch.setattr(TranscriptView, "scroll_end", scroll_end)

    view = TranscriptView()
    view._active = True

    await view.sync_sample(cast(ActiveSample, _Sample(transcript)))

    assert rendered_events is transcript.history.resident_events
    assert rendered_events == [sample_init, resident]


def test_render_tool_event_hides_only_operator_cancelled_events() -> None:
    """Skipped halt_on_error calls share the `cancelled` error type but stay visible."""
    from inspect_ai._display.textual.widgets.transcript import render_tool_event
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.tool._tool_call import ToolCallError

    operator_cancelled = ToolEvent(
        id="a",
        function="computer",
        arguments={},
        result="",
        error=ToolCallError("cancelled", "Tool call cancelled by operator."),
        failed=True,
    )
    skipped = ToolEvent(
        id="b",
        function="computer",
        arguments={},
        result="",
        error=ToolCallError(
            "cancelled", "Not executed: an earlier computer action in this turn failed."
        ),
        failed=None,
    )
    assert render_tool_event(operator_cancelled) is None
    assert render_tool_event(skipped) is not None


def _sentinel_text(event: SentinelEvent) -> str:
    display = render_sentinel_event(event)
    assert isinstance(display.content, Group)
    console = Console(width=500, no_color=True)
    with console.capture() as capture:
        console.print(display.content)
    return capture.get().strip()


def test_render_sentinel_event_shows_monitor_text_literally() -> None:
    event = SentinelEvent(
        factory="d4_rule",
        path="[bold]guard[/bold]",
        function="check",
        step_id="call_1",
        conversation="c",
        stage="tool_call",
        kind="decision",
        status="reported",
        action="reject",
        message="no [red]rm[/red]",
        explanation="flagged [italic]this[/italic]",
    )
    assert _sentinel_text(event) == (
        "[bold]guard[/bold]: reject (flagged [italic]this[/italic]), "
        "told the agent: no [red]rm[/red]"
    )


@pytest.mark.parametrize(
    "suspicion,shown",
    [
        (0.75, "suspicion 0.75"),
        (1 / 3, "suspicion 0.33"),
        (
            {"exfiltration": 0.8, "sabotage": 0.1},
            "suspicion exfiltration 0.80, sabotage 0.10",
        ),
    ],
)
def test_render_sentinel_event_formats_suspicion(
    suspicion: float | dict[str, float], shown: str
) -> None:
    event = SentinelEvent(
        factory="d4_score",
        path="score",
        function="check",
        step_id="call_1",
        conversation="c",
        stage="tool_call",
        kind="observation",
        status="reported",
        suspicion=suspicion,
    )
    assert _sentinel_text(event) == f"score: observation, {shown}"
