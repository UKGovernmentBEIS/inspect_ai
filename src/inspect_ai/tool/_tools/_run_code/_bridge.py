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
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.tool import ToolDef
from inspect_ai.util import OutputLimitExceededError
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.events import SandboxTimeoutError


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


def _recoverable_tool_error_message(exc: Exception, tool_name: str) -> str | None:
    """Convert known recoverable tool exceptions to model-visible text.

    This mirrors the kinds of tool failures that Inspect's higher-level
    execute_tools(...) path normally converts into ToolCallError messages.
    Unknown exceptions intentionally return None so they still propagate.
    """
    if isinstance(exc, (TimeoutError, SandboxTimeoutError)):
        return "timeout: Command timed out before completing."

    if isinstance(exc, UnicodeDecodeError):
        return f"unicode_decode: Error decoding bytes to {exc.encoding}: {exc.reason}"

    if isinstance(exc, ValueError):
        if "embedded null byte" in str(exc):
            return (
                "parsing: "
                f"An argument to tool '{tool_name}' contained an embedded null byte."
            )
        return None

    if isinstance(exc, PermissionError):
        err = f"{exc.strerror or str(exc)}."
        if isinstance(exc.filename, str):
            err = f"{err} Filename '{exc.filename}'."
        return f"permission: {err}"

    if isinstance(exc, FileNotFoundError):
        if isinstance(exc.filename, str):
            err = f"File '{exc.filename}' was not found."
        else:
            err = exc.strerror or str(exc)
        return f"file_not_found: {err}"

    if isinstance(exc, IsADirectoryError):
        err = f"{exc.strerror or str(exc)}."
        if isinstance(exc.filename, str):
            err = f"{err} Filename '{exc.filename}'."
        return f"is_a_directory: {err}"

    if isinstance(exc, OutputLimitExceededError):
        return f"limit: The tool exceeded its output limit of {exc.limit_str}."

    if isinstance(exc, LimitExceededError):
        return f"limit: The tool exceeded its {exc.type} limit of {exc.limit_str}."

    return None


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
            ) -> Any:
                return await self._call_tool(_tool_def, *args, **kwargs)

            external_functions[tool_def.name] = call_tool

        return external_functions

    async def _call_tool(self, tool_def: ToolDef, *args: Any, **kwargs: Any) -> Any:
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
            value = self._project_result(result)
            artifact_count = len(self.artifacts) - artifacts_before
            call.result_preview = _preview(f"{value!r} | artifacts={artifact_count}")
            return value
        except Exception as exc:
            call.error = str(exc)
            raise

    def _project_result(self, result: Any) -> Any:
        """Project a raw Inspect ToolResult into a Monty runtime value.

        Scalars (str/int/float/bool) cross the boundary natively so code can
        chain them into later calls or compute on them. Rich Content is
        projected to text, with non-text content preserved as artifacts.
        """
        if isinstance(result, (str, int, float, bool)):
            return result
        content = result if isinstance(result, list) else [result]
        return _content_to_runtime_value(content, self.artifacts)

    async def _execute_inspect_tool_call(
        self,
        tool_def: ToolDef,
        arguments: dict[str, Any],
    ) -> Any:
        """Run one inner tool call and return its result.

        Goes through ``call_tool`` for validation, approval and transcript
        events. Inspect tool errors are returned as text; other exceptions
        propagate.
        """
        from inspect_ai.event._tool import ToolEvent
        from inspect_ai.model._call_tools import call_tool
        from inspect_ai.model._chat_message import ChatMessageAssistant
        from inspect_ai.tool._tool import ToolApprovalError, ToolError, ToolParsingError
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
        event = ToolEvent(
            id=call.id,
            function=call.function,
            arguments=call.arguments,
            view=call.view,
            pending=True,
        )

        try:
            result, _messages, _output, _agent, _agent_span_id = await call_tool(
                self.tool_defs, message.text, call, event, [message]
            )
        except TerminateSampleError:
            raise
        except ToolParsingError as ex:
            return f"parsing: {ex.message}"
        except ToolApprovalError as ex:
            return f"approval: {ex.message}"
        except ToolError as ex:
            return f"unknown: {ex.message}"
        except Exception as ex:
            recoverable_error = _recoverable_tool_error_message(ex, call.function)
            if recoverable_error is not None:
                return recoverable_error
            raise
        return result


def external_functions_for_tool_defs(
    tool_defs: list[ToolDef],
    *,
    max_inner_tool_calls: int | None = None,
) -> dict[str, Callable[..., Any]]:
    """Create Monty external functions for allowlisted Inspect tools."""
    bridge = RunCodeToolBridge(tool_defs, max_inner_tool_calls=max_inner_tool_calls)
    return bridge.external_functions()
