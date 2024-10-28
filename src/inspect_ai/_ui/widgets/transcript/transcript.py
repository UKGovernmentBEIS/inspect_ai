from rich.align import AlignMethod
from rich.box import ROUNDED, Box
from rich.console import Group, RenderableType
from rich.panel import Panel
from textual.containers import ScrollableContainer
from textual.widgets import Static

from inspect_ai.log._transcript import StepEvent

from ...core.group import EventGroup
from .event import EventGroupDisplay


class TranscriptView(ScrollableContainer):
    def __init__(self, event_groups: list[EventGroup]) -> None:
        super().__init__(*[Static(EventGroupPanel(group)) for group in event_groups])


class EventGroupPanel(Panel):
    def __init__(self, group: EventGroup) -> None:
        # handle title
        display = event_group_display(group)

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
        child_groups = display.groups if display.groups is not None else group.groups
        if child_groups:
            content.extend([EventGroupPanel(group) for group in child_groups])

        # create panel
        super().__init__(
            renderable=Group(*content, fit=False),
            title=title,
            title_align=title_align,
            box=box,
            expand=True,
        )


LINE: Box = Box(" ── \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n")


def event_group_display(group: EventGroup) -> EventGroupDisplay:
    # handle title
    if isinstance(group.event, StepEvent):
        title = f"{group.event.type or 'step'}: {group.event.name}"
    else:
        title = group.event.event

    # return display
    return EventGroupDisplay(title=title, content="", groups=group.groups)
