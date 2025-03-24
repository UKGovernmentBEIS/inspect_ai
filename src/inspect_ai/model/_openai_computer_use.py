from openai.types.responses import (
    ComputerToolParam,
    ResponseComputerToolCall,
    ResponseComputerToolCallOutputScreenshotParam,
)
from openai.types.responses.response_input_item_param import ComputerCallOutput

from inspect_ai._util.content import Content, ContentImage
from inspect_ai.model._chat_message import ChatMessageTool
from inspect_ai.model._openai_internal_tools import ResponseToolCallInternal
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo


def tool_call_for_openai_computer_tool_call(
    output: ResponseComputerToolCall,
) -> ToolCall:
    return ToolCall(
        id=output.call_id,
        function="computer",
        arguments=_parse_computer_tool_call_arguments(output),
        internal=output.model_dump(),
    )


def maybe_computer_use_tool_param(tool: ToolInfo) -> ComputerToolParam | None:
    # check for compatible 'computer' tool
    if tool.name == "computer" and (
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
    ):
        return ComputerToolParam(
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
    # not a computer_use tool
    else:
        return None


def maybe_computer_call_output(
    message: ChatMessageTool,
    # internal is passed in despite being within message to avoid an extra
    # validation step
    internal: ResponseToolCallInternal,
) -> ComputerCallOutput | None:
    image_url = _maybe_content_image(message.content)

    # TODO: We won't have an image_url if we're redacting old images. I wonder how
    # the model handles getting "function_call_output" for a "computer_call"?
    if image_url:
        return ComputerCallOutput(
            call_id=internal.call_id,
            # id=internal.id,
            # id=internal.id.replace("cu_", "cuo_", 1),  # TODO: ??!??!
            type="computer_call_output",
            output=ResponseComputerToolCallOutputScreenshotParam(
                type="computer_screenshot",
                image_url=image_url,
            ),
        )

    return None


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
            case "back" | "forward":
                # TODO: Code me
                # Need to extend the tool to support this
                raise NotImplementedError(f"Unsupported button: {action.button}")
    elif action.type == "double_click":
        return {"action": "double_click", "coordinate": [action.x, action.y]}
    elif action.type == "drag":
        # TODO: Code me - it takes a path
        # Need to extend the tool to support this
        raise NotImplementedError("Unsupported action: drag")
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
        mapped_keys = [mapping.get(key, key) for key in action.keys]
        return {"action": "key", "text": "+".join(mapped_keys)}
    elif action.type == "move":
        return {"action": "mouse_move", "coordinate": [action.x, action.y]}
    elif action.type == "screenshot":
        return {"action": "screenshot"}
    elif action.type == "scroll":
        # TODO: OpenAI spec's with x/y distances
        # Need to extend the tool to support this
        raise NotImplementedError("Unsupported action: scroll")
    elif action.type == "type":
        return {"action": "type", "text": action.text}
    elif action.type == "wait":
        # TODO: WTF? Their spec doesn't include a duration
        return {"action": "wait", "duration": 1}

    assert False, f"Unexpected action type: {action.type}"


def _maybe_content_image(input: str | list[Content]) -> str | None:
    return (
        next((item.image for item in input if isinstance(item, ContentImage)), None)
        if isinstance(input, list)
        else None
    )
