from openai.types.responses import ResponseComputerToolCall
from openai.types.responses.response_computer_tool_call import (
    ActionClick,
    ActionDoubleClick,
    ActionDrag,
    ActionKeypress,
    ActionMove,
    ActionScreenshot,
    ActionScroll,
    ActionType,
    ActionWait,
)

from inspect_ai.model._providers._openai_computer_use import (
    _parse_computer_tool_call_arguments,
    tool_call_arguments_to_action,
)


def test_left_click_bidirectional():
    # Test left click transformation
    args = {"action": "left_click", "coordinate": [100, 200]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionClick)
    assert action.type == "click"
    assert action.button == "left"
    assert action.x == 100
    assert action.y == 200

    # Test reverse transformation
    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_right_click_bidirectional():
    args = {"action": "right_click", "coordinate": [50, 75]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionClick)
    assert action.button == "right"
    assert action.x == 50
    assert action.y == 75

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_middle_click_bidirectional():
    args = {"action": "middle_click", "coordinate": [300, 400]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionClick)
    assert action.button == "wheel"
    assert action.x == 300
    assert action.y == 400

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_double_click_bidirectional():
    args = {"action": "double_click", "coordinate": [150, 250]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionDoubleClick)
    assert action.type == "double_click"
    assert action.x == 150
    assert action.y == 250

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_triple_click_maps_to_double_click():
    # Triple click doesn't exist in OpenAI spec, should map to double click
    args = {"action": "triple_click", "coordinate": [100, 100]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionDoubleClick)
    assert action.type == "double_click"
    assert action.x == 100
    assert action.y == 100


def test_drag_bidirectional():
    args = {
        "action": "left_click_drag",
        "start_coordinate": [10, 20],
        "coordinate": [100, 200],
    }
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionDrag)
    assert action.type == "drag"
    assert len(action.path) == 2
    assert action.path[0].x == 10
    assert action.path[0].y == 20
    assert action.path[1].x == 100
    assert action.path[1].y == 200

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_keypress_with_special_keys():
    args = {"action": "key", "text": "Return+Tab+space"}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionKeypress)
    assert action.type == "keypress"
    assert action.keys == ["ENTER", "TAB", "SPACE"]

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == {"action": "key", "text": "Return+Tab+space"}


def test_keypress_with_regular_keys():
    args = {"action": "key", "text": "ctrl+c"}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionKeypress)
    assert action.keys == ["ctrl", "c"]


def test_mouse_move_bidirectional():
    args = {"action": "mouse_move", "coordinate": [500, 600]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionMove)
    assert action.type == "move"
    assert action.x == 500
    assert action.y == 600

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_cursor_position_maps_to_move():
    args = {"action": "cursor_position", "coordinate": [123, 456]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionMove)
    assert action.x == 123
    assert action.y == 456


def test_screenshot_bidirectional():
    args = {"action": "screenshot"}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionScreenshot)
    assert action.type == "screenshot"

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_scroll_down():
    args = {
        "action": "scroll",
        "coordinate": [200, 300],
        "scroll_direction": "down",
        "scroll_amount": 5,
    }
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionScroll)
    assert action.type == "scroll"
    assert action.x == 200
    assert action.y == 300
    assert action.scroll_x == 0
    assert action.scroll_y == 5


def test_scroll_up():
    args = {
        "action": "scroll",
        "coordinate": [100, 100],
        "scroll_direction": "up",
        "scroll_amount": 3,
    }
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionScroll)
    assert action.scroll_x == 0
    assert action.scroll_y == -3


def test_scroll_left():
    args = {
        "action": "scroll",
        "coordinate": [100, 100],
        "scroll_direction": "left",
        "scroll_amount": 2,
    }
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionScroll)
    assert action.scroll_x == -2
    assert action.scroll_y == 0


def test_scroll_right():
    args = {
        "action": "scroll",
        "coordinate": [100, 100],
        "scroll_direction": "right",
        "scroll_amount": 4,
    }
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionScroll)
    assert action.scroll_x == 4
    assert action.scroll_y == 0


def test_type_text_bidirectional():
    args = {"action": "type", "text": "Hello, World!"}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionType)
    assert action.type == "type"
    assert action.text == "Hello, World!"

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == args


def test_wait_action():
    # Wait doesn't support duration in OpenAI spec
    args = {"action": "wait", "duration": 5}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionWait)
    assert action.type == "wait"

    tool_call = ResponseComputerToolCall(
        id="test_id",
        action=action,
        call_id="call_id",
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    # Duration is hardcoded to 1 in the reverse transform
    assert parsed == {"action": "wait", "duration": 1}


def test_left_mouse_down_maps_to_move():
    # No direct equivalent in OpenAI spec
    args = {"action": "left_mouse_down", "coordinate": [50, 50]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionMove)
    assert action.x == 50
    assert action.y == 50


def test_left_mouse_up_maps_to_move():
    # No direct equivalent in OpenAI spec
    args = {"action": "left_mouse_up", "coordinate": [60, 60]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionMove)
    assert action.x == 60
    assert action.y == 60


def test_unknown_action_defaults_to_screenshot():
    args = {"action": "unknown_action"}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionScreenshot)
    assert action.type == "screenshot"


def test_back_and_forward_click():
    # Test back click
    args = {"action": "back_click", "coordinate": [10, 10]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionClick)
    assert action.button == "back"

    # Test forward click
    args = {"action": "forward_click", "coordinate": [20, 20]}
    action = tool_call_arguments_to_action(args)

    assert isinstance(action, ActionClick)
    assert action.button == "forward"
