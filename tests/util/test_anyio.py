import sys

from inspect_ai.tool._tool import ToolError
from inspect_ai.util._anyio import _flatten_exception

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


def test_crazy_with_from():
    flattened = _flatten_exception(_construct_mcp_exception(True))
    assert len(flattened) == 1
    assert str(flattened[0]) == "tool error"


def test_crazy_without_from():
    flattened = _flatten_exception(_construct_mcp_exception(False))
    assert len(flattened) == 2
    assert str(flattened[0]) == "tool error"
    assert str(flattened[1]) == "mcp error"


def _construct_mcp_exception(use_from: bool) -> Exception:
    """
    Constructs an exception "stack" that is observed when an MCP server raises a ToolError

          ┌───────────────────────┐
          │ ExceptionGroup        │
          └───────────────────────┘
               │            │
           exceptions  __context__
               │            │
               ▼            ▼
          ┌───────────────────────┐
          │ ExceptionGroup        │
          └───────────────────────┘
                     │
                 exceptions
                     │
                     ▼
          ┌───────────────────────┐
          │ ToolError             │
          └───────────────────────┘
               │            │
           __cause__   __context__
         (depending on      │
           use_from)        │
               │            │
               ▼            ▼
          ┌───────────────────────┐
          │ McpError              │
          └───────────────────────┘
    """
    inner_group: ExceptionGroup
    try:
        try:
            raise RuntimeError("mcp error")
        except RuntimeError as e:
            if use_from:
                raise ToolError("tool error") from e
            else:
                raise ToolError("tool error")
    except Exception as inner_tool_error:
        inner_group = ExceptionGroup("Inner Group", [inner_tool_error])

    try:
        try:
            raise inner_group
        except Exception as e:
            raise ExceptionGroup("Outer Group", [e])
    except Exception as wow:
        return wow
