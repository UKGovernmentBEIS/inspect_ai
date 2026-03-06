from collections.abc import Iterable

from openai.types.responses import (
    ComputerUseToolParam,
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
) -> ComputerUseToolParam | None:
    return (
        ComputerUseToolParam(type="computer")
        if "gpt-5.4" in model_name
        and tool.name == "computer"
        and (sorted(tool.parameters.properties.keys()) == sorted(computer_parameters()))
        else None
    )


def computer_parameters() -> list[str]:
    return [
        "action",
        "coordinate",
        "duration",
        "region",
        "scroll_amount",
        "scroll_direction",
        "start_coordinate",
        "text",
    ]


def computer_call_output(
    message: ChatMessageTool,
    computer_call_id: str,
    pending_safety_checks: Iterable[PendingSafetyCheck] | None = None,
) -> ComputerCallOutput:
    return ComputerCallOutput(
        call_id=computer_call_id,
        type="computer_call_output",
        output=ResponseComputerToolCallOutputScreenshotParam(
            type="computer_screenshot",
            image_url=_content_image(message.content),
        ),
        # PendingSafetyCheck and ComputerCallOutputAcknowledgedSafetyCheck are structurally
        # identical TypedDicts, so this assignment is type-safe.
        acknowledged_safety_checks=pending_safety_checks,
    )


def tool_call_arguments_to_actions(
    arguments: dict[str, object],
) -> list[ComputerAction]:
    actions_list = arguments.get("actions")
    assert isinstance(actions_list, list), "Expected 'actions' list in arguments"
    return [_single_arg_to_action(a) for a in actions_list]


def _single_arg_to_action(arguments: dict[str, object]) -> ComputerAction:
    action_type = str(arguments.get("action", ""))
    action: ComputerAction

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
        action = Click(
            type="click",
            button=button_map[action_type],  # type: ignore[arg-type]
            x=coordinate[0],  # type: ignore[index]
            y=coordinate[1],  # type: ignore[index]
        )
    elif action_type == "double_click":
        coordinate = arguments.get("coordinate", [0, 0])
        action = DoubleClick(
            type="double_click",
            x=coordinate[0],  # type: ignore[index]
            y=coordinate[1],  # type: ignore[index]
        )
    elif action_type == "triple_click":
        # Triple click doesn't exist in OpenAI's spec, map to double click
        coordinate = arguments.get("coordinate", [0, 0])
        action = DoubleClick(
            type="double_click",
            x=coordinate[0],  # type: ignore[index]
            y=coordinate[1],  # type: ignore[index]
        )
    elif action_type == "left_click_drag":
        start_coordinate = arguments.get("start_coordinate", [0, 0])
        end_coordinate = arguments.get("coordinate", [0, 0])
        action = Drag(
            type="drag",
            path=[
                DragPath(x=start_coordinate[0], y=start_coordinate[1]),  # type: ignore[index]
                DragPath(x=end_coordinate[0], y=end_coordinate[1]),  # type: ignore[index]
            ],
        )
    elif action_type in ["key", "hold_key"]:
        text = str(arguments.get("text", ""))
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
        keys = [reverse_mapping.get(key, key) for key in text.split("+")]
        action = Keypress(
            type="keypress",
            keys=keys,
        )
    elif action_type in ["mouse_move", "cursor_position"]:
        coordinate = arguments.get("coordinate", [0, 0])
        action = Move(
            type="move",
            x=coordinate[0],  # type: ignore[index]
            y=coordinate[1],  # type: ignore[index]
        )
    elif action_type == "screenshot":
        action = Screenshot(type="screenshot")
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

        action = Scroll(
            type="scroll",
            x=coordinate[0],  # type: ignore[index]
            y=coordinate[1],  # type: ignore[index]
            scroll_x=scroll_x,
            scroll_y=scroll_y,
        )
    elif action_type == "type":
        text = str(arguments.get("text", ""))
        action = TypeAction(
            type="type",
            text=text,
        )
    elif action_type == "wait":
        action = Wait(type="wait")
    elif action_type in ["left_mouse_down", "left_mouse_up"]:
        coordinate = arguments.get("coordinate", [0, 0])
        action = Move(
            type="move",
            x=coordinate[0],  # type: ignore[index]
            y=coordinate[1],  # type: ignore[index]
        )
    else:
        action = Screenshot(type="screenshot")

    return action


def _parse_computer_tool_call_arguments(
    output: ResponseComputerToolCall,
) -> dict[str, object]:
    actions = output.actions
    assert actions, "Expected actions array in computer_call"
    return {"actions": [_parse_single_action(action) for action in actions]}


def _parse_single_action(action: ComputerAction) -> dict[str, object]:
    if isinstance(action, Click):
        button_map = {
            "left": "left_click",
            "right": "right_click",
            "wheel": "middle_click",
            "back": "back_click",
            "forward": "forward_click",
        }
        return {
            "action": button_map[action.button],
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
    elif isinstance(action, Move):
        return {"action": "mouse_move", "coordinate": [action.x, action.y]}
    elif isinstance(action, Screenshot):
        return {"action": "screenshot"}
    elif isinstance(action, Scroll):
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
    elif isinstance(action, TypeAction):
        return {"action": "type", "text": action.text}
    elif isinstance(action, Wait):
        return {"action": "wait", "duration": 1}

    assert False, f"Unexpected action type: {type(action)}"


def _content_image(input: str | list[Content]) -> str:
    result = (
        next((item.image for item in input if isinstance(item, ContentImage)), None)
        if isinstance(input, list)
        else None
    )
    assert result, "Must find image in content"
    return result
