from typing import Awaitable, Callable, Literal, TypeVar

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai.tool import Tool, ToolResult, tool
from inspect_ai.tool._tool import TOOL_INIT_MODEL_INPUT, ToolParsingError
from inspect_ai.tool._tool_call import ToolCallModelInput, ToolCallModelInputHints

from . import _common as common

# this is duplicated from ._resources.tool._constants import Action
# changes should be synchronized!

Action = Literal[
    "key",
    "hold_key",
    "type",
    "cursor_position",
    "mouse_move",
    "left_mouse_down",
    "left_mouse_up",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "back_click",
    "forward_click",
    "double_click",
    "triple_click",
    "scroll",
    "wait",
    "screenshot",
]


ActionFunction = Callable[[str], ToolResult | Awaitable[ToolResult]]


@tool
def computer(max_screenshots: int | None = 1, timeout: int | None = 180) -> Tool:
    """Desktop computer tool.

    See documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-computer>.

    Args:
      max_screenshots: The maximum number of screenshots to play
        back to the model as input. Defaults to 1 (set to `None` to have no limit).
      timeout: Timeout in seconds for computer tool actions.
        Defaults to 180 (set to `None` for no timeout).
    """

    async def execute(
        action: Action,
        coordinate: list[int] | None = None,
        duration: int | None = None,
        scroll_amount: int | None = None,
        scroll_direction: Literal["up", "down", "left", "right"] | None = None,
        start_coordinate: list[int] | None = None,
        text: str | None = None,
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
              - 'hold_key': Hold down a key or multiple keys for a specified duration (in seconds). Supports the same syntax as `key`.
              - `type`: Type a string of text on the keyboard. If the text contains spaces, enclose it in quotes.
                  - Example: execute(action="type", text="The crux of the biscuit is the apostrophe!")
              - `cursor_position`: Get the current (x, y) pixel coordinate of the cursor on the screen.
              - `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.
                  - Example: execute(action="mouse_move", coordinate=(100, 200))
              - `left_mouse_down`: Press the left mouse button.
              - `left_mouse_up`: Release the left mouse button.
              - `left_click`: Click the left mouse button.
              - `left_click_drag`: Click and drag the cursor to a specified (x, y) pixel coordinate on the screen.
                  - Example: execute(action="left_click_drag", coordinate=(150, 250))
              - `right_click`: Click the right mouse button.
              - `middle_click`: Click the middle mouse button.
              - `back_click`: Click the 'back' mouse button.
              - `forward_click`: Click the 'forward' mouse button.
              - `double_click`: Double-click the left mouse button.
              - `triple_click`: Double-click the left mouse button.
              - `wait`: Wait for a specified duration (in seconds).
              - `screenshot`: Take a screenshot.
          coordinate (tuple[int, int] | None): The (x, y) pixel coordinate on the screen to which to move or drag. Required only by `action=mouse_move` and `action=left_click_drag`.
          duration (int | None): The duration to wait or hold the key down for. Required only by `action=hold_key` and `action=wait`.
          scroll_amount (int | None): The number of 'clicks' to scroll. Required only by `action=scroll`.
          scroll_direction (Literal["up", "down", "left", "right] | None): The direction to scroll the screen. Required only by `action=scroll`.
          start_coordinate (tuple[int, int] | None): The (x, y) pixel coordinate on the screen from which to initiate a drag. Required only by `action=scroll`.
          text (str | None): The text to type or the key to press. Required when action is "key" or "type".

        Returns:
          The output of the command. Many commands will include a screenshot reflecting the result of the command in their output.
        """
        match action:
            case "key":
                return await common.press_key(not_none(text, "text"), timeout=timeout)
            case "hold_key":
                return await common.hold_key(
                    not_none(text, "text"),
                    not_none(duration, "duration"),
                    timeout=timeout,
                )
            case "type":
                return await common.type(not_none(text, "text"), timeout=timeout)
            case "cursor_position":
                return await common.cursor_position(timeout=timeout)
            case "mouse_move":
                return await common.mouse_move(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "left_mouse_down":
                return await common.left_mouse_down(timeout=timeout)
            case "left_mouse_up":
                return await common.left_mouse_up(timeout=timeout)
            case "left_click":
                return await common.left_click(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "left_click_drag":
                return await common.left_click_drag(
                    not_none(start_coordinate, "start_coordinate"),
                    not_none(coordinate, "coordinate"),
                    timeout=timeout,
                )
            case "right_click":
                return await common.right_click(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "middle_click":
                return await common.middle_click(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "back_click":
                return await common.back_click(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "forward_click":
                return await common.forward_click(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "double_click":
                return await common.double_click(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "triple_click":
                return await common.triple_click(
                    not_none(coordinate, "coordinate"), timeout=timeout
                )
            case "scroll":
                return await common.scroll(
                    not_none(scroll_amount, "scroll_amount"),
                    not_none(scroll_direction, "scroll_direction"),
                    coordinate,
                    timeout=timeout,
                )
            case "wait":
                return await common.wait(
                    not_none(duration, "duration"), timeout=timeout
                )
            case "screenshot":
                return await common.screenshot(timeout=timeout)

        raise ToolParsingError(f"Invalid action: {action}")

    # if max_screenshots is specified then polk model input into where @tool can find it
    if max_screenshots is not None:
        setattr(execute, TOOL_INIT_MODEL_INPUT, _computer_model_input(max_screenshots))

    return execute


def _computer_model_input(max_screenshots: int) -> ToolCallModelInput:
    def model_input(
        message_index: int,
        message_total: int,
        content: str | list[Content],
        hints: ToolCallModelInputHints,
    ) -> str | list[Content]:
        if hints.get("disable_computer_screenshot_truncation", False):
            return content

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


T = TypeVar("T")


def not_none(value: T | None, name: str) -> T:
    if value is None:
        raise ToolParsingError(f"{name} must be provided")
    return value
