from dataclasses import dataclass
from typing import Sequence

from inspect_ai.log._transcript import Event, StepEvent, SubtaskEvent, ToolEvent


@dataclass
class EventGroup:
    """Event and (optionally) its embedded event groups.

    - Some events (e.g. SampleInitEvent, LogEvent) have no embedded event groups.
    - Some events (e.g. ToolEvent, SubtaskEvent) contain lists of event groups.
    - StepEvent has an implicit of event groups based on its begin/end instances.
    """

    event: Event
    level: int
    groups: list["EventGroup"] | None = None


def group_events(events: Sequence[Event], level: int = 1) -> list[EventGroup]:
    """Transform ordinary list of events into list of event groups."""
    # groups are either plain events (some of which can have sub-events)
    # and higher level steps (e.g. solvers/scorers) that contain events
    event_groups: list[EventGroup] = []

    # track stack of active steps
    active_steps: list[tuple[StepEvent, list[EventGroup]]] = []

    # iterate though events
    for event in events:
        # manage step events
        if isinstance(event, StepEvent):
            if event.action == "begin":
                active_steps.append((event, []))
            elif event.action == "end":
                begin_step, step_groups = active_steps.pop()
                target_group = (
                    active_steps[-1][1] if len(active_steps) else event_groups
                )
                target_group.append(
                    EventGroup(
                        event=begin_step,
                        level=level + len(active_steps),
                        groups=step_groups,
                    )
                )

        # other events
        else:
            # target level depends on whether we are appending to a set
            target_level = level + len(active_steps)

            # tool and subtask events have their own nested event lists
            if isinstance(event, ToolEvent | SubtaskEvent):
                group = EventGroup(
                    event=event,
                    groups=group_events(event.events, level=target_level + 1),
                    level=target_level,
                )
            else:
                group = EventGroup(event=event, level=target_level)

            # add to active step if we have one
            if len(active_steps) > 0:
                active_steps[-1][1].append(group)
            # otherwise just add to root list
            else:
                event_groups.append(group)

    # if there are active steps alive then collect them (an error
    # may have prevented them from having end steps)
    while len(active_steps) > 0:
        begin_step, step_groups = active_steps.pop()
        event_groups.append(
            EventGroup(event=begin_step, level=level, groups=step_groups)
        )

    return event_groups
