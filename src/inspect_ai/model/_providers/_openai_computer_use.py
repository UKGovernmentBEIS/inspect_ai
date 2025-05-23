from openai.types.responses import (
    ComputerToolParam,
    ResponseComputerToolCall,
    ResponseComputerToolCallOutputScreenshotParam,
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
        internal=output.model_dump(),
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
        and (
            sorted(tool.parameters.properties.keys())
            == sorted(
                [
                    "action",
                    "coordinate",
                    "duration",
                    "scroll_amount",
                    "scroll_direction",
                    "start_coordinate",
                    "text",
                ]
            )
        )
        else None
    )


def computer_call_output(
    message: ChatMessageTool,
    # internal is passed in despite being within message to avoid an extra
    # validation step
    internal: ResponseComputerToolCall,
) -> ComputerCallOutput:
    return ComputerCallOutput(
        call_id=internal.call_id,
        type="computer_call_output",
        output=ResponseComputerToolCallOutputScreenshotParam(
            type="computer_screenshot",
            image_url=_content_image(message.content),
        ),
    )


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
