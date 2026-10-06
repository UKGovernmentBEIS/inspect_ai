import re
from logging import getLogger

from pydantic import JsonValue

from inspect_ai._util.format import format_function_call
from inspect_ai._util.logger import warn_once

# isort: split
# Backward-compatible re-exports of names that moved to inspect_ai.core.
from inspect_ai.core._tool_call import ToolCall as ToolCall
from inspect_ai.core._tool_call import ToolCallContent as ToolCallContent
from inspect_ai.core._tool_call import ToolCallError as ToolCallError
from inspect_ai.core._tool_call import ToolCallModelInput as ToolCallModelInput
from inspect_ai.core._tool_call import (
    ToolCallModelInputHints as ToolCallModelInputHints,
)
from inspect_ai.core._tool_call import ToolCallView as ToolCallView
from inspect_ai.core._tool_call import ToolCallViewer as ToolCallViewer

# End of backward-compatible re-exports.

logger = getLogger(__name__)


def resolve_tool_call_view(
    call: ToolCall, viewer: ToolCallViewer | None
) -> ToolCallView:
    if viewer:
        try:
            view = viewer(call)
            if not view.call:
                view.call = default_tool_call_viewer(call).call
            return view
        except Exception as ex:
            warn_once(
                logger,
                f"Error in viewer for tool '{call.function}': {ex}. "
                "Falling back to default rendering.",
            )
    return default_tool_call_viewer(call)


def default_tool_call_viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(
            format="markdown",
            content="```python\n"
            + format_function_call(call.function, call.arguments)
            + "\n```\n",
        )
    )


def substitute_tool_call_content(
    content: ToolCallContent, arguments: dict[str, JsonValue]
) -> ToolCallContent:
    """Substitute ``{{param_name}}`` placeholders in *content* from *arguments*.

    Placeholders whose ``param_name`` does not appear in *arguments* are left
    as-is.  Returns a **new** ``ToolCallContent`` – the original is not mutated.
    """

    def _replace(text: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            key = m.group(1)
            if key in arguments:
                return str(arguments[key])
            return m.group(0)

        return re.sub(r"\{\{(\w+)\}\}", _sub, text)

    return ToolCallContent(
        title=_replace(content.title) if content.title else content.title,
        format=content.format,
        content=_replace(content.content),
    )
