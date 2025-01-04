from typing import Awaitable, Callable

from inspect_ai.tool import Tool, ToolResult, tool

from . import _common as common

ActionFunction = Callable[[str], ToolResult | Awaitable[ToolResult]]


def computer_split() -> list[Tool]:
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
        computer_left_double_click(),
        computer_left_click_drag(),
        computer_right_click(),
        computer_key(),
        computer_type(),
    ]


@tool()
def computer_cursor_position() -> Tool:
    async def execute() -> ToolResult:
        """
        Get the current mouse cursor position.

        Args:
          None

        Returns:
          A `str` of the form "x y" where x and y are the current mouse coordinates.
        """
        return await common.cursor_position()

    return execute


@tool()
def computer_screenshot() -> Tool:
    async def execute() -> ToolResult:
        """
        Take a screenshot of the screen.

        Args:
          None

        Returns:
          A `list` with a single `ContentImage` of the screen.
        """
        return await common.screenshot()

    return execute


@tool()
def computer_mouse_move() -> Tool:
    async def execute(x: int, y: int) -> ToolResult:
        """
        Move the cursor to a specified (x, y) pixel coordinate on the screen.

        Args:
          x: X coordinate of the mouse destination.
          y: Y coordinate of the mouse destination.

        Returns:
          The `str` "OK" on success.
        """
        return await common.mouse_move(x, y)

    return execute


@tool()
def computer_left_click() -> Tool:
    async def execute() -> ToolResult:
        """
        Click the left mouse button.

        Args:
          None

        Returns:
          The `str` "OK" on success.
        """
        return await common.left_click()

    return execute


@tool()
def computer_left_double_click() -> Tool:
    async def execute() -> ToolResult:
        """
        Double-click the left mouse button.

        Args:
          None

        Returns:
          The `str` "OK" on success.
        """
        return await common.double_click()

    return execute


@tool()
def computer_left_click_drag() -> Tool:
    async def execute(x: int, y: int) -> ToolResult:
        """
        Click the left button and drag to a specified (x, y) pixel coordinate on the screen.

        Args:
          x: X coordinate of the mouse destination.
          y: Y coordinate of the mouse destination.

        Returns:
          The `str` "OK" on success.
        """
        return await common.left_click_drag(x, y)

    return execute


@tool()
def computer_right_click() -> Tool:
    async def execute() -> ToolResult:
        """
        Click the right mouse button.

        Args:
          None

        Returns:
          The `str` "OK" on success.
        """
        return await common.right_click()

    return execute


# keysm list is from https://gist.github.com/rvaiya/be31f42049a4b5ad46666a8e120d9843
@tool()
def computer_key() -> Tool:
    async def execute(key: str) -> ToolResult:
        """
        Press the specified key.

        Args:
          key: The key to press. Can be any valid keysym name such as:
            "BackSpace", "Tab", "Return", "Escape", "Insert", "Delete", "Home", "End", "Prior", "Next", "Left", "Up", "Right", "Down",
            "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Scroll_Lock", "Num_Lock", "Caps_Lock", "Pause",
            "KP_Multiply", "KP_Home", "KP_Up", "KP_Prior", "KP_Subtract", "KP_Left", "KP_Begin", "KP_Right", "KP_Add", "KP_End","KP_Down",
            "KP_Next", "KP_Insert", "KP_Delete", "KP_Enter", "KP_Divide", "KP_Equal", "KP_Decimal",

        Returns:
          The `str` "OK" on success.
        """
        return await common.press_key(key)

    return execute


@tool()
def computer_type() -> Tool:
    async def execute(text: str) -> ToolResult:
        """
        Type a string of text on the keyboard.

        Args:
          text: The text to type.

        Returns:
          The `str` "OK" on success.
        """
        return await common.type(text)

    return execute
