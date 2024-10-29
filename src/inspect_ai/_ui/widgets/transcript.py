from typing import Any, Callable, NamedTuple, Type

from pydantic_core import to_json
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.containers import ScrollableContainer
from textual.widgets import Static

from inspect_ai._util.format import format_function_call
from inspect_ai._util.transcript import transcript_markdown, transcript_panel
from inspect_ai.log._transcript import (
    ErrorEvent,
    Event,
    InfoEvent,
    InputEvent,
    LoggerEvent,
    ModelEvent,
    SampleInitEvent,
    ScoreEvent,
    StepEvent,
    SubtaskEvent,
    ToolEvent,
)
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._render import messages_preceding_assistant

from ..core.group import EventGroup


class TranscriptView(ScrollableContainer):
    def __init__(self, event_groups: list[EventGroup]) -> None:
        panels = [event_group_panel(group) for group in event_groups]
        widgets = [
            Static(Group(panel, Text())) for panel in panels if panel is not None
        ]
        super().__init__(*widgets)


def event_group_panel(group: EventGroup) -> Panel | None:
    # get display
    display = render_event(group.event)
    if display is None:
        return None

    # content group
    content: list[RenderableType] = []
    if display.content:
        content.append(display.content)

    # resolve child groups
    if group.groups:
        content.append(Text())
        for child_group in group.groups:
            child_panel = event_group_panel(child_group)
            if child_panel:
                content.append(child_panel)

    # create panel
    return transcript_panel(title=display.title, content=content, level=group.level)


class EventDisplay(NamedTuple):
    """Display for an event group."""

    title: str
    """Text for title bar"""

    content: RenderableType | None = None
    """Optional custom content to display."""


def render_event(event: Event) -> EventDisplay | None:
    # see if we have a renderer
    for event_type, renderer in _renderers:
        if isinstance(event, event_type):
            display = renderer(event)
            if display:
                return display

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
    content: list[RenderableType] = [Text()]
    for message in messages:
        content.extend(render_message(message))

    # target
    if sample.target:
        content.append(Text())
        content.append(Text("Target", style="bold"))
        content.append(Text())
        content.append(str(sample.target).strip())

    content.append(Text())

    return EventDisplay("sample init", Group(*content))


def render_model_event(event: ModelEvent) -> EventDisplay:
    # content
    content: list[RenderableType] = []

    def append_message(message: ChatMessage) -> None:
        content.extend(render_message(message))

    # render preceding messages
    map(append_message, messages_preceding_assistant(event.input))

    # display assistant message (note that we don't render tool calls
    # because they will be handled as part of render_tool)
    if event.output.message.text:
        append_message(event.output.message)

    return EventDisplay(f"model: {event.model}", Group(*content))


def render_tool_event(event: ToolEvent) -> EventDisplay:
    # render the call
    content: list[RenderableType] = []
    if event.view:
        if event.view.format == "markdown":
            content.append(transcript_markdown(event.view.content))
        else:
            content.append(event.view.content)
    else:
        content.append(render_function_call(event.function, event.arguments))
    content.append(Text())

    # render the output
    content.append(str(event.result).strip())

    return EventDisplay("tool call", Group(*content))


def render_step_event(event: StepEvent) -> EventDisplay:
    if event.type == "solver":
        return render_solver_event(event)
    if event.type == "scorer":
        return render_scorer_event(event)
    else:
        return EventDisplay(step_title(event))


def render_solver_event(event: StepEvent) -> EventDisplay:
    return EventDisplay(step_title(event))


def render_scorer_event(event: StepEvent) -> EventDisplay:
    return EventDisplay(step_title(event))


def render_score_event(event: ScoreEvent) -> EventDisplay:
    table = Table(box=None, show_header=False)
    table.add_column("", min_width=10, justify="left")
    table.add_column("", justify="left")
    table.add_row("Target", str(event.target).strip())
    if event.score.answer:
        table.add_row("Answer", transcript_markdown(event.score.answer))
    table.add_row("Score", str(event.score.value).strip())
    if event.score.explanation:
        table.add_row("Explanation", transcript_markdown(event.score.explanation))

    return EventDisplay("score", table)


def render_subtask_event(event: SubtaskEvent) -> EventDisplay:
    content: list[RenderableType] = [render_function_call(event.name, event.input)]
    content.append(Text())
    content.append(render_as_json(event.result))

    return EventDisplay(f"subtask: {event.name}", Group(*content))


def render_input_event(event: InputEvent) -> EventDisplay:
    return EventDisplay("input", Text.from_ansi(event.input_ansi.strip()))


def render_info_event(event: InfoEvent) -> EventDisplay:
    if isinstance(event.data, str):
        content: RenderableType = transcript_markdown(event.data)
    else:
        content = render_as_json(event.data)
    return EventDisplay("info", content)


def render_logger_event(event: LoggerEvent) -> EventDisplay:
    content = event.message.level.upper()
    if event.message.name:
        content = f"{content} (${event.message.name})"
    content = f"{content}: {event.message.message}"
    return EventDisplay("logger", content)


def render_error_event(event: ErrorEvent) -> EventDisplay:
    return EventDisplay("error", event.error.traceback.strip())


def render_function_call(function: str, arguments: dict[str, Any]) -> RenderableType:
    call = format_function_call(function, arguments)
    return transcript_markdown("```python\n" + call + "\n```\n")


def render_as_json(json: Any) -> RenderableType:
    return transcript_markdown(
        "```json\n"
        + to_json(json, indent=2, fallback=lambda _: None).decode()
        + "\n```\n"
    )


def render_message(message: ChatMessage) -> list[RenderableType]:
    content: list[RenderableType] = [
        Text(message.role.capitalize(), style="bold"),
        Text(),
    ]
    if message.text:
        content.extend([Text(message.text)])
    return content


def step_title(event: StepEvent) -> str:
    return f"{event.type or 'step'}: {event.name}"


EventRenderer = Callable[[Any], EventDisplay | None]

_renderers: list[tuple[Type[Event], EventRenderer]] = [
    (SampleInitEvent, render_sample_init_event),
    (StepEvent, render_step_event),
    (ModelEvent, render_model_event),
    (ToolEvent, render_tool_event),
    (SubtaskEvent, render_subtask_event),
    (ScoreEvent, render_score_event),
    (InputEvent, render_input_event),
    (InfoEvent, render_info_event),
    (LoggerEvent, render_logger_event),
    (ErrorEvent, render_error_event),
]

# | SampleInitEvent [DONE]
# | StateEvent
# | StoreEvent      [DONE]
# | ModelEvent      [DONE]
# | ToolEvent       [DONE]
# | ApprovalEvent
# | InputEvent      [DONE]
# | ScoreEvent      [DONE]
# | ErrorEvent      [DONE]
# | LoggerEvent     [DONE]
# | InfoEvent       [DONE]
# | StepEvent       [DONE]
# | SubtaskEvent    [DONE]
