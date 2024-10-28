from rich.align import AlignMethod
from rich.box import ROUNDED, Box
from rich.console import Group, RenderableType
from rich.panel import Panel
from textual.containers import ScrollableContainer
from textual.widgets import Static

from inspect_ai.log._transcript import StepEvent

from ..core.group import EventGroup


class TranscriptView(ScrollableContainer):
    def __init__(self, event_groups: list[EventGroup]) -> None:
        super().__init__(*[Static(EventGroupPanel(group)) for group in event_groups])


class EventGroupPanel(Panel):
    def __init__(self, group: EventGroup) -> None:
        # handle title
        if isinstance(group.event, StepEvent):
            title = f"{group.event.type or 'step'}: {group.event.name}"
        else:
            title = group.event.event

        # handle level
        if group.level == 1:
            title = f"[bold][blue]{title}[/blue][/bold]"
            title_align: AlignMethod = "left"
            box = ROUNDED
        else:
            title = f"[bold]{title}[/bold]"
            title_align = "center"
            box = LINE

        # handle nested groups
        if group.groups:
            content: RenderableType = Group(
                *[EventGroupPanel(group) for group in group.groups], fit=False
            )
        else:
            content = ""

        super().__init__(
            renderable=content,
            title=title,
            title_align=title_align,
            box=box,
            expand=True,
        )


LINE: Box = Box(" ── \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n")
