import argparse
import asyncio
import json
import logging
import os
import sys

from _tool_result import ToolResult
from _x11_client import X11Client


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
    computer = X11Client(color_count=64)
    return await computer(
        action=args.action,
        text=args.text,
        coordinate=args.coordinate if args.coordinate else None,
    )


def main():
    logging.basicConfig(
        filename=os.path.join("/tmp", "computer_tool.log"),
        filemode="a",
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.DEBUG,
    )

    try:
        args = parse_arguments()
        logging.info(f"Starting computer_tool CLI for {args}")
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
        logging.info(f"Execution of {args} successful")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
