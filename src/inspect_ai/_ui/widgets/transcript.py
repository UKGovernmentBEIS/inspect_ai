from rich.console import RenderableType
from rich.panel import Panel
from textual.widgets import ListItem, ListView, Static

from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.log._log import EvalSample
from inspect_ai.log._transcript import StepEvent

from ..core.group import EventGroup, group_events


class TranscriptView(ListView):
    def __init__(self, sample: EvalSample) -> None:
        sample = resolve_sample_attachments(sample)
        list_items = [
            event_group_list_item(group) for group in group_events(sample.events)
        ]
        super().__init__(*list_items)


def event_group_list_item(group: EventGroup) -> ListItem:
    if isinstance(group.event, StepEvent):
        panel = group_panel(f"{group.event.type or 'step'}: {group.event.name}")
    else:
        panel = group_panel(group.event.event)

    return ListItem(Static(panel))


def group_panel(title: str, renderable: RenderableType = "") -> Panel:
    return Panel(renderable, title=title, expand=True)
