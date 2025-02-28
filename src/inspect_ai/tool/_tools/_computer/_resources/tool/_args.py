from argparse import Action, ArgumentParser, Namespace
from typing import Sequence


def parse_arguments(args: Sequence[str] | None = None) -> Namespace:
    return _create_parser().parse_args(args)


def _create_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="computer_tool")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # these take no additional arguments
    subparsers.add_parser(
        "screenshot",
        aliases=["cursor_position", "left_mouse_down", "left_mouse_up"],
    )

    key_and_type = subparsers.add_parser("type", aliases=["key"])
    _add_text(key_and_type)

    hold_key = subparsers.add_parser("hold_key")
    _add_text(hold_key)
    _add_duration(hold_key)

    mouse_move = subparsers.add_parser("mouse_move")
    _add_coordinate(mouse_move)

    click = subparsers.add_parser(
        "left_click",
        aliases=["right_click", "middle_click", "double_click", "triple_click"],
    )
    _add_coordinate(click, False)
    _add_text(click, False)

    left_click_drag = subparsers.add_parser("left_click_drag")
    _add_start_coordinate(left_click_drag)
    _add_coordinate(left_click_drag)
    _add_text(left_click_drag, False)

    scroll = subparsers.add_parser("scroll")
    _add_scroll_direction(scroll)
    _add_scroll_amount(scroll)
    # despite what the doc says, the model doesn't always provide a coordinate
    _add_coordinate(scroll, False)

    wait = subparsers.add_parser("wait")
    _add_duration(wait)

    return parser


def _add_scroll_direction(subparser: ArgumentParser) -> Action:
    return subparser.add_argument(
        "--scroll_direction", choices=["up", "down", "left", "right"], required=True
    )


def _add_scroll_amount(subparser: ArgumentParser) -> Action:
    return subparser.add_argument("--scroll_amount", type=int, required=True)


def _add_coordinate(subparser: ArgumentParser, required: bool = True) -> Action:
    return subparser.add_argument("--coordinate", type=int, nargs=2, required=required)


def _add_start_coordinate(subparser: ArgumentParser) -> Action:
    return subparser.add_argument(
        "--start_coordinate", type=int, nargs=2, required=True
    )


def _add_duration(subparser: ArgumentParser) -> Action:
    return subparser.add_argument("--duration", type=int, required=True)


def _add_text(subparser: ArgumentParser, required: bool = True) -> Action:
    return subparser.add_argument("--text", type=str, required=required)
