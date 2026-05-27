from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.tool._tool_call import substitute_tool_call_content

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
        view = substitute_tool_call_content(event.view, event.arguments)
        title = f"{view.title}\n\n" if view.title is not None else ""
        return f"{title}{view.content}"
    else:
        return None
