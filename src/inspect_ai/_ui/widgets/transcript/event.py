from typing import Callable, NamedTuple

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text

from inspect_ai._util.format import format_function_call
from inspect_ai.log._transcript import (
    Event,
    ModelEvent,
    SampleInitEvent,
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


EventRenderer = Callable[[Event], EventDisplay | None]


def render_event(event: Event) -> EventDisplay | None:
    # see if we have a renderer
    for renderer in _renderers:
        display = renderer(event)
        if display:
            return display

    # no renderer
    return None


def render_sample_init_event(event: Event) -> EventDisplay | None:
    if isinstance(event, SampleInitEvent):
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
    else:
        return None


def render_model_event(event: Event) -> EventDisplay | None:
    if isinstance(event, ModelEvent):
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
    else:
        return None


def render_tool_event(event: Event) -> EventDisplay | None:
    if isinstance(event, ToolEvent):
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
    else:
        return None


def render_solver_event(event: Event) -> EventDisplay | None:
    if isinstance(event, StepEvent) and event.type == "solver":
        return EventDisplay(step_title(event))
    else:
        return None


def render_scorer_event(event: Event) -> EventDisplay | None:
    if isinstance(event, StepEvent) and event.type == "scorer":
        return EventDisplay(step_title(event))
    else:
        return None


def render_error_event(event: Event) -> EventDisplay | None:
    return None


def render_step_event(event: Event) -> EventDisplay | None:
    if isinstance(event, StepEvent) and event.type == "scorer":
        return EventDisplay(step_title(event))
    else:
        return None


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


_renderers: list[EventRenderer] = [
    render_sample_init_event,
    render_solver_event,
    render_scorer_event,
    render_step_event,
    render_model_event,
    render_tool_event,
]

# | SampleInitEvent [DONE]
# | StateEvent
# | StoreEvent      [DONE]
# | ModelEvent      [DONE]
# | ToolEvent       [DONE]
# | ApprovalEvent
# | InputEvent
# | ScoreEvent
# | ErrorEvent
# | LoggerEvent
# | InfoEvent
# | StepEvent       [DONE]
# | SubtaskEvent,
