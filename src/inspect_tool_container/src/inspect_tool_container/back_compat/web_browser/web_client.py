"""
This script provides a backward compatible CLI for web browser commands.

It is intended for backwards compatibility only, adapting the old, deprecated CLI to the new version supported by `multi_tool_v1.py`.
"""

import argparse
import json
import subprocess
import sys
from typing import Literal

from constants import DEFAULT_SESSION_NAME
from tool_types import (
    ClickParams,
    CrawlerBaseParams,
    GoParams,
    ScrollParams,
    TypeOrSubmitParams,
)


def main() -> None:
    command, params = _parse_args()
    result = subprocess.run(
        [
            "python",
            "multi_tool_v1.py",
            command,
            json.dumps(vars(params)),
        ],
        cwd="/opt/inspect",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    for key, value in json.loads(result.stdout).items():
        if value is not None:
            print(key, ": ", value)

    sys.exit(result.returncode)


def _create_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="web_client")
    parser.add_argument(
        "--session_name",
        type=str,
        required=False,
        default=DEFAULT_SESSION_NAME,
        help="Session name",
    )
    return parser


def _create_command_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="web_client")

    subparsers = result.add_subparsers(dest="command", required=True)

    go_parser = subparsers.add_parser("web_go")
    go_parser.add_argument("url", type=str, help="URL to navigate to")

    click_parser = subparsers.add_parser("web_click")
    click_parser.add_argument("element_id", type=str, help="ID of the element to click")

    scroll_parser = subparsers.add_parser("web_scroll")
    scroll_parser.add_argument(
        "direction",
        type=str,
        choices=["up", "down"],
        help="Direction to scroll (up or down)",
    )
    subparsers.add_parser("web_forward")
    subparsers.add_parser("web_back")
    subparsers.add_parser("web_refresh")

    type_parser = subparsers.add_parser("web_type")
    type_parser.add_argument(
        "element_id", type=str, help="ID of the element to type into"
    )
    type_parser.add_argument("text", type=str, help="The text to type")

    submit_parser = subparsers.add_parser("web_type_submit")
    submit_parser.add_argument(
        "element_id",
        type=str,
        help="ID of the element to type into and submit",
    )
    submit_parser.add_argument("text", type=str, help="The text to type")

    # Add common argument to all subparsers
    for name, subparser in subparsers.choices.items():
        if name != "new_session":
            subparser.add_argument(
                "--session_name",
                type=str,
                nargs="?",
                required=False,
                default=DEFAULT_SESSION_NAME,
                help="Session name",
            )

    return result


main_parser = _create_main_parser()
command_parser = _create_command_parser()


def _parse_args() -> (
    tuple[Literal["web_go"], GoParams]
    | tuple[Literal["web_click"], ClickParams]
    | tuple[Literal["web_type", "web_type_submit"], TypeOrSubmitParams]
    | tuple[Literal["web_scroll"], ScrollParams]
    | tuple[Literal["web_forward", "web_back", "web_refresh"], CrawlerBaseParams]
):
    # web_client.py supports a very non-standard command line. It has a required named
    # parameter, --session_name, before the command.
    # Unfortunately, because we can't break backwards compatibility, we're stuck
    # with that. To properly parse it, we'll be forced to have a separate parser
    # for --session_name and merge the results with the normal command parser.

    main_args, remaining_args = main_parser.parse_known_args()
    session_name = main_args.session_name or DEFAULT_SESSION_NAME

    command_args = command_parser.parse_args(remaining_args)
    command_args_dict = vars(command_args)

    match command_args.command:
        case "web_go":
            return command_args_dict["command"], GoParams(
                url=command_args_dict["url"],
                session_name=session_name,
            )
        case "web_click":
            return command_args_dict["command"], ClickParams(
                element_id=command_args_dict["element_id"],
                session_name=session_name,
            )
        case "web_type" | "web_type_submit":
            return command_args_dict["command"], TypeOrSubmitParams(
                element_id=command_args_dict["element_id"],
                text=command_args_dict["text"],
                session_name=session_name,
            )
        case "web_scroll":
            return command_args_dict["command"], ScrollParams(
                direction=command_args_dict["direction"],
                session_name=session_name,
            )
        case "web_forward" | "web_back" | "web_refresh":
            return command_args_dict["command"], CrawlerBaseParams(
                session_name=session_name,
            )
        case _:
            raise ValueError("Unexpected command")


if __name__ == "__main__":
    main()
