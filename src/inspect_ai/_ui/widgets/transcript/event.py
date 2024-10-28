from typing import Callable, NamedTuple

from rich.console import RenderableType

from inspect_ai.log._transcript import ModelEvent, SampleInitEvent, StepEvent

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
        return EventGroupDisplay(f"model: {group.event.model}")
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
]
