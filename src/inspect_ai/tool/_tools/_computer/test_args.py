import pytest

from ._resources.tool._args import parse_arguments


def test_parse_args_screenshot() -> None:
    args = parse_arguments(["screenshot"])
    assert args.action == "screenshot"


def test_parse_args_cursor_position() -> None:
    args = parse_arguments(["cursor_position"])
    assert args.action == "cursor_position"


def test_parse_args_type() -> None:
    args = parse_arguments(["type", "--text", "hello"])
    assert args.action == "type"
    assert args.text == "hello"


def test_parse_args_mouse_move() -> None:
    args = parse_arguments(["mouse_move", "--coordinate", "100", "200"])
    assert args.action == "mouse_move"
    assert args.coordinate == [100, 200]


def test_parse_args_left_click() -> None:
    args = parse_arguments(["left_click", "--coordinate", "100", "200"])
    assert args.action == "left_click"
    assert args.coordinate == [100, 200]


def test_parse_args_right_click() -> None:
    args = parse_arguments(["right_click", "--coordinate", "100", "200"])
    assert args.action == "right_click"
    assert args.coordinate == [100, 200]


def test_parse_args_middle_click() -> None:
    args = parse_arguments(["middle_click", "--coordinate", "100", "200"])
    assert args.action == "middle_click"
    assert args.coordinate == [100, 200]


def test_parse_args_double_click() -> None:
    args = parse_arguments(["double_click", "--coordinate", "100", "200"])
    assert args.action == "double_click"
    assert args.coordinate == [100, 200]


def test_parse_args_triple_click() -> None:
    args = parse_arguments(["triple_click", "--coordinate", "100", "200"])
    assert args.action == "triple_click"
    assert args.coordinate == [100, 200]


def test_parse_args_hold_key() -> None:
    args = parse_arguments(["hold_key", "--text", "a", "--duration", "5"])
    assert args.action == "hold_key"
    assert args.text == "a"
    assert args.duration == 5


def test_parse_args_left_click_drag() -> None:
    args = parse_arguments(
        [
            "left_click_drag",
            "--start_coordinate",
            "100",
            "200",
            "--coordinate",
            "300",
            "400",
            "--text",
            "drag",
        ]
    )
    assert args.action == "left_click_drag"
    assert args.start_coordinate == [100, 200]
    assert args.coordinate == [300, 400]
    assert args.text == "drag"


def test_parse_args_scroll() -> None:
    args = parse_arguments(
        [
            "scroll",
            "--scroll_direction",
            "up",
            "--scroll_amount",
            "10",
            "--coordinate",
            "100",
            "200",
        ]
    )
    assert args.action == "scroll"
    assert args.scroll_direction == "up"
    assert args.scroll_amount == 10
    assert args.coordinate == [100, 200]


def test_parse_args_wait() -> None:
    args = parse_arguments(["wait", "--duration", "5"])
    assert args.action == "wait"
    assert args.duration == 5


def test_parse_args_type_missing_text() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["type"])


def test_parse_args_invalid_action() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["invalid_action"])


def test_parse_args_mouse_move_missing_coordinate() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["mouse_move"])


def test_parse_args_click_invalid_coordinate() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["left_click", "--coordinate", "100"])


def test_parse_args_hold_key_missing_duration() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["hold_key", "--text", "a"])


def test_parse_args_left_click_drag_missing_start_coordinate() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(
            ["left_click_drag", "--coordinate", "300", "400", "--text", "drag"]
        )


def test_parse_args_scroll_missing_scroll_direction() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(
            ["scroll", "--scroll_amount", "10", "--coordinate", "100", "200"]
        )


def test_parse_args_wait_missing_duration() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["wait"])
