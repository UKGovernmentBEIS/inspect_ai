from __future__ import annotations

from collections.abc import Callable
from typing import Any

from inspect_ai.tool import ToolDef


def external_functions_for_tool_defs(
    tool_defs: list[ToolDef],
) -> dict[str, Callable[..., Any]]:
    """Create Monty external functions for allowlisted Inspect tools."""

    external_functions: dict[str, Callable[..., Any]] = {}

    for tool_def in tool_defs:
        if tool_def.name in external_functions:
            raise ValueError(f"Duplicate run_code inner tool name: {tool_def.name}")

        async def call_tool(*args: Any, _tool_def: ToolDef = tool_def, **kwargs: Any) -> Any:
            result = await _tool_def.tool(*args, **kwargs)
            return _coerce_external_function_result(result)

        external_functions[tool_def.name] = call_tool

    return external_functions


def _coerce_external_function_result(result: Any) -> Any:
    """Return a Monty-compatible external function result.

    Keep this conservative for now. Rich Inspect tool results can be handled later.
    """
    if result is None:
        return None
    if isinstance(result, str | int | float | bool | list | dict):
        return result
    return str(result)
