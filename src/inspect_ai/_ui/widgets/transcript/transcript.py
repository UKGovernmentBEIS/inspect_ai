from rich.align import AlignMethod
from rich.box import ROUNDED, Box
from rich.console import Group, RenderableType
from rich.panel import Panel
from textual.containers import ScrollableContainer
from textual.widgets import Static

from ...core.group import EventGroup
from .event import event_group_display


class TranscriptView(ScrollableContainer):
    def __init__(self, event_groups: list[EventGroup]) -> None:
        panels = [event_group_panel(group) for group in event_groups]
        widgets = [Static(panel) for panel in panels if panel is not None]

        super().__init__(*widgets)


def event_group_panel(group: EventGroup) -> Panel | None:
    # get display
    display = event_group_display(group)
    if display is None:
        return None

    # handle level
    if group.level == 1:
        title = f"[bold][blue]{display.title}[/blue][/bold]"
        title_align: AlignMethod = "left"
        box = ROUNDED
    else:
        title = f"[bold]{display.title}[/bold]"
        title_align = "center"
        box = LINE

    # content group
    content: list[RenderableType] = []
    if display.content:
        content.append(display.content)

    # resolve child groups
    if group.groups:
        for child_group in group.groups:
            child_panel = event_group_panel(child_group)
            if child_panel:
                content.append(child_panel)

    # create panel
    return Panel(
        renderable=Group(*content, fit=False),
        title=title,
        title_align=title_align,
        box=box,
        expand=True,
    )


LINE: Box = Box(" ── \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n")
