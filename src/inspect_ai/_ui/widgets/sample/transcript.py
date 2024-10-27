from rich.console import RenderableType
from rich.panel import Panel
from textual.widgets import ListItem, ListView, Static

from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.log._log import EvalSample
from inspect_ai.log._transcript import Event, StepEvent


class TranscriptView(ListView):
    def __init__(self, sample: EvalSample) -> None:
        sample = resolve_sample_attachments(sample)
        super().__init__(*[event_list_item(event) for event in sample.events])


def event_list_item(event: Event) -> ListItem:
    if isinstance(event, StepEvent):
        panel = step_event_panel(event)
    else:
        panel = event_panel(event.event)

    return ListItem(Static(panel))


def step_event_panel(event: StepEvent) -> Panel:
    title = f"{event.type}: {event.name}" if event.type else event.event
    return event_panel(title, "")


def event_panel(title: str, renderable: RenderableType = "") -> Panel:
    return Panel(renderable, title=title, expand=True)
