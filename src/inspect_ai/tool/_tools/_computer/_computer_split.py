"""
This module provides the same functionality as the computer tool but via a list of per-action tools . e.g. computer_mouse_move(100, 100).

The split version is not publicly exported, but is retained until we decide if it performs better than the monolithic computer tool.
"""

from typing import Awaitable, Callable

from inspect_ai.tool import Tool, ToolResult, tool

from . import _common as common

ActionFunction = Callable[[str], ToolResult | Awaitable[ToolResult]]


def computer_split(timeout: int | None = None) -> list[Tool]:
    """
    Computer interaction tools.

    Args:
      timeout (int | None): Timeout (in seconds) for command.

    Returns:
       List of computer interaction tools.
    """
    return [
        computer_cursor_position(),
        computer_screenshot(),
        computer_mouse_move(),
        computer_left_click(),
        computer_double_click(),
        computer_left_click_drag(),
        computer_right_click(),
        computer_key(),
        computer_type(),
    ]


@tool()
def computer_cursor_position(timeout: int | None = None) -> Tool:
    async def execute() -> ToolResult:
        """
        Get the current (x, y) pixel coordinate of the cursor on the screen.

        Args:
          None

        Returns:
          A `str` of the form "x y" where x and y are the current mouse coordinates.
        """
        return await common.cursor_position(timeout=timeout)

    return execute


@tool()
def computer_screenshot(timeout: int | None = None) -> Tool:
    async def execute() -> ToolResult:
        """
        Take a screenshot.

        Args:
          None

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.screenshot(timeout=timeout)

    return execute


@tool()
def computer_mouse_move(timeout: int | None = None) -> Tool:
    async def execute(x: int, y: int) -> ToolResult:
        """
        Move the cursor to a specified (x, y) pixel coordinate on the screen.

        Args:
          x: X coordinate of the mouse destination.
          y: Y coordinate of the mouse destination.

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.mouse_move(x, y, timeout=timeout)

    return execute


@tool()
def computer_left_click(timeout: int | None = None) -> Tool:
    async def execute() -> ToolResult:
        """
        Click the left mouse button.

        Args:
          None

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.left_click(timeout=timeout)

    return execute


@tool()
def computer_double_click(timeout: int | None = None) -> Tool:
    async def execute() -> ToolResult:
        """
        Double-click the left mouse button.

        Args:
          None

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.double_click(timeout=timeout)

    return execute


@tool()
def computer_left_click_drag(timeout: int | None = None) -> Tool:
    async def execute(x: int, y: int) -> ToolResult:
        """
        Click and drag the cursor to a specified (x, y) pixel coordinate on the screen.

        Args:
          x: X coordinate of the mouse destination.
          y: Y coordinate of the mouse destination.

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.left_click_drag(x, y, timeout=timeout)

    return execute


@tool()
def computer_right_click(timeout: int | None = None) -> Tool:
    async def execute() -> ToolResult:
        """
        Click the right mouse button.

        Args:
          None

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.right_click(timeout=timeout)

    return execute


# keysm list is from https://gist.github.com/rvaiya/be31f42049a4b5ad46666a8e120d9843
@tool()
def computer_key(timeout: int | None = None) -> Tool:
    async def execute(key: str) -> ToolResult:
        """
        Press a key or key-combination on the keyboard.

        Args:
          key: The key or key-combination to press. Can be any key name supported by xdotool's `key` such as:
            "Return", "Escape", "alt+Tab", "BackSpace", "Tab", "alt+Tab", "ctrl+s", "Up", "KP_0" (for the numpad 0 key),
            "Insert", "Delete", "Home", "End", "Prior", "Next", "Left", "Up", "Right", "Down",
            "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Scroll_Lock", "Num_Lock", "Caps_Lock", "Pause",
            "KP_Multiply", "KP_Home", "KP_Up", "KP_Prior", "KP_Subtract", "KP_Left", "KP_Begin", "KP_Right", "KP_Add", "KP_End","KP_Down",
            "KP_Next", "KP_Insert", "KP_Delete", "KP_Enter", "KP_Divide", "KP_Equal", "KP_Decimal"

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.press_key(key, timeout=timeout)

    return execute


@tool()
def computer_type(timeout: int | None = None) -> Tool:
    async def execute(text: str) -> ToolResult:
        """
        Type a string of text on the keyboard.

        Args:
          text: The text to type. If the text contains spaces, enclose it in quotes.

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.type(text, timeout=timeout)

    return execute
