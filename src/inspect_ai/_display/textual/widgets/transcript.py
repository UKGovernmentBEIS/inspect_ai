from typing import Any, Callable, NamedTuple, Sequence, Type

from pydantic import JsonValue
from pydantic_core import to_json
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.containers import ScrollableContainer
from textual.widget import Widget
from textual.widgets import Static

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.rich import tool_result_display
from inspect_ai._util.transcript import (
    content_display,
    set_transcript_markdown_options,
    transcript_function,
    transcript_markdown,
    transcript_reasoning,
    transcript_separator,
)
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._branch import BranchEvent
from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._error import ErrorEvent
from inspect_ai.event._event import (
    Event,
)
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._input import InputEvent
from inspect_ai.event._interrupt import InterruptEvent
from inspect_ai.event._logger import LoggerEvent
from inspect_ai.event._model import CANCEL_ERRORS, ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.event._score import ScoreEvent
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.event._subtask import SubtaskEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._samples import ActiveSample
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._render import messages_preceding_assistant, render_tool_calls
from inspect_ai.tool._tool import ToolResult


class TranscriptView(ScrollableContainer):
    DEFAULT_CSS = """
    TranscriptView {
        scrollbar-size-vertical: 1;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._sample_id: str | None = None
        self._sample_events: int | None = None

        self._active = False
        self._pending_sample: ActiveSample | None = None

    async def notify_active(self, active: bool) -> None:
        self._active = active
        if self._active and self._pending_sample:
            await self.sync_sample(self._pending_sample)
            self._pending_sample = None

    async def sync_sample(self, sample: ActiveSample | None) -> None:
        # if sample is none then reset
        if sample is None:
            self._sample = None
            self._sample_events = None
            await self.remove_children()

        # process sample if we are active
        elif self._active:
            # if we have either a new sample or a new event count then proceed
            if (
                sample.id != self._sample_id
                or len(sample.transcript.events) != self._sample_events
            ):
                # update (scrolling to end if we are already close to it)
                new_sample = sample.id != self._sample_id
                scroll_to_end = (
                    new_sample or abs(self.scroll_y - self.max_scroll_y) <= 20
                )

                async with self.batch():
                    await self.remove_children()
                    await self.mount_all(
                        self._widgets_for_events(sample.transcript.events)
                    )
                if scroll_to_end:
                    self.scroll_end(animate=not new_sample)

                # set members
                self._sample_id = sample.id
                self._sample_events = len(sample.transcript.events)

        # if we aren't active then save as a pending sample
        else:
            self._pending_sample = sample

    def _widgets_for_events(
        self, events: Sequence[Event], limit: int = 15
    ) -> list[Widget]:
        from rich.markdown import Markdown

        widgets: list[Widget] = []

        # function to append content
        def append_content(c: RenderableType) -> None:
            if isinstance(c, Markdown):
                set_transcript_markdown_options(c)
            widgets.append(Static(c, markup=False))

        # first set aside events we don't render
        filtered_events = [e for e in events if can_render_event(e)]

        # filter the events to the <limit> most recent
        if len(events) > limit:
            filtered_events = filtered_events[-limit:]

        # find the sample init event
        sample_init: SampleInitEvent | None = None
        for event in events:
            if isinstance(event, SampleInitEvent):
                sample_init = event
                break

        # add the sample init event if it isn't already in the event list
        if sample_init and sample_init not in filtered_events:
            filtered_events = [sample_init] + list(filtered_events)

        # compute how many events we filtered out
        filtered_count = len(events) - len(filtered_events)
        showed_filtered_count = False
        for event in filtered_events:
            display = render_event(event)
            if display:
                for d in display:
                    if d.content:
                        widgets.append(
                            Static(
                                transcript_separator(
                                    d.title, self.app.current_theme.primary
                                )
                            )
                        )
                        append_content(d.content)
                        widgets.append(Static(Text(" ")))

                        if not showed_filtered_count and filtered_count > 0:
                            showed_filtered_count = True

                            widgets.append(
                                Static(
                                    transcript_separator(
                                        f"{filtered_count} events..."
                                        if filtered_count > 1
                                        else "1 event...",
                                        self.app.current_theme.primary,
                                    )
                                )
                            )
                            widgets.append(Static(Text(" ")))

        return widgets


class EventDisplay(NamedTuple):
    """Display for an event group."""

    title: str
    """Text for title bar"""

    content: RenderableType | None = None
    """Optional custom content to display."""


def can_render_event(event: Event) -> bool:
    for event_type, _ in _renderers:
        if isinstance(event, event_type):
            return True
    return False


def render_event(event: Event) -> list[EventDisplay] | None:
    # see if we have a renderer
    for event_type, renderer in _renderers:
        if isinstance(event, event_type):
            display = renderer(event)
            if display is not None:
                return display if isinstance(display, list) else [display]

    # no renderer
    return None


def render_sample_init_event(event: SampleInitEvent) -> EventDisplay:
    # alias sample
    sample = event.sample

    # input
    messages: list[ChatMessage] = (
        [ChatMessageUser(content=sample.input)]
        if isinstance(sample.input, str)
        else sample.input
    )
    content: list[RenderableType] = []
    for message in messages:
        content.extend(render_message(message))

    # target
    if sample.target:
        content.append(Text())
        content.append(Text("Target", style="bold"))
        content.append(Text())
        content.append(str(sample.target).strip())

    return EventDisplay("sample init", Group(*content))


def render_sample_limit_event(event: SampleLimitEvent) -> EventDisplay:
    return EventDisplay(f"limit: {event.type}", Text(event.message))


def render_interrupt_event(event: InterruptEvent) -> EventDisplay:
    return EventDisplay(
        f"interrupt: {event.source}",
        Text(f"interrupted during {event.interrupted}"),
    )


def render_model_event(event: ModelEvent) -> EventDisplay | None:
    # Hide cancelled model events entirely (operator / limit / system).
    # The adjacent InterruptEvent communicates the cause; the cancelled
    # call has no useful assistant output to show.
    if event.error in CANCEL_ERRORS:
        return None

    content: list[RenderableType] = []

    # Render preceding non-tool messages (user/system context for this
    # generation). ``ChatMessageTool`` results are intentionally NOT
    # rendered here — each tool result has its own row via
    # ``render_tool_event``, so including it in the prefix would
    # duplicate that body every time a downstream model event walks
    # back through unconsumed tool messages (e.g. after a cancel).
    preceding = messages_preceding_assistant(event.input)
    for message in preceding:
        if isinstance(message, ChatMessageTool):
            continue
        content.extend(render_message(message))
        content.append(Text())

    # display assistant message
    if event.output.message and event.output.message.text:
        content.extend(render_message(event.output.message))
        if event.output.message.tool_calls:
            content.append(Text())

    # render tool calls
    if event.output.message.tool_calls:
        content.extend(render_tool_calls(event.output.message.tool_calls))

    return EventDisplay(
        f"model: {event.model}",
        Group(*content),
    )


def render_tool_event(event: ToolEvent) -> EventDisplay | None:
    # Hide operator-cancelled tool events. Matches the model-event
    # treatment — the adjacent InterruptEvent already says what
    # happened; the natural-completion result body (if it raced in
    # before cancel propagated) is preserved in the eval log but
    # suppressed from the live transcript.
    if event.error is not None and event.error.type == "cancelled":
        return None

    # Skip pending tool events: the tool *call* is already visible
    # in the preceding model event's content (via render_tool_calls),
    # so a pending tool row would just be a titled stub with no body.
    # Once the tool completes, _event_updated triggers a re-render
    # via the next batched widget refresh.
    if event.pending:
        return None

    # Resolve the body text — error message, structured content list,
    # or plain string result. Mirrors the legacy ChatMessageTool path
    # in render_message so the visual output is unchanged for callers.
    if event.error is not None:
        body_text: str = f"{event.error.type}: {event.error.message}"
    elif isinstance(event.result, list):
        body_text = "\n".join(
            block.text for block in event.result if isinstance(block, ContentText)
        )
    else:
        body_text = str(event.result) if event.result else ""

    if body_text:
        body: list[RenderableType] = list(tool_result_display(body_text.strip(), 50))
    else:
        body = [Text("(no output)")]

    return EventDisplay(f"tool: {event.function}", Group(*body))


def render_sub_events(events: list[Event]) -> list[RenderableType]:
    from rich.markdown import Markdown

    content: list[RenderableType] = []
    for e in events:
        event_displays = render_event(e) or []
        for d in event_displays:
            if d.content:
                content.append(Text("  "))
                content.append(transcript_separator(d.title, "black", "··"))
                if isinstance(d.content, Markdown):
                    set_transcript_markdown_options(d.content)
                content.append(d.content)

    return content


def render_score_event(event: ScoreEvent) -> EventDisplay:
    table = Table(box=None, show_header=False)
    table.add_column("", min_width=10, justify="left")
    table.add_column("", justify="left")
    table.add_row("Target", str(event.target).strip())
    if event.score.answer:
        table.add_row("Answer", transcript_markdown(event.score.answer, escape=True))
    table.add_row("Score", str(event.score.value).strip())
    if event.score.explanation:
        table.add_row(
            "Explanation", transcript_markdown(event.score.explanation, escape=True)
        )

    return EventDisplay("score", table)


def render_subtask_event(event: SubtaskEvent) -> list[EventDisplay]:
    # render header
    content: list[RenderableType] = [transcript_function(event.name, event.input)]

    if event.result:
        content.append(Text())
        if isinstance(event.result, str | int | float | bool | None):
            content.append(Text(str(event.result)))
        else:
            content.append(render_as_json(event.result))

    return [EventDisplay(f"subtask: {event.name}", Group(*content))]


def render_input_event(event: InputEvent) -> EventDisplay:
    return EventDisplay("input", Text.from_ansi(event.input_ansi.strip()))


def render_approval_event(event: ApprovalEvent) -> EventDisplay:
    content: list[RenderableType] = [
        f"[bold]{event.approver}[/bold]: {event.decision} ({event.explanation})"
    ]

    return EventDisplay("approval", Group(*content))


def render_info_event(event: InfoEvent) -> EventDisplay:
    if isinstance(event.data, str):
        content: RenderableType = transcript_markdown(event.data)
    else:
        content = render_as_json(event.data)
    return EventDisplay("info", content)


def render_branch_event(event: BranchEvent) -> EventDisplay:
    branch: dict[str, JsonValue] = {}
    if event.from_anchor:
        branch["from_anchor"] = event.from_anchor
    if event.metadata:
        branch["metadata"] = event.metadata

    content = render_as_json(branch)
    return EventDisplay("branch", content)


def render_compaction_event(event: CompactionEvent) -> EventDisplay:
    compaction: dict[str, JsonValue] = {}
    if event.source is not None:
        compaction["source"] = event.source
    if event.tokens_before is not None:
        compaction["tokens_before"] = event.tokens_before
    if event.tokens_after is not None:
        compaction["tokens_after"] = event.tokens_after
    if event.metadata:
        compaction["metadata"] = event.metadata

    content = render_as_json(compaction)
    return EventDisplay("compaction", content)


def render_logger_event(event: LoggerEvent) -> EventDisplay:
    content = event.message.level.upper()
    if event.message.name:
        content = f"{content} (${event.message.name})"
    content = f"{content}: {event.message.message}"
    return EventDisplay("logger", content)


def render_error_event(event: ErrorEvent) -> EventDisplay:
    return EventDisplay("error", event.error.traceback.strip())


def render_as_json(json: Any) -> RenderableType:
    return transcript_markdown(
        "```json\n"
        + to_json(json, indent=2, fallback=lambda _: None).decode()
        + "\n```\n"
    )


def render_message(message: ChatMessage) -> list[RenderableType]:
    content: list[RenderableType] = []

    # use truncation for tool messages
    if isinstance(message, ChatMessageTool):
        # render the error or the output
        if message.error:
            result: ToolResult = f"{message.error.type}: {message.error.message}"
        elif isinstance(message.content, list):
            result = "\n".join(
                [
                    content.text
                    for content in message.content
                    if isinstance(content, ContentText)
                ]
            )
        else:
            result = message.content

        if result:
            result = str(result).strip()
            content.extend(tool_result_display(result, 50))
        else:
            content.append("(no output)")

    else:
        # header
        content.extend([Text(message.role.capitalize(), style="bold"), Text()])

        # deal with plain text or with content blocks
        if isinstance(message.content, str):
            content.extend(content_display(message.text.strip()))
        else:
            for c in message.content:
                if isinstance(c, ContentReasoning):
                    content.extend(transcript_reasoning(c))
                elif isinstance(c, ContentText):
                    content.extend(content_display(c.text.strip()))

    return content


def span_title(event: SpanBeginEvent) -> str:
    return f"{event.type or 'span'}: {event.name}"


EventRenderer = Callable[[Any], EventDisplay | list[EventDisplay] | None]

_renderers: list[tuple[Type[Event], EventRenderer]] = [
    (SampleInitEvent, render_sample_init_event),
    (SampleLimitEvent, render_sample_limit_event),
    (InterruptEvent, render_interrupt_event),
    (ModelEvent, render_model_event),
    (ToolEvent, render_tool_event),
    (SubtaskEvent, render_subtask_event),
    (ScoreEvent, render_score_event),
    (InputEvent, render_input_event),
    (ApprovalEvent, render_approval_event),
    (InfoEvent, render_info_event),
    (BranchEvent, render_branch_event),
    (CompactionEvent, render_compaction_event),
    (LoggerEvent, render_logger_event),
    (ErrorEvent, render_error_event),
]
