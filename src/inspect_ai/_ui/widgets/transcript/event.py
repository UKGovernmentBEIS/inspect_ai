from typing import Callable, NamedTuple

from rich.console import RenderableType

from ...core.group import EventGroup


class EventGroupDisplay(NamedTuple):
    """Display for an event group."""

    title: str
    """Text for title bar"""

    content: RenderableType | None
    """Optional custom content to display."""

    groups: list[EventGroup] | None
    """Optional filtered list of contained event groups."""


EventGroupRenderer = Callable[[EventGroup], EventGroupDisplay | None]

_renderers: list[EventGroupRenderer] = []


def register_renderer(renderer: EventGroupRenderer) -> None:
    _renderers.append(renderer)
