import asyncio
import json
import logging
import os
import sys
import time
from argparse import Namespace
from typing import TypeVar

from _args import parse_arguments
from _constants import Action
from _logger import setup_logger
from _tool_result import ToolResult
from _x11_client import X11Client


class ComputerToolError(Exception):
    def __init__(self, message):
        self.message = message


# This is a bit sketchy. We really want to use relative imports here. Using absolute imports
# works at runtime, but it prevents intellisense from working. However, when this folder is
# copied to the container, by default relative imports won't work if this file is launched
# normally. To overcome this, two things need to happen:
# 1. PYTHONPATH must be set to the parent of the container folder. `PYTHONPATH=/opt`
# 2. The program must be launched with the -m flag. `python3 -m computer_tool.computer_tool`
#
# TODO: There's got to be a cleaner way.

my_logger = setup_logger(logging.INFO)


def main():
    try:
        args = parse_arguments()
        my_logger.info(f"({args})")
        result = asyncio.run(execute_action(args))

        print(
            json.dumps(
                {
                    "output": result.output,
                    "error": result.error,
                    "base64_image": result.base64_image,
                }
            )
        )
        my_logger.debug("SUCCESS")
    except Exception as e:
        my_logger.warning(f"An error occurred: {e}")
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


async def execute_action(args: Namespace) -> ToolResult:
    # we can't do anything until X11 is ready to go.
    await wait_for_file("/tmp/xfce_started")

    computer = X11Client()
    action: Action = args.action
    match action:
        case "key":
            return await computer.key(not_none(args.text, "text"))
        case "hold_key":
            return await computer.hold_key(
                not_none(args.text, "text"), not_none(args.duration, "duration")
            )
        case "type":
            return await computer.type(not_none(args.text, "text"))
        case "cursor_position":
            return await computer.cursor_position()
        case "left_mouse_down":
            return await computer.left_mouse_down()
        case "left_mouse_up":
            return await computer.left_mouse_up()
        case "mouse_move":
            return await computer.mouse_move(not_none(args.coordinate, "coordinate"))
        case "left_click":
            return await computer.left_click(
                getattr(args, "coordinate", None), getattr(args, "text", None)
            )
        case "right_click":
            return await computer.right_click(
                getattr(args, "coordinate", None), getattr(args, "text", None)
            )
        case "middle_click":
            return await computer.middle_click(
                getattr(args, "coordinate", None), getattr(args, "text", None)
            )
        case "double_click":
            return await computer.double_click(
                getattr(args, "coordinate", None), getattr(args, "text", None)
            )
        case "triple_click":
            return await computer.triple_click(
                getattr(args, "coordinate", None), getattr(args, "text", None)
            )
        case "left_click_drag":
            return await computer.left_click_drag(
                not_none(args.start_coordinate, "start_coordinate"),
                not_none(args.coordinate, "coordinate"),
            )
        case "scroll":
            return await computer.scroll(
                not_none(args.scroll_direction, "scroll_direction"),
                not_none(args.scroll_amount, "scroll_amount"),
                getattr(args, "coordinate", None),
                getattr(args, "text", None),
            )
        case "wait":
            return await computer.wait(not_none(args.duration, "duration"))
        case "screenshot":
            return await computer.screenshot()

    raise ComputerToolError(f"Invalid action: {action}")


async def wait_for_file(file_path, check_interval=1):
    if os.path.exists(file_path):
        return
    my_logger.info(f"Waiting for {file_path}")
    start_time = time.time()
    while not os.path.exists(file_path):
        await asyncio.sleep(check_interval)
    my_logger.info(
        f"Done waiting for {file_path} after {time.time() - start_time:.1f} seconds"
    )


T = TypeVar("T")


def not_none(value: T | None, name: str) -> T:
    if value is None:
        raise ComputerToolError(f"{name} must be provided")
    return value


if __name__ == "__main__":
    main()
