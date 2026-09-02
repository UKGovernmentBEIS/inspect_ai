"""The data-text projection of a transcript event, for grep-style search."""

from inspect_ai._util.content import ContentDocument, ContentText
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._error import ErrorEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._logger import LoggerEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.tool._tool import ToolResult

from ._projection import _Builder, _text


def project_event(event: Event, include_chrome: bool = True) -> list[str]:
    """Project one event; chrome is its title label, data the text it carries.

    Unsupported event kinds project to nothing.
    """
    builder = _Builder(include_chrome)
    if isinstance(event, ModelEvent):
        builder.add(event.model, chrome=True)
        builder.add(event.output.completion)
    elif isinstance(event, ToolEvent):
        builder.add(event.function, chrome=True)
        for value in event.arguments.values():
            builder.add(_text(value))
        if event.error is not None:
            builder.add(event.error.message)
        else:
            _result(builder, event.result)
    elif isinstance(event, ErrorEvent):
        builder.add("Error", chrome=True)
        builder.add(event.error.message)
    elif isinstance(event, InfoEvent):
        builder.add(event.source or "Info", chrome=True)
        if event.data is not None:
            builder.add(_text(event.data))
    elif isinstance(event, LoggerEvent):
        builder.add(event.message.level, chrome=True)
        builder.add(event.message.message)
    elif isinstance(event, ApprovalEvent):
        builder.add(event.decision, chrome=True)
        builder.add(event.message)
        builder.add(event.call.function)
        for value in event.call.arguments.values():
            builder.add(_text(value))
        builder.add(event.explanation or "")
    return builder.texts


def _result(builder: _Builder, result: ToolResult) -> None:
    for part in result if isinstance(result, list) else [result]:
        if isinstance(part, ContentText):
            builder.add(part.text)
        elif isinstance(part, ContentDocument):
            builder.add(part.filename)
        elif isinstance(part, (str, int, float)):
            builder.add(_text(part))
