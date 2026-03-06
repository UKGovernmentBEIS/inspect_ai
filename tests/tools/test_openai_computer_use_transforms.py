from openai.types.responses import ResponseComputerToolCall
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
    Type,
    Wait,
)

from inspect_ai.model._providers._openai_computer_use import (
    _PIXELS_PER_SCROLL_CLICK,
    _parse_computer_tool_call_arguments,
    maybe_computer_use_tool,
    tool_call_arguments_to_actions,
    tool_call_from_openai_computer_tool_call,
)


def _make_tool_call(
    actions: list[ComputerAction], call_id: str = "call_id"
) -> ResponseComputerToolCall:
    return ResponseComputerToolCall(
        id="test_id",
        actions=actions,
        call_id=call_id,
        pending_safety_checks=[],
        status="completed",
        type="computer_call",
    )


def test_left_click_bidirectional():
    args = {"action": "left_click", "coordinate": [100, 200]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Click)
    assert action.type == "click"
    assert action.button == "left"
    assert action.x == 100
    assert action.y == 200

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([Click(type="click", button="left", x=100, y=200)])
    )
    assert parsed == {"actions": [args]}


def test_right_click_bidirectional():
    args = {"action": "right_click", "coordinate": [50, 75]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Click)
    assert action.button == "right"
    assert action.x == 50
    assert action.y == 75

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([Click(type="click", button="right", x=50, y=75)])
    )
    assert parsed == {"actions": [args]}


def test_middle_click_bidirectional():
    args = {"action": "middle_click", "coordinate": [300, 400]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Click)
    assert action.button == "wheel"
    assert action.x == 300
    assert action.y == 400

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([Click(type="click", button="wheel", x=300, y=400)])
    )
    assert parsed == {"actions": [args]}


def test_double_click_bidirectional():
    args = {"action": "double_click", "coordinate": [150, 250]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, DoubleClick)
    assert action.type == "double_click"
    assert action.x == 150
    assert action.y == 250

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([DoubleClick(type="double_click", x=150, y=250)])
    )
    assert parsed == {"actions": [args]}


def test_triple_click_maps_to_double_click():
    # Triple click doesn't exist in OpenAI spec, should map to double click
    args = {"action": "triple_click", "coordinate": [100, 100]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, DoubleClick)
    assert action.type == "double_click"
    assert action.x == 100
    assert action.y == 100


def test_drag_bidirectional():
    args = {
        "action": "left_click_drag",
        "start_coordinate": [10, 20],
        "coordinate": [100, 200],
    }
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Drag)
    assert action.type == "drag"
    assert len(action.path) == 2
    assert action.path[0].x == 10
    assert action.path[0].y == 20
    assert action.path[1].x == 100
    assert action.path[1].y == 200

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call(
            [Drag(type="drag", path=[DragPath(x=10, y=20), DragPath(x=100, y=200)])]
        )
    )
    assert parsed == {"actions": [args]}


def test_keypress_with_special_keys():
    args = {"action": "key", "text": "Return+Tab+space"}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Keypress)
    assert action.type == "keypress"
    assert action.keys == ["Return", "Tab", "space"]

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([Keypress(type="keypress", keys=["ENTER", "TAB", "SPACE"])])
    )
    assert parsed == {"actions": [{"action": "key", "text": "ENTER+TAB+SPACE"}]}


def test_keypress_with_regular_keys():
    args = {"action": "key", "text": "ctrl+c"}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Keypress)
    assert action.keys == ["ctrl", "c"]


def test_mouse_move_bidirectional():
    args = {"action": "mouse_move", "coordinate": [500, 600]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Move)
    assert action.type == "move"
    assert action.x == 500
    assert action.y == 600

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([Move(type="move", x=500, y=600)])
    )
    assert parsed == {"actions": [args]}


def test_cursor_position_maps_to_move():
    args = {"action": "cursor_position", "coordinate": [123, 456]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Move)
    assert action.x == 123
    assert action.y == 456


def test_screenshot_bidirectional():
    args = {"action": "screenshot"}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Screenshot)
    assert action.type == "screenshot"

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([Screenshot(type="screenshot")])
    )
    assert parsed == {"actions": [args]}


def test_scroll_down():
    args = {
        "action": "scroll",
        "coordinate": [200, 300],
        "scroll_direction": "down",
        "scroll_amount": 5,
    }
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Scroll)
    assert action.type == "scroll"
    assert action.x == 200
    assert action.y == 300
    assert action.scroll_x == 0
    assert action.scroll_y == 5 * _PIXELS_PER_SCROLL_CLICK


def test_scroll_up():
    args = {
        "action": "scroll",
        "coordinate": [100, 100],
        "scroll_direction": "up",
        "scroll_amount": 3,
    }
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Scroll)
    assert action.scroll_x == 0
    assert action.scroll_y == -3 * _PIXELS_PER_SCROLL_CLICK


def test_scroll_left():
    args = {
        "action": "scroll",
        "coordinate": [100, 100],
        "scroll_direction": "left",
        "scroll_amount": 2,
    }
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Scroll)
    assert action.scroll_x == -2 * _PIXELS_PER_SCROLL_CLICK
    assert action.scroll_y == 0


def test_scroll_right():
    args = {
        "action": "scroll",
        "coordinate": [100, 100],
        "scroll_direction": "right",
        "scroll_amount": 4,
    }
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Scroll)
    assert action.scroll_x == 4 * _PIXELS_PER_SCROLL_CLICK
    assert action.scroll_y == 0


def test_type_text_bidirectional():
    args = {"action": "type", "text": "Hello, World!"}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Type)
    assert action.type == "type"
    assert action.text == "Hello, World!"

    parsed = _parse_computer_tool_call_arguments(
        _make_tool_call([Type(type="type", text="Hello, World!")])
    )
    assert parsed == {"actions": [args]}


def test_wait_action():
    # Wait doesn't support duration in OpenAI spec
    args = {"action": "wait", "duration": 5}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Wait)
    assert action.type == "wait"

    parsed = _parse_computer_tool_call_arguments(_make_tool_call([Wait(type="wait")]))
    # Duration is hardcoded to 1 in the reverse transform
    assert parsed == {"actions": [{"action": "wait", "duration": 1}]}


def test_left_mouse_down_maps_to_move():
    # No direct equivalent in OpenAI spec
    args = {"action": "left_mouse_down", "coordinate": [50, 50]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Move)
    assert action.x == 50
    assert action.y == 50


def test_left_mouse_up_maps_to_move():
    # No direct equivalent in OpenAI spec
    args = {"action": "left_mouse_up", "coordinate": [60, 60]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Move)
    assert action.x == 60
    assert action.y == 60


def test_unknown_action_defaults_to_screenshot():
    args = {"action": "unknown_action"}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Screenshot)
    assert action.type == "screenshot"


def test_multi_action_parse():
    tool_call = _make_tool_call(
        [
            Click(type="click", button="left", x=100, y=200),
            Type(type="type", text="hello"),
            Screenshot(type="screenshot"),
        ]
    )
    parsed = _parse_computer_tool_call_arguments(tool_call)
    assert parsed == {
        "actions": [
            {"action": "left_click", "coordinate": [100, 200]},
            {"action": "type", "text": "hello"},
            {"action": "screenshot"},
        ]
    }


def test_tool_call_wraps_actions():
    tool_call = _make_tool_call(
        [
            Click(type="click", button="left", x=100, y=200),
            Type(type="type", text="hello"),
            Screenshot(type="screenshot"),
        ],
        call_id="call_123",
    )
    result = tool_call_from_openai_computer_tool_call(tool_call)
    assert result.id == "call_123"
    assert result.function == "computer"
    assert result.arguments == {
        "actions": [
            {"action": "left_click", "coordinate": [100, 200]},
            {"action": "type", "text": "hello"},
            {"action": "screenshot"},
        ]
    }


def test_multi_action_reverse_transform():
    arguments = {
        "actions": [
            {"action": "left_click", "coordinate": [100, 200]},
            {"action": "type", "text": "hello"},
            {"action": "screenshot"},
        ]
    }
    actions = tool_call_arguments_to_actions(arguments)
    assert len(actions) == 3
    assert isinstance(actions[0], Click)
    assert isinstance(actions[1], Type)
    assert isinstance(actions[2], Screenshot)


def _computer_tool_info():
    """Helper to create a ToolInfo matching the computer tool signature."""
    from inspect_ai.tool._tool_info import ToolInfo, ToolParams

    return ToolInfo(
        name="computer",
        description="computer tool",
        parameters=ToolParams(
            properties={
                k: {}
                for k in [
                    "action",
                    "coordinate",
                    "duration",
                    "region",
                    "scroll_amount",
                    "scroll_direction",
                    "start_coordinate",
                    "text",
                    "actions",
                ]
            }
        ),
    )


def test_maybe_computer_use_tool_gpt54():
    tool = _computer_tool_info()
    result = maybe_computer_use_tool("gpt-5.4", tool)
    assert result is not None
    assert result["type"] == "computer"
    # No display dimensions needed
    assert "display_width" not in result
    assert "display_height" not in result


def test_maybe_computer_use_tool_non_matching_model():
    tool = _computer_tool_info()
    assert maybe_computer_use_tool("gpt-4o", tool) is None
    assert maybe_computer_use_tool("computer-use-preview", tool) is None


def test_maybe_computer_use_tool_non_computer_tool():
    from inspect_ai.tool._tool_info import ToolInfo, ToolParams

    tool = ToolInfo(name="bash", description="bash", parameters=ToolParams())
    assert maybe_computer_use_tool("gpt-5.4", tool) is None


def test_back_and_forward_click():
    # Test back click
    args = {"action": "back_click", "coordinate": [10, 10]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Click)
    assert action.button == "back"

    # Test forward click
    args = {"action": "forward_click", "coordinate": [20, 20]}
    action = tool_call_arguments_to_actions({"actions": [args]})[0]

    assert isinstance(action, Click)
    assert action.button == "forward"
