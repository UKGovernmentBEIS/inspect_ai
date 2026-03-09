from collections.abc import Iterable

from openai.types.responses import (
    ComputerToolParam,
    ResponseComputerToolCall,
    ResponseComputerToolCallOutputScreenshotParam,
)
from openai.types.responses.computer_action import (
    Click,
    ComputerAction,
    DoubleClick,
    Drag,
    DragPath,
    Keypress,
    Move,
    Screenshot,
    Scroll,
    Wait,
)
from openai.types.responses.computer_action import Type as TypeAction
from openai.types.responses.response_computer_tool_call_param import (
    PendingSafetyCheck,
)
from openai.types.responses.response_input_item_param import ComputerCallOutput

from inspect_ai._util.content import Content, ContentImage
from inspect_ai.model._chat_message import ChatMessageTool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tools._computer import is_builtin_computer_tool

# Canonical mappings — inverses are derived programmatically.
_BUTTON_TO_ACTION: dict[str, str] = {
    "left": "left_click",
    "right": "right_click",
    "wheel": "middle_click",
    "back": "back_click",
    "forward": "forward_click",
}
_ACTION_TO_BUTTON: dict[str, str] = {v: k for k, v in _BUTTON_TO_ACTION.items()}

# Approximate pixels per scroll wheel click. Used to convert between OpenAI's
# pixel-based scroll_x/scroll_y and the sandbox's click-based scroll_amount.
# Unfortunately, there's no constant multiplier — it depends on the application
# receiving the event. Since OpenAI seems trained primarily on Playwright/browser
# mode, we'll use Chromium's kWheelDelta = 120px per click from here:
# https://source.chromium.org/chromium/chromium/src/+/main:ui/events/event.cc;l=637?q=kwheelde&ss=chromium%2Fchromium%2Fsrc
_PIXELS_PER_SCROLL_CLICK = 120

# 1x1 transparent PNG, base64-encoded. Used when the tool response has no
# screenshot (e.g. error) but OpenAI's protocol requires one.
_PLACEHOLDER_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
    "Nl7BcQAAAABJRU5ErkJggg=="
)


def tool_call_from_openai_computer_tool_call(
    output: ResponseComputerToolCall,
) -> ToolCall:
    return ToolCall(
        id=output.call_id,
        function="computer",
        arguments=_parse_computer_tool_call_arguments(output),
    )


def maybe_computer_use_tool(
    model_name: str, tool: ToolInfo
) -> ComputerToolParam | None:
    return (
        ComputerToolParam(type="computer")
        if "gpt-5.4" in model_name and is_builtin_computer_tool(tool)
        else None
    )


def computer_call_output(
    message: ChatMessageTool,
    computer_call_id: str,
    pending_safety_checks: Iterable[PendingSafetyCheck] | None = None,
) -> ComputerCallOutput:
    # OpenAI's computer_call_output has no error/text field — the only payload is
    # a screenshot.  When a tool call fails (e.g. bad key name), the error message
    # cannot be communicated back to the model.  We still must return a screenshot,
    # so use a 1x1 transparent PNG placeholder when the tool response has no image.
    image_url = _content_image(message.content) or _PLACEHOLDER_IMAGE
    return ComputerCallOutput(
        call_id=computer_call_id,
        type="computer_call_output",
        # "detail: original" preserves full screenshot resolution (up to 10.24M px)
        # and improves click accuracy. Documented at
        # developers.openai.com/api/docs/guides/tools-computer-use but not yet in
        # the SDK's ResponseComputerToolCallOutputScreenshotParam TypedDict.
        output=ResponseComputerToolCallOutputScreenshotParam(
            type="computer_screenshot",
            image_url=image_url,
            detail="original",  # type: ignore[typeddict-unknown-key]
        ),
        # PendingSafetyCheck and ComputerCallOutputAcknowledgedSafetyCheck are structurally
        # identical TypedDicts, so this assignment is type-safe.
        acknowledged_safety_checks=pending_safety_checks,
    )


def _get_coordinate(
    args: dict[str, object], key: str = "coordinate"
) -> tuple[int, int]:
    c = args.get(key, [0, 0])
    assert isinstance(c, (list, tuple)) and len(c) >= 2
    return (int(c[0]), int(c[1]))


def tool_call_arguments_to_actions(
    arguments: dict[str, object],
) -> list[ComputerAction]:
    actions_list = arguments.get("actions")
    assert isinstance(actions_list, list), "Expected 'actions' list in arguments"
    return [_single_arg_to_action(a) for a in actions_list]


def _single_arg_to_action(arguments: dict[str, object]) -> ComputerAction:
    action_type = str(arguments.get("action", ""))

    if action_type in _ACTION_TO_BUTTON:
        x, y = _get_coordinate(arguments)
        return Click(
            type="click",
            button=_ACTION_TO_BUTTON[action_type],  # type: ignore[arg-type]
            x=x,
            y=y,
        )
    elif action_type in ("double_click", "triple_click"):
        # Triple click doesn't exist in OpenAI's spec, map to double click
        x, y = _get_coordinate(arguments)
        return DoubleClick(type="double_click", x=x, y=y)
    elif action_type == "left_click_drag":
        sx, sy = _get_coordinate(arguments, "start_coordinate")
        ex, ey = _get_coordinate(arguments)
        return Drag(
            type="drag",
            path=[DragPath(x=sx, y=sy), DragPath(x=ex, y=ey)],
        )
    elif action_type in ("key", "hold_key"):
        text = str(arguments.get("text", ""))
        keys = text.split("+")
        return Keypress(type="keypress", keys=keys)
    elif action_type in (
        "mouse_move",
        "cursor_position",
        "left_mouse_down",
        "left_mouse_up",
    ):
        x, y = _get_coordinate(arguments)
        return Move(type="move", x=x, y=y)
    elif action_type == "screenshot":
        return Screenshot(type="screenshot")
    elif action_type == "scroll":
        x, y = _get_coordinate(arguments)
        scroll_direction = str(arguments.get("scroll_direction", "down"))
        clicks = int(str(arguments.get("scroll_amount", 1)))
        pixels = clicks * _PIXELS_PER_SCROLL_CLICK

        scroll_x = 0
        scroll_y = 0
        if scroll_direction == "up":
            scroll_y = -pixels
        elif scroll_direction == "down":
            scroll_y = pixels
        elif scroll_direction == "left":
            scroll_x = -pixels
        elif scroll_direction == "right":
            scroll_x = pixels

        return Scroll(type="scroll", x=x, y=y, scroll_x=scroll_x, scroll_y=scroll_y)
    elif action_type == "type":
        return TypeAction(type="type", text=str(arguments.get("text", "")))
    elif action_type == "wait":
        return Wait(type="wait")
    else:
        return Screenshot(type="screenshot")


def _parse_computer_tool_call_arguments(
    output: ResponseComputerToolCall,
) -> dict[str, object]:
    actions = output.actions
    assert actions, "Expected actions array in computer_call"
    return {"actions": [_parse_single_action(action) for action in actions]}


def _parse_single_action(action: ComputerAction) -> dict[str, object]:
    if isinstance(action, Click):
        return {
            "action": _BUTTON_TO_ACTION[action.button],
            "coordinate": [action.x, action.y],
        }
    elif isinstance(action, DoubleClick):
        return {"action": "double_click", "coordinate": [action.x, action.y]}
    elif isinstance(action, Drag):
        # TODO: For now, we go directly from the first to the last coordinate in
        # the path. Ultimately, we'll need to extend the tool to support all of
        # the intermediate coordinates in the path.
        path = action.path
        assert len(path) >= 2
        start = path[0]
        end = path[-1]
        return {
            "action": "left_click_drag",
            "start_coordinate": [start.x, start.y],
            "coordinate": [end.x, end.y],
        }
    elif isinstance(action, Keypress):
        return {
            "action": "key",
            "text": "+".join(action.keys),
        }
    elif isinstance(action, Move):
        return {"action": "mouse_move", "coordinate": [action.x, action.y]}
    elif isinstance(action, Screenshot):
        return {"action": "screenshot"}
    elif isinstance(action, Scroll):
        # OpenAI uses pixel distances; the sandbox uses scroll-wheel clicks.
        # Since it's not really a thing to scroll both horizontally and
        # vertically at the same time, pick the dominant axis.
        (scroll_direction, pixels) = (
            ("right" if action.scroll_x > 0 else "left", abs(action.scroll_x))
            if action.scroll_x
            else ("down" if action.scroll_y > 0 else "up", abs(action.scroll_y))
        )
        clicks = max(1, round(pixels / _PIXELS_PER_SCROLL_CLICK))
        return {
            "action": "scroll",
            "coordinate": [action.x, action.y],
            "scroll_direction": scroll_direction,
            "scroll_amount": clicks,
        }
    elif isinstance(action, TypeAction):
        return {"action": "type", "text": action.text}
    elif isinstance(action, Wait):
        return {"action": "wait", "duration": 1}

    assert False, f"Unexpected action type: {type(action)}"


def _content_image(input: str | list[Content]) -> str | None:
    return (
        next((item.image for item in input if isinstance(item, ContentImage)), None)
        if isinstance(input, list)
        else None
    )
