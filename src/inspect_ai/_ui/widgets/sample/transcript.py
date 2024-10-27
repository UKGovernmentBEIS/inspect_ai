from dataclasses import dataclass

from rich.console import RenderableType
from rich.panel import Panel
from textual.widgets import ListItem, ListView, Static

from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.log._log import EvalSample
from inspect_ai.log._transcript import Event, StepEvent


class TranscriptView(ListView):
    def __init__(self, sample: EvalSample) -> None:
        sample = resolve_sample_attachments(sample)
        super().__init__(*transcript_list_items(sample.events))


def transcript_list_items(events: list[Event]) -> list[ListItem]:
    return [event_list_item(event) for event in collapse_steps(events)]


@dataclass
class TranscriptStep:
    type: str
    name: str
    events: list[Event | "TranscriptStep"]


def collapse_steps(events: list[Event]) -> list[Event | TranscriptStep]:
    collapsed_steps: list[Event | TranscriptStep] = []

    active_steps: list[tuple[StepEvent, list[Event]]] = []
    for event in events:
        if isinstance(event, StepEvent):
            if event.action == "begin":
                active_steps.append((event, []))
            elif event.action == "end":
                begin_step, step_events = active_steps.pop()
                collapsed_steps.append(
                    TranscriptStep(
                        type=begin_step.type or "step",
                        name=begin_step.name,
                        events=collapse_steps(step_events),
                    )
                )
        elif len(active_steps) > 0:
            active_steps[-1][1].append(event)
        else:
            collapsed_steps.append(event)

    return collapsed_steps


def event_list_item(event: Event | TranscriptStep) -> ListItem:
    if isinstance(event, TranscriptStep):
        panel = event_panel(f"{event.type}: {event.name}")
    else:
        panel = event_panel(event.event)

    return ListItem(Static(panel))


def event_panel(title: str, renderable: RenderableType = "") -> Panel:
    return Panel(renderable, title=title, expand=True)
