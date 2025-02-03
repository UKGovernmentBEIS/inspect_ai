import argparse
import asyncio
import json
import logging
import os
import sys
import time

from _logger import setup_logger
from _tool_result import ToolResult
from _x11_client import X11Client

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


def parse_arguments():
    parser = argparse.ArgumentParser(description="Execute computer tool action")
    parser.add_argument("--action", type=str, required=True, help="Action to perform")
    parser.add_argument("--text", type=str, help="Optional text parameter")
    parser.add_argument(
        "--coordinate",
        type=int,
        nargs=2,
        help="Optional coordinate parameter as a list of two integers",
    )
    return parser.parse_args()


async def execute_action(args) -> ToolResult:
    # we can't do anything until X11 is ready to go.
    await wait_for_file("/tmp/xfce_started")

    computer = X11Client()
    return await computer(
        action=args.action,
        text=args.text,
        coordinate=args.coordinate if args.coordinate else None,
    )


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


if __name__ == "__main__":
    main()
