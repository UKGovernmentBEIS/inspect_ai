from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from inspect_ai._util.content import (
    Content,
    ContentText,
)
from inspect_ai.tool import ToolDef


def _preview(value: Any, *, max_chars: int = 500) -> str:
    """Return a bounded string preview of a value."""
    try:
        text = repr(value)
    except Exception:
        text = f"<unrepresentable {type(value).__name__}>"

    if len(text) <= max_chars:
        return text

    suffix = f"... [truncated to {max_chars} chars]"
    if max_chars <= len(suffix):
        return text[:max_chars]

    return text[: max_chars - len(suffix)] + suffix


def _tool_call_arguments(
    tool_def: ToolDef, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Convert Python args/kwargs into Inspect ToolCall arguments."""
    if not args:
        return dict(kwargs)

    signature = inspect.signature(tool_def.tool)
    bound = signature.bind_partial(*args, **kwargs)
    return dict(bound.arguments)


def _tool_message_result(message: Any) -> list[Content]:
    """Return the model-visible result from an Inspect tool message."""
    if message.error is not None:
        return [ContentText(text=f"{message.error.type}: {message.error.message}")]

    content = message.content

    if isinstance(content, list):
        return content

    return [ContentText(text=content)]


def _content_to_runtime_value(
    content: list[Content],
    artifacts: list[Content],
) -> str:
    """Extract text for Monty runtime, collecting non-text content as artifacts."""
    text_parts = []

    for item in content:
        match item:
            case ContentText():
                # Only text is projected into the Monty runtime.
                text_parts.append(item.text)
            case _:
                # All other content types are preserved as artifacts.
                artifacts.append(item)

    artifact_count = len(content) - len(text_parts)
    if text_parts:
        return "\n".join(text_parts)

    return f"[{artifact_count} non-text artifact(s) generated]"


@dataclass
class RunCodeInnerToolCall:
    """A tool call made from inside run_code."""

    name: str
    args_preview: str = ""
    kwargs_preview: str = ""
    result_preview: str | None = None
    error: str | None = None


class RunCodeToolBridge:
    """Bridge from run_code external functions to allowlisted Inspect tools."""

    def __init__(
        self,
        tool_defs: list[ToolDef],
        *,
        max_inner_tool_calls: int | None = None,
    ) -> None:
        self.tool_defs = tool_defs
        self.max_tool_calls = max_inner_tool_calls
        self.calls: list[RunCodeInnerToolCall] = []
        self.artifacts: list[Content] = []

    def external_functions(self) -> dict[str, Callable[..., Any]]:
        """Create Monty external functions for allowlisted Inspect tools."""
        external_functions: dict[str, Callable[..., Any]] = {}

        for tool_def in self.tool_defs:
            if tool_def.name in external_functions:
                raise ValueError(f"Duplicate run_code inner tool name: {tool_def.name}")

            async def call_tool(
                *args: Any,
                _tool_def: ToolDef = tool_def,
                **kwargs: Any,
            ) -> str:
                return await self._call_tool(_tool_def, *args, **kwargs)

            external_functions[tool_def.name] = call_tool

        return external_functions

    async def _call_tool(self, tool_def: ToolDef, *args: Any, **kwargs: Any) -> str:
        if self.max_tool_calls is not None and len(self.calls) >= self.max_tool_calls:
            raise RuntimeError(
                f"Maximum run_code inner tool calls exceeded: {self.max_tool_calls}"
            )

        arguments = _tool_call_arguments(tool_def, args, kwargs)

        call = RunCodeInnerToolCall(
            name=tool_def.name,
            args_preview=_preview(args),
            kwargs_preview=_preview(kwargs),
        )
        self.calls.append(call)
        artifacts_before = len(self.artifacts)

        try:
            result = await self._execute_inspect_tool_call(tool_def, arguments)
            text = _content_to_runtime_value(result, self.artifacts)
            artifact_count = len(self.artifacts) - artifacts_before
            call.result_preview = _preview(f"{text} | artifacts={artifact_count}")
            return text
        except Exception as exc:
            call.error = str(exc)
            raise

    async def _execute_inspect_tool_call(
        self,
        tool_def: ToolDef,
        arguments: dict[str, Any],
    ) -> list[Content]:
        """Execute an inner tool call through Inspect's normal tool path."""
        from inspect_ai.model._call_tools import execute_tools
        from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
        from inspect_ai.tool._tool_call import ToolCall

        call = ToolCall(
            id=f"run_code_{uuid4().hex}",
            function=tool_def.name,
            arguments=arguments,
        )

        message = ChatMessageAssistant(
            content="Tool call requested from inside run_code.",
            tool_calls=[call],
        )

        result = await execute_tools(
            [message],
            self.tool_defs,
        )

        tool_messages = [
            message
            for message in result.messages
            if isinstance(message, ChatMessageTool) and message.tool_call_id == call.id
        ]

        if not tool_messages:
            return [ContentText(text="")]

        tool_message = tool_messages[-1]
        return _tool_message_result(tool_message)


def external_functions_for_tool_defs(
    tool_defs: list[ToolDef],
    *,
    max_inner_tool_calls: int | None = None,
) -> dict[str, Callable[..., Any]]:
    """Create Monty external functions for allowlisted Inspect tools."""
    bridge = RunCodeToolBridge(tool_defs, max_inner_tool_calls=max_inner_tool_calls)
    return bridge.external_functions()
