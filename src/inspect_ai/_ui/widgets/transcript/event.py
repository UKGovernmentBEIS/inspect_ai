from typing import Any, Callable, NamedTuple, Type

from rich.console import Group, RenderableType
from rich.json import JSON
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from inspect_ai._util.format import format_function_call
from inspect_ai.log._transcript import (
    ErrorEvent,
    Event,
    InfoEvent,
    LoggerEvent,
    ModelEvent,
    SampleInitEvent,
    ScoreEvent,
    StepEvent,
    ToolEvent,
)
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._render import messages_preceding_assistant


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
            content.append(Markdown(event.view.content))
        else:
            content.append(event.view.content)
    else:
        call = format_function_call(event.function, event.arguments)
        content.append(Markdown("```python\n" + call + "\n```\n"))
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
        table.add_row("Answer", Markdown(event.score.answer))
    table.add_row("Score", str(event.score.value).strip())
    if event.score.explanation:
        table.add_row("Explanation", Markdown(event.score.explanation))

    return EventDisplay("score", table)


def render_info_event(event: InfoEvent) -> EventDisplay:
    if isinstance(event.data, str):
        content: RenderableType = Markdown(event.data)
    else:
        content = JSON.from_data(event.data)
    return EventDisplay("info", content)


def render_logger_event(event: LoggerEvent) -> EventDisplay:
    content = event.message.level.upper()
    if event.message.name:
        content = f"{content} (${event.message.name})"
    content = f"{content}: {event.message.message}"
    return EventDisplay("logger", content)


def render_error_event(event: ErrorEvent) -> EventDisplay:
    return EventDisplay("error", event.error.traceback.strip())


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
    (ScoreEvent, render_score_event),
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
# | InputEvent
# | ScoreEvent      [DONE]
# | ErrorEvent      [DONE]
# | LoggerEvent     [DONE]
# | InfoEvent       [DONE]
# | StepEvent       [DONE]
# | SubtaskEvent,
