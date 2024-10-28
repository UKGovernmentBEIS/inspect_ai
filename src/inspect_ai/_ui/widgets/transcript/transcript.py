from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.containers import ScrollableContainer
from textual.widgets import Static

from inspect_ai._util.transcript import transcript_panel

from ...core.group import EventGroup
from .event import render_event


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
