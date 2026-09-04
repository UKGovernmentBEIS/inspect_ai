"""The source-text projection of a Messages tab row.

A row becomes the texts the viewer renders for it, in render order, taken from
the log as written (markdown source, not rendered text). The server only has to
say which rows match and roughly how often; the client's DOM is authoritative
inside a row, so no attempt is made to reproduce the viewer's formatting.
"""

import html
import json
from dataclasses import dataclass
from typing import Literal

from inspect_ai._util.citation import Citation, UrlCitation
from inspect_ai._util.content import (
    Content,
    ContentData,
    ContentDocument,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.tool._tool_call import ToolCall

from ._markdown import strip_markdown_for_count
from ._rows import MessageRow

ToolCallStyle = Literal["complete", "compact", "omit"]
DisplayMode = Literal["rendered", "raw"]
"""The viewer's toggle: `raw` shows markdown source, so nothing is stripped."""


@dataclass(frozen=True)
class ProjectionOptions:
    unlabeled_roles: frozenset[str] = frozenset()
    tool_call_style: ToolCallStyle = "complete"
    display_mode: DisplayMode = "rendered"


def project_row(
    row: MessageRow,
    options: ProjectionOptions = ProjectionOptions(),
    include_chrome: bool = True,
) -> list[str]:
    """Project one row; chrome is text the viewer adds (role heading, "Reasoning" title)."""
    builder = _Builder(include_chrome, options.display_mode)
    message = row.message
    if message.role not in options.unlabeled_roles:
        builder.add(message.role, chrome=True)
    if isinstance(message, ChatMessageTool):
        # a tool message heading its own row (grep scans messages singly)
        # projects as it would folded under its call
        _tool_result(builder, message)
    elif isinstance(message.content, str):
        builder.add_markdown(message.content)
    else:
        for item in message.content:
            _content(builder, item)
    if isinstance(message, ChatMessageAssistant) and options.tool_call_style != "omit":
        for index, call in enumerate(message.tool_calls or []):
            _tool_call(builder, row, index, call, options.tool_call_style)
    return builder.texts


class _Builder:
    def __init__(
        self, include_chrome: bool, display_mode: DisplayMode = "rendered"
    ) -> None:
        self.include_chrome = include_chrome
        self.display_mode = display_mode
        self.texts: list[str] = []

    def add(self, text: str, chrome: bool = False) -> None:
        if text and (self.include_chrome or not chrome):
            self.texts.append(text)

    def add_markdown(self, text: str) -> None:
        if self.display_mode == "rendered":
            text = strip_markdown_for_count(text)
        self.add(text)


def _content(builder: _Builder, item: Content) -> None:
    if isinstance(item, ContentText):
        builder.add_markdown(item.text)
        for citation in item.citations or []:
            builder.add(_citation_label(citation))
    elif isinstance(item, ContentReasoning):
        builder.add(_reasoning_title(item), chrome=True)
        builder.add_markdown(_reasoning_text(item))
    elif isinstance(item, ContentData):
        builder.add(_text(item.data))
    elif isinstance(item, ContentDocument):
        builder.add(item.filename)
    elif isinstance(item, ContentToolUse):
        builder.add(f"tool: {item.name}", chrome=True)
        builder.add(item.context or "")
        builder.add(item.name)
        builder.add(item.arguments)
        if item.error:
            builder.add(item.error)
        else:
            builder.add(item.result)


def _citation_label(citation: Citation) -> str:
    """What the viewer prints for a citation: title, else quoted text, else URL; entities decoded."""
    if citation.title:
        label = citation.title
    elif isinstance(citation.cited_text, str):
        label = citation.cited_text
    else:
        label = citation.url if isinstance(citation, UrlCitation) else ""
    return html.unescape(label)


def _reasoning_text(item: ContentReasoning) -> str:
    """Redacted reasoning is ciphertext; the viewer shows its summary instead."""
    if item.redacted:
        return item.summary or ""
    return item.reasoning or item.summary or ""


def _reasoning_title(item: ContentReasoning) -> str:
    shows_summary = bool(item.summary) and (item.redacted or not item.reasoning)
    return "Reasoning (Summary)" if shows_summary else "Reasoning"


def _tool_call(
    builder: _Builder,
    row: MessageRow,
    index: int,
    call: ToolCall,
    style: ToolCallStyle,
) -> None:
    builder.add(f"tool: {call.function}", chrome=True)
    if call.view is not None and call.view.title:
        builder.add(call.view.title, chrome=True)
    builder.add(call.function)
    for value in call.arguments.values():
        builder.add(_text(value))
    if style == "compact":
        return
    tool_message = _tool_message(row, index, call)
    if tool_message is not None:
        _tool_result(builder, tool_message)


def _tool_message(
    row: MessageRow, index: int, call: ToolCall
) -> ChatMessageTool | None:
    if call.id:
        return next((m for m in row.tool_messages if m.tool_call_id == call.id), None)
    return row.tool_messages[index] if index < len(row.tool_messages) else None


def _tool_result(builder: _Builder, message: ChatMessageTool) -> None:
    """The error message replaces the output, as the viewer shows it."""
    if message.error:
        builder.add(message.error.message)
        return
    content = message.content
    for part in [content] if isinstance(content, str) else content:
        if isinstance(part, str):
            builder.add(part)
        elif isinstance(part, ContentText):
            builder.add(part.text)
        elif isinstance(part, ContentReasoning):
            builder.add(_reasoning_text(part))
        elif isinstance(part, ContentData):
            builder.add(_text(part.data))
        elif isinstance(part, ContentDocument):
            builder.add(part.filename)


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
