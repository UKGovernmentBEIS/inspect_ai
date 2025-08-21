from openai.types.responses import (
    ComputerToolParam,
    ResponseComputerToolCall,
    ResponseComputerToolCallOutputScreenshotParam,
)
from openai.types.responses.response_computer_tool_call import (
    Action,
    ActionClick,
    ActionDoubleClick,
    ActionDrag,
    ActionDragPath,
    ActionKeypress,
    ActionMove,
    ActionScreenshot,
    ActionScroll,
    ActionType,
    ActionWait,
)
from openai.types.responses.response_input_item_param import ComputerCallOutput

from inspect_ai._util.content import Content, ContentImage
from inspect_ai.model._chat_message import ChatMessageTool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo


def tool_call_from_openai_computer_tool_call(
    output: ResponseComputerToolCall,
) -> ToolCall:
    return ToolCall(
        id=output.call_id,
        function="computer",
        arguments=_parse_computer_tool_call_arguments(output),
    )


def maybe_computer_use_preview_tool(tool: ToolInfo) -> ComputerToolParam | None:
    # check for compatible 'computer' tool
    return (
        ComputerToolParam(
            type="computer_use_preview",
            # The OpenAI model is ahead of the sdk — "ubuntu" -> "linux"
            environment="linux",  # type: ignore
            # Note: The dimensions passed here for display_width and display_height should
            # match the dimensions of screenshots returned by the tool.
            # Those dimensions will always be one of the values in MAX_SCALING_TARGETS
            # in _x11_client.py.
            # TODO: enhance this code to calculate the dimensions based on the scaled screen
            # size used by the container.
            display_width=1366,
            display_height=768,
        )
        if tool.name == "computer"
        and (sorted(tool.parameters.properties.keys()) == sorted(computer_parmaeters()))
        else None
    )


def computer_parmaeters() -> list[str]:
    return [
        "action",
        "coordinate",
        "duration",
        "scroll_amount",
        "scroll_direction",
        "start_coordinate",
        "text",
    ]


def computer_call_output(
    message: ChatMessageTool,
    computer_call_id: str,
) -> ComputerCallOutput:
    return ComputerCallOutput(
        call_id=computer_call_id,
        type="computer_call_output",
        output=ResponseComputerToolCallOutputScreenshotParam(
            type="computer_screenshot",
            image_url=_content_image(message.content),
        ),
    )


def tool_call_arguments_to_action(
    arguments: dict[str, object],
) -> Action:
    action_type = str(arguments.get("action", ""))
    action: Action

    if action_type in [
        "left_click",
        "right_click",
        "middle_click",
        "back_click",
        "forward_click",
    ]:
        coordinate = arguments.get("coordinate", [0, 0])
        button_map = {
            "left_click": "left",
            "right_click": "right",
            "middle_click": "wheel",
            "back_click": "back",
            "forward_click": "forward",
        }
        action = ActionClick(
            type="click",
            button=button_map[action_type],  # type: ignore
            x=coordinate[0],  # type: ignore
            y=coordinate[1],  # type: ignore
        )
    elif action_type == "double_click":
        coordinate = arguments.get("coordinate", [0, 0])
        action = ActionDoubleClick(
            type="double_click",
            x=coordinate[0],  # type: ignore
            y=coordinate[1],  # type: ignore
        )
    elif action_type == "triple_click":
        # Triple click doesn't exist in OpenAI's spec, map to double click
        coordinate = arguments.get("coordinate", [0, 0])
        action = ActionDoubleClick(
            type="double_click",
            x=coordinate[0],  # type: ignore
            y=coordinate[1],  # type: ignore
        )
    elif action_type == "left_click_drag":
        start_coordinate = arguments.get("start_coordinate", [0, 0])
        end_coordinate = arguments.get("coordinate", [0, 0])
        action = ActionDrag(
            type="drag",
            path=[
                ActionDragPath(x=start_coordinate[0], y=start_coordinate[1]),  # type: ignore
                ActionDragPath(x=end_coordinate[0], y=end_coordinate[1]),  # type: ignore
            ],
        )
    elif action_type in ["key", "hold_key"]:
        text = str(arguments.get("text", ""))
        # Reverse the mapping from _parse_computer_tool_call_arguments
        reverse_mapping = {
            "Return": "ENTER",
            "Left": "LEFT",
            "Right": "RIGHT",
            "Up": "UP",
            "Down": "DOWN",
            "Escape": "ESC",
            "space": "SPACE",
            "BackSpace": "BACKSPACE",
            "Tab": "TAB",
        }
        keys = []
        for key in text.split("+"):
            mapped_key = reverse_mapping.get(key, key)
            keys.append(mapped_key)
        action = ActionKeypress(
            type="keypress",
            keys=keys,
        )
    elif action_type in ["mouse_move", "cursor_position"]:
        coordinate = arguments.get("coordinate", [0, 0])
        action = ActionMove(
            type="move",
            x=coordinate[0],  # type: ignore
            y=coordinate[1],  # type: ignore
        )
    elif action_type == "screenshot":
        action = ActionScreenshot(type="screenshot")
    elif action_type == "scroll":
        coordinate = arguments.get("coordinate", [0, 0])
        scroll_direction = str(arguments.get("scroll_direction", "down"))
        scroll_amount = int(str(arguments.get("scroll_amount", 1)))

        scroll_x = 0
        scroll_y = 0
        if scroll_direction == "up":
            scroll_y = -scroll_amount
        elif scroll_direction == "down":
            scroll_y = scroll_amount
        elif scroll_direction == "left":
            scroll_x = -scroll_amount
        elif scroll_direction == "right":
            scroll_x = scroll_amount

        action = ActionScroll(
            type="scroll",
            x=coordinate[0],  # type: ignore
            y=coordinate[1],  # type: ignore
            scroll_x=scroll_x,
            scroll_y=scroll_y,
        )
    elif action_type == "type":
        text = str(arguments.get("text", ""))
        action = ActionType(
            type="type",
            text=text,
        )
    elif action_type == "wait":
        # OpenAI's wait doesn't support duration parameter
        action = ActionWait(type="wait")
    elif action_type in ["left_mouse_down", "left_mouse_up"]:
        # These don't have direct equivalents in OpenAI's spec
        # Map to a move for now (could potentially be ignored)
        coordinate = arguments.get("coordinate", [0, 0])
        action = ActionMove(
            type="move",
            x=coordinate[0],  # type: ignore
            y=coordinate[1],  # type: ignore
        )
    else:
        # Default to screenshot if action type is unknown
        action = ActionScreenshot(type="screenshot")

    return action


def _parse_computer_tool_call_arguments(
    output: ResponseComputerToolCall,
) -> dict[str, object]:
    action = output.action

    if action.type == "click":
        coordinate = [action.x, action.y]
        match action.button:
            case "left":
                return {"action": "left_click", "coordinate": coordinate}
            case "right":
                return {"action": "right_click", "coordinate": coordinate}
            case "wheel":
                return {"action": "middle_click", "coordinate": coordinate}
            case "back":
                return {"action": "back_click", "coordinate": coordinate}
            case "forward":
                return {"action": "forward_click", "coordinate": coordinate}
    elif action.type == "double_click":
        return {"action": "double_click", "coordinate": [action.x, action.y]}
    elif action.type == "drag":
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
    elif action.type == "keypress":
        # TODO: This mapping logic is copied from their example, but seems incomplete
        mapping = {
            "ENTER": "Return",
            "LEFT": "Left",
            "RIGHT": "Right",
            "UP": "Up",
            "DOWN": "Down",
            "ESC": "Escape",
            "SPACE": "space",
            "BACKSPACE": "BackSpace",
            "TAB": "Tab",
        }
        return {
            "action": "key",
            "text": "+".join([mapping.get(key, key) for key in action.keys]),
        }
    elif action.type == "move":
        return {"action": "mouse_move", "coordinate": [action.x, action.y]}
    elif action.type == "screenshot":
        return {"action": "screenshot"}
    elif action.type == "scroll":
        # TODO: OpenAI spec's with x/y distances. Their example code treats the
        # unit of measurement as a "click" of the scroll wheel. Since it's not
        # really a thing to scroll both horizontally and vertically at the same
        # time, we'll just pick one of the potentially two directions and
        # scroll along that dimension.
        (scroll_direction, scroll_amount) = (
            ("right" if action.scroll_x > 0 else "left", abs(action.scroll_x))
            if action.scroll_x
            else ("down" if action.scroll_y > 0 else "up", abs(action.scroll_y))
        )
        return {
            "action": "scroll",
            "coordinate": [action.x, action.y],
            "scroll_direction": scroll_direction,
            "scroll_amount": scroll_amount,
        }
    elif action.type == "type":
        return {"action": "type", "text": action.text}
    elif action.type == "wait":
        return {"action": "wait", "duration": 1}

    assert False, f"Unexpected action type: {action.type}"


def _content_image(input: str | list[Content]) -> str:
    result = (
        next((item.image for item in input if isinstance(item, ContentImage)), None)
        if isinstance(input, list)
        else None
    )
    assert result, "Must find image in content"
    return result
