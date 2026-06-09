from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from inspect_ai.tool import ToolDef


@dataclass
class RunCodeInnerToolCall:
    """A tool call made from inside run_code."""

    name: str
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    result: Any | None = None
    error: str | None = None


class RunCodeToolBridge:
    """Bridge from run_code external functions to allowlisted Inspect tools."""

    def __init__(
        self,
        tool_defs: list[ToolDef],
        *,
        max_tool_calls: int | None = None,
    ) -> None:
        self.tool_defs = tool_defs
        self.max_tool_calls = max_tool_calls
        self.calls: list[RunCodeInnerToolCall] = []

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

        call = RunCodeInnerToolCall(
            name=tool_def.name,
            args=args,
            kwargs=kwargs,
        )
        self.calls.append(call)

        try:
            result = await tool_def.tool(*args, **kwargs)
            result = _coerce_external_function_result(result)
            call.result = result
            return result
        except Exception as exc:
            call.error = str(exc)
            raise


def external_functions_for_tool_defs(
    tool_defs: list[ToolDef],
    *,
    max_tool_calls: int | None = None,
) -> dict[str, Callable[..., Any]]:
    """Create Monty external functions for allowlisted Inspect tools."""
    bridge = RunCodeToolBridge(tool_defs, max_tool_calls=max_tool_calls)
    return bridge.external_functions()


def _coerce_external_function_result(result: Any) -> Any:
    """Return a Monty-compatible external function result."""
    if result is None:
        return None
    if isinstance(result, str | int | float | bool | list | dict):
        return result
    return str(result)
