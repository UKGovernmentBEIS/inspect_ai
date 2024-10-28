from typing import Callable, NamedTuple

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text

from inspect_ai._util.format import format_function_call
from inspect_ai.log._transcript import ModelEvent, SampleInitEvent, StepEvent, ToolEvent
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._render import messages_preceding_assistant, render_tool_calls

from ...core.group import EventGroup


class EventGroupDisplay(NamedTuple):
    """Display for an event group."""

    title: str
    """Text for title bar"""

    content: RenderableType | None = None
    """Optional custom content to display."""


EventGroupRenderer = Callable[[EventGroup], EventGroupDisplay | None]


def event_group_display(group: EventGroup) -> EventGroupDisplay | None:
    # see if we have a renderer
    for renderer in _renderers:
        display = renderer(group)
        if display:
            return display

    # no renderer
    return None


def render_sample_init(group: EventGroup) -> EventGroupDisplay | None:
    if isinstance(group.event, SampleInitEvent):
        return EventGroupDisplay("sample init")
    else:
        return None


def render_model(group: EventGroup) -> EventGroupDisplay | None:
    if isinstance(group.event, ModelEvent):
        # content
        content: list[RenderableType] = []

        def render_message(message: ChatMessage) -> None:
            content.extend([Text(message.role.capitalize(), style="bold"), Text()])
            if message.text:
                content.extend([Text(message.text)])

        # render preceding messages
        map(render_message, messages_preceding_assistant(group.event.input))

        # display assistant message (note that we don't render tool calls
        # because they will be handled as part of render_tool)
        if group.event.output.message.text:
            render_message(group.event.output.message)

        return EventGroupDisplay(f"model: {group.event.model}", Group(*content))
    else:
        return None


def render_tool(group: EventGroup) -> EventGroupDisplay | None:
    if isinstance(group.event, ToolEvent):
        # render the call
        content: list[RenderableType] = []
        if group.event.view:
            if group.event.view.format == "markdown":
                content.append(Markdown(group.event.view.content))
            else:
                content.append(group.event.view.content)
        else:
            call = format_function_call(group.event.function, group.event.arguments)
            content.append(Markdown("```python\n" + call + "\n```\n"))
        content.append(Text())

        # render the output
        content.append(str(group.event.result).strip())

        return EventGroupDisplay("tool call", Group(*content))
    else:
        return None


def render_solver(group: EventGroup) -> EventGroupDisplay | None:
    if isinstance(group.event, StepEvent) and group.event.type == "solver":
        return EventGroupDisplay(step_title(group.event))
    else:
        return None


def render_scorer(group: EventGroup) -> EventGroupDisplay | None:
    if isinstance(group.event, StepEvent) and group.event.type == "scorer":
        return EventGroupDisplay(step_title(group.event))
    else:
        return None


def step_title(event: StepEvent) -> str:
    return f"{event.type or 'step'}: {event.name}"


_renderers: list[EventGroupRenderer] = [
    render_sample_init,
    render_solver,
    render_scorer,
    render_model,
    render_tool,
]
