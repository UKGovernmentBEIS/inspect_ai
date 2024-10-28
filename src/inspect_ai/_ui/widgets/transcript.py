from rich.panel import Panel
from textual.widgets import ListItem, ListView, Static

from inspect_ai.log._transcript import StepEvent

from ..core.group import EventGroup


class EventGroupsListView(ListView):
    def __init__(self, event_groups: list[EventGroup]) -> None:
        # pass list to super
        super().__init__(*[EventGroupListItem(group) for group in event_groups])


class EventGroupListItem(ListItem):
    def __init__(self, group: EventGroup) -> None:
        # handle title
        if isinstance(group.event, StepEvent):
            title = f"{group.event.type or 'step'}: {group.event.name}"
        else:
            title = group.event.event

        super().__init__(Static(Panel("", title=title, expand=True)))
