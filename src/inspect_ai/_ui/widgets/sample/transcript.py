from dataclasses import dataclass

from rich.console import RenderableType
from rich.panel import Panel
from textual.widgets import ListItem, ListView, Static

from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.log._log import EvalSample
from inspect_ai.log._transcript import Event, StepEvent, SubtaskEvent, ToolEvent


class TranscriptView(ListView):
    def __init__(self, sample: EvalSample) -> None:
        sample = resolve_sample_attachments(sample)
        list_items = [group_list_item(group) for group in group_events(sample.events)]
        super().__init__(*list_items)


@dataclass
class Step:
    type: str
    name: str
    groups: list["Group"]


Group = Step | Event


def group_events(events: list[Event]) -> list[Group]:
    # groups are eitehr plain events (some of which can have sub-events)
    # and higher level steps (e.g. solvers/scorers) that contain events
    grouped_steps: list[Group] = []

    # track stack of active steps
    active_steps: list[tuple[StepEvent, list[Event]]] = []

    # iterate though events
    for event in events:
        # manage step events
        if isinstance(event, StepEvent):
            if event.action == "begin":
                active_steps.append((event, []))
            elif event.action == "end":
                begin_step, step_events = active_steps.pop()
                grouped_steps.append(
                    Step(
                        type=begin_step.type or "step",
                        name=begin_step.name,
                        groups=group_events(step_events),
                    )
                )

        # other events
        else:
            # tool and subtask events have their own nested event lists
            if isinstance(event, ToolEvent | SubtaskEvent):
                event = event.model_copy(update=dict(events=group_events(event.events)))

            # add to active step if we have one
            if len(active_steps) > 0:
                active_steps[-1][1].append(event)
            # otherwise just add to root list
            else:
                grouped_steps.append(event)

    return grouped_steps


def group_list_item(group: Group) -> ListItem:
    if isinstance(group, Step):
        panel = group_panel(f"{group.type}: {group.name}")
    else:
        panel = group_panel(group.event)

    return ListItem(Static(panel))


def group_panel(title: str, renderable: RenderableType = "") -> Panel:
    return Panel(renderable, title=title, expand=True)
