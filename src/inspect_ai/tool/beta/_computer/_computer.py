from typing import Awaitable, Callable

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai.tool import Tool, ToolResult, tool
from inspect_ai.tool._tool import (
    TOOL_INIT_MODEL_INPUT,
    ToolParsingError,
)
from inspect_ai.tool._tool_call import ToolCallModelInput

from . import _common as common
from ._common import Action

ActionFunction = Callable[[str], ToolResult | Awaitable[ToolResult]]


@tool
def computer(max_screenshots: int | None = 1, timeout: int | None = 180) -> Tool:
    async def execute(
        action: Action,
        text: str | None = None,
        coordinate: list[int] | None = None,
    ) -> ToolResult:
        """
        Use this tool to interact with a computer.

        Use a mouse and keyboard to interact with a computer's desktop GUI.

        Keep in mind that icons require double clicks to open while other UI affordances like menu items and buttons require a single click.

        Args:
          action (Action): The action to perform.
              - `key`: Press a key or key-combination on the keyboard.
                  - Example: execute(action="key", text="ctrl+s")
                  - Text can be any key name supported by xdotool's `key` such as:
                      "Return", "Escape", "alt+Tab", "BackSpace", "Tab", "alt+Tab", "ctrl+s", "Up", "KP_0" (for the numpad 0 key),
                      "Insert", "Delete", "Home", "End", "Prior", "Next", "Left", "Up", "Right", "Down",
                      "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
                      "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Scroll_Lock", "Num_Lock", "Caps_Lock", "Pause",
                      "KP_Multiply", "KP_Home", "KP_Up", "KP_Prior", "KP_Subtract", "KP_Left", "KP_Begin", "KP_Right", "KP_Add", "KP_End","KP_Down",
                      "KP_Next", "KP_Insert", "KP_Delete", "KP_Enter", "KP_Divide", "KP_Equal", "KP_Decimal",
              - `type`: Type a string of text on the keyboard. If the text contains spaces, enclose it in quotes.
                  - Example: execute(action="type", text="The crux of the biscuit is the apostrophe!")
              - `cursor_position`: Get the current (x, y) pixel coordinate of the cursor on the screen.
              - `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.
                  - Example: execute(action="mouse_move", coordinate=(100, 200))
              - `left_click`: Click the left mouse button.
              - `left_click_drag`: Click and drag the cursor to a specified (x, y) pixel coordinate on the screen.
                  - Example: execute(action="left_click_drag", coordinate=(150, 250))
              - `right_click`: Click the right mouse button.
              - `middle_click`: Click the middle mouse button.
              - `double_click`: Double-click the left mouse button.
              - `screenshot`: Take a screenshot.
          text (str | None): The text to type or the key to press. Required when action is "key" or "type".
          coordinate (tuple[int, int] | None): The (x, y) pixel coordinate on the screen to which to move or drag. Required when action is "mouse_move" or "left_click_drag".

        Returns:
          The output of the command. Many commands will include a screenshot reflecting the result of the command in their output.
        """
        if action in ("mouse_move", "left_click_drag"):
            if coordinate is None:
                raise ToolParsingError(f"coordinate is required for {action}")
            if text is not None:
                raise ToolParsingError(f"text is not accepted for {action}")
            if not isinstance(coordinate, list) or len(coordinate) != 2:
                raise ToolParsingError(f"{coordinate} must be a tuple of length 2")
            if not all(isinstance(i, int) and i >= 0 for i in coordinate):
                raise ToolParsingError(
                    f"{coordinate} must be a tuple of non-negative ints"
                )

            if action == "mouse_move":
                return await common.mouse_move(
                    coordinate[0], coordinate[1], timeout=timeout
                )
            elif action == "left_click_drag":
                return await common.left_click_drag(
                    coordinate[0], coordinate[1], timeout=timeout
                )

        if action in ("key", "type"):
            if text is None:
                raise ToolParsingError(f"text is required for {action}")
            if coordinate is not None:
                raise ToolParsingError(f"coordinate is not accepted for {action}")
            if not isinstance(text, str):
                raise ToolParsingError(output=f"{text} must be a string")

            if action == "key":
                return await common.press_key(text, timeout=timeout)
            elif action == "type":
                return await common.type(text, timeout=timeout)

        if action in (
            "left_click",
            "right_click",
            "double_click",
            "middle_click",
            "screenshot",
            "cursor_position",
        ):
            if text is not None:
                raise ToolParsingError(f"text is not accepted for {action}")
            if coordinate is not None:
                raise ToolParsingError(f"coordinate is not accepted for {action}")

            if action == "screenshot":
                return await common.screenshot(timeout=timeout)
            elif action == "cursor_position":
                return await common.cursor_position(timeout=timeout)
            elif action == "left_click":
                return await common.left_click(timeout=timeout)
            elif action == "right_click":
                return await common.right_click(timeout=timeout)
            elif action == "middle_click":
                return await common.middle_click(timeout=timeout)
            elif action == "double_click":
                return await common.double_click(timeout=timeout)

        raise ToolParsingError(f"Invalid action: {action}")

    # if max_screenshots is specified then polk model input into where @tool can find it
    if max_screenshots is not None:
        setattr(execute, TOOL_INIT_MODEL_INPUT, _computer_model_input(max_screenshots))

    return execute


def _computer_model_input(max_screenshots: int) -> ToolCallModelInput:
    def model_input(
        message_index: int, message_total: int, content: str | list[Content]
    ) -> str | list[Content]:
        # nothing to do for scalars
        if isinstance(content, str):
            return content

        # if we are inside max_screenshots then return as is
        elif (message_total - message_index) <= max_screenshots:
            return content

        # otherwise convert images to text placeholdrs
        else:
            input_content: list[Content] = []
            for c in content:
                if isinstance(c, ContentImage):
                    input_content.append(
                        ContentText(
                            text="Screenshot removed to reduce size of input. Please consult the latest screenshots for the most up to date state of the screen."
                        )
                    )
                else:
                    input_content.append(c)
            return input_content

    return model_input
