from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic_core import to_jsonable_python

from inspect_ai._util.content import (
    Content,
    ContentBase,
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
) -> tuple[str, list[Content]]:
    """Extract text for Monty runtime, collecting non-text content as artifacts."""
    text_parts: list[str] = []
    collected_artifacts: list[Content] = []

    for item in content:
        match item:
            case ContentText():
                # Only text is projected into the Monty runtime.
                text_parts.append(item.text)
            case _:
                # All other content types are preserved as artifacts.
                collected_artifacts.append(item)

    if text_parts:
        return "\n".join(text_parts), collected_artifacts

    return f"[{len(collected_artifacts)} non-text artifact(s) generated]", collected_artifacts


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


class RunCodeMaxToolCallsExceededError(RuntimeError):
    """Raised when run_code exceeds its configured inner tool-call limit."""

    def __init__(self, max_tool_calls: int) -> None:
        self.max_tool_calls = max_tool_calls
        super().__init__(
            f"Maximum run_code inner tool calls exceeded: {max_tool_calls}"
        )


@dataclass
class RunCodeInnerToolCallTraceEntry:
    """One compact preview entry in the run_code inner tool-call trace.

    The actual Inspect ToolCall / ToolEvent path keeps full mapped arguments.
    This trace intentionally stores bounded previews so optional run_code
    tracing does not duplicate large intermediate values into model context.
    """

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
        self.call_trace: list[RunCodeInnerToolCallTraceEntry] = []
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
        if (
            self.max_tool_calls is not None
            and len(self.call_trace) >= self.max_tool_calls
        ):
            raise RunCodeMaxToolCallsExceededError(self.max_tool_calls)

        arguments = _tool_call_arguments(tool_def, args, kwargs)

        call_trace_entry = RunCodeInnerToolCallTraceEntry(
            name=tool_def.name,
            args_preview=_preview(args),
            kwargs_preview=_preview(kwargs),
        )
        self.call_trace.append(call_trace_entry)
        artifacts_before = len(self.artifacts)

        try:
            result = await self._execute_inspect_tool_call(tool_def, arguments)
            value = self._project_result(result, tool_def.name)
            artifact_count = len(self.artifacts) - artifacts_before
            call_trace_entry.result_preview = _preview(
                f"{value!r} | artifacts={artifact_count}"
            )
            return value
        except Exception as exc:
            call_trace_entry.error = str(exc)
            raise

    def _project_result(self, result: Any, tool_name: str) -> Any:
        """Project a raw Inspect ToolResult into a Monty runtime value.

        Three cases:
          - Scalars (str/int/float/bool) cross natively so code can chain them
            into later calls or compute on them.
          - Rich Content (text/image/...) is projected to text, with non-text
            content preserved as artifacts.
          - Structured data (list/dict/BaseModel) is converted to native Python
            so code can index/iterate/aggregate over it. Monty accepts native
            lists and dicts of primitives.
        """
        if isinstance(result, (str, int, float, bool)):
            return result

        if self._is_content_result(result):
            content = result if isinstance(result, list) else [result]
            text, new_artifacts = _content_to_runtime_value(content)
            self.artifacts.extend(new_artifacts)
            return text

        try:
            return to_jsonable_python(result, fallback=lambda value: str(value))
        except Exception as exc:
            from inspect_ai.tool._tool import ToolError

            raise ToolError(
                f"run_code: tool '{tool_name}' returned a value that can't be "
                f"projected into the runtime ({type(result).__name__}): {exc}"
            ) from exc

    @staticmethod
    def _is_content_result(result: Any) -> bool:
        """Whether a tool result carries Inspect Content (vs. structured data)."""
        if isinstance(result, ContentBase):
            return True
        if isinstance(result, list):
            return any(isinstance(item, ContentBase) for item in result)
        return False

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
