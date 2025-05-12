from inspect_ai.log._transcript import ModelEvent, ToolEvent

from ..extract import messages_as_str


def model_event_input_as_str(event: ModelEvent) -> str:
    return messages_as_str(event.input)


def tool_choice_as_str(event: ModelEvent) -> str:
    if isinstance(event.tool_choice, str):
        return event.tool_choice
    else:
        return event.tool_choice.name


def completion_as_str(event: ModelEvent) -> str:
    return event.output.completion


def tool_view_as_str(event: ToolEvent) -> str | None:
    if event.view is not None:
        title = f"{event.view.title}\n\n" if event.view.title is not None else ""
        return f"{title}{event.view.content}"
    else:
        return None
