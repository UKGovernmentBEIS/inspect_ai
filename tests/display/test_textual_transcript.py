import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from rich.console import Console, Group
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from inspect_ai._display.textual.widgets.transcript import (
    TranscriptView,
    render_sentinel_event,
    render_sub_events,
)
from inspect_ai.dataset import Sample
from inspect_ai.event import (
    CommunicationDelivery,
    CommunicationEvent,
    CommunicationRecord,
    CommunicationRejection,
    CommunicationSend,
    CommunicationWait,
    Event,
    InfoEvent,
    SentinelEvent,
    SwarmEvent,
)
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


class _TranscriptApp(App[None]):
    def compose(self) -> ComposeResult:
        yield TranscriptView()


async def _textual_output(events: list[Event], *, nested: bool = False) -> str:
    """The terminal output of the Textual transcript widgets for ``events``.

    ``nested`` renders them as the sub-events of another event.
    """
    app = _TranscriptApp()
    async with app.run_test(size=(400, 40)) as pilot:
        view = app.query_one(TranscriptView)
        widgets: list[Widget] = (
            [Static(Group(*render_sub_events(events)))]
            if nested
            else view._widgets_for_events(events)
        )
        await view.mount_all(widgets)
        await pilot.pause()
        return "".join(
            widget.render_line(y).render(app.console)
            for widget in widgets
            for y in range(widget.size.height)
        )


# ESC/CSI, C1 CSI and bidi controls, markup-looking text, a lone surrogate and
# ordinary Unicode
_HOSTILE = "a\x1b[2Jb\x9bc\u202ed [/red] [bold]x[/bold] \ud800 é"
_SHOWN = "abcd [/red] [bold]x[/bold] \\ud800 é"
# JSON already escapes C0 controls, so data shows ESC as `\u001b`
_SHOWN_IN_DATA = "a\\u001b[2Jbcd [/red] [bold]x[/bold] \\ud800 é"

_SGR = re.compile(r"\x1b\[[0-9;]*m")
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def _communication(**kwargs: Any) -> CommunicationEvent:
    fields: dict[str, Any] = dict(
        kind="sent",
        source="inspect_swarm",
        agent="a",
        channel="bus",
        record_ids=["w-1"],
        send=CommunicationSend(
            record=CommunicationRecord(id="w-1", kind="message", sender="a")
        ),
    )
    fields.update(kwargs)
    return CommunicationEvent(**fields)


def _record(**kwargs: Any) -> CommunicationSend:
    fields: dict[str, Any] = dict(kind="message", sender="a")
    fields.update(kwargs)
    return CommunicationSend(record=CommunicationRecord(**fields))


def _refused(control: str = "rate", reason: str = "slow") -> CommunicationSend:
    return CommunicationSend(
        record=CommunicationRecord(kind="message", sender="a"),
        rejected=CommunicationRejection(control=control, reason=reason),
    )


def _wait(**kwargs: Any) -> CommunicationEvent:
    fields: dict[str, Any] = (
        dict(channels=["bus"], outcome="news", duration=1.0) | kwargs
    )
    return _communication(
        kind="waited",
        channel=None,
        record_ids=[],
        send=None,
        wait=CommunicationWait(**fields),
    )


def _delivered(**kwargs: Any) -> CommunicationEvent:
    return _communication(
        kind="delivered", send=None, delivery=CommunicationDelivery(**kwargs)
    )


_LINES: list[tuple[str, Event, str]] = [
    ("sent agent", _communication(agent=_HOSTILE), _SHOWN),
    ("sent channel", _communication(channel=_HOSTILE), _SHOWN),
    (
        "sent record kind",
        _communication(record_ids=[], send=_record(kind=_HOSTILE)),
        _SHOWN,
    ),
    (
        "sent record id",
        _communication(record_ids=[_HOSTILE], send=_record(id=_HOSTILE)),
        _SHOWN,
    ),
    ("sent to", _communication(record_ids=[], send=_record(to=[_HOSTILE])), _SHOWN),
    (
        "sent content",
        _communication(record_ids=[], send=_record(content=_HOSTILE)),
        _SHOWN,
    ),
    (
        "refused control",
        _communication(record_ids=[], send=_refused(control=_HOSTILE)),
        _SHOWN,
    ),
    (
        "refused reason",
        _communication(record_ids=[], send=_refused(reason=_HOSTILE)),
        _SHOWN,
    ),
    ("delivered recipients", _delivered(recipients=[_HOSTILE], seq=1), _SHOWN),
    (
        "read record ids",
        _communication(kind="read", send=None, record_ids=[_HOSTILE]),
        _SHOWN,
    ),
    ("wait channels", _wait(channels=[_HOSTILE]), _SHOWN),
    ("wait outcome", _wait(outcome=_HOSTILE), _SHOWN),
    ("swarm member", SwarmEvent(kind="final", member=_HOSTILE, data={}), _SHOWN),
    ("swarm kind", SwarmEvent(kind=_HOSTILE, data={}), f"swarm: {_SHOWN}"),
    ("swarm data", SwarmEvent(kind="final", data={"note": _HOSTILE}), _SHOWN_IN_DATA),
]


@skip_if_trio
@pytest.mark.anyio
@pytest.mark.parametrize("nested", [False, True], ids=["top", "nested"])
@pytest.mark.parametrize(
    "event,shown", [line[1:] for line in _LINES], ids=[line[0] for line in _LINES]
)
async def test_event_text_reaches_terminal_literally_and_safely(
    event: Event, shown: str, nested: bool
) -> None:
    output = await _textual_output([event], nested=nested)
    output.encode("utf-8")
    text = _SGR.sub("", output)
    assert shown in text
    assert _CONTROLS.search(text) is None
