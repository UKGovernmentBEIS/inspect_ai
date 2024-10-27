from rich.console import RenderableType
from rich.panel import Panel
from textual.widgets import ListItem, ListView, Static

from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.log._log import EvalSample
from inspect_ai.log._transcript import Event


class TranscriptView(ListView):
    def __init__(self, sample: EvalSample) -> None:
        sample = resolve_sample_attachments(sample)
        super().__init__(*[event_view(event) for event in sample.events])


def event_view(event: Event) -> ListItem:
    return ListItem(Static(event_panel(event.event, "")))


def event_panel(title: str, renderable: RenderableType) -> RenderableType:
    return Panel(renderable, title=title, expand=True)
