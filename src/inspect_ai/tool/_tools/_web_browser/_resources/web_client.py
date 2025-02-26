import argparse
import sys
from typing import Literal

from constants import DEFAULT_SESSION_NAME, SERVER_PORT
from rpc_client_helpers import RPCError, rpc_call
from web_browser_rpc_types import (
    ClickArgs,
    CrawlerBaseArgs,
    CrawlerResponse,
    GoArgs,
    NewSessionArgs,
    NewSessionResponse,
    ScrollArgs,
    TypeOrSubmitArgs,
)

_SERVER_URL = f"http://localhost:{SERVER_PORT}/"


def main() -> None:
    if len(sys.argv) > 1:
        command, params = _parse_args()
        _execute_command(command, params)
    else:
        _interactive_mode()


def _execute_command(
    command: str,
    params: NewSessionArgs
    | GoArgs
    | ClickArgs
    | TypeOrSubmitArgs
    | ScrollArgs
    | CrawlerBaseArgs,
) -> None:
    try:
        if command == "new_session":
            print(
                rpc_call(
                    _SERVER_URL, command, dict(params), NewSessionResponse
                ).session_name
            )
        else:
            response = rpc_call(
                _SERVER_URL,
                command,
                dict(params),
                CrawlerResponse,
            )
            for key, value in vars(response).items():
                if value is not None:
                    print(key, ": ", value)

    except RPCError as rpc_error:
        _return_error(f"error: {rpc_error}")


def _interactive_mode() -> None:
    print(
        "Welcome to the Playwright Crawler interactive mode!\n"
        "commands:\n"
        "  web_go <URL> - goes to the specified url.\n"
        "  web_click <ELEMENT_ID> - clicks on a given element.\n"
        "  web_scroll <up/down> - scrolls up or down one page.\n"
        "  web_forward - navigates forward a page.\n"
        "  web_back - navigates back a page.\n"
        "  web_refresh - reloads current page (F5).\n"
        "  web_type <ELEMENT_ID> <TEXT> - types the specified text into the input with the specified id.\n"
        "  web_type_submit <ELEMENT_ID> <TEXT> - types the specified text into the input with the specified id and presses ENTER to submit the form."
    )

    session_created = False
    while True:
        try:
            user_input = input("Enter command: ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            args = user_input.split()
            sys.argv = ["cli"] + args
            command, params = _parse_args()
            print(f"command: {command}, params: {params}")
            if not session_created:
                _execute_command("new_session", NewSessionArgs(headful=True))
                session_created = True
            _execute_command(command, params)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error: {e}")


def _return_error(error: str) -> None:
    print(error, file=sys.stderr)
    sys.exit(1)


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
    tuple[Literal["web_go"], GoArgs]
    | tuple[Literal["web_click"], ClickArgs]
    | tuple[Literal["web_type", "web_type_submit"], TypeOrSubmitArgs]
    | tuple[Literal["web_scroll"], ScrollArgs]
    | tuple[Literal["web_forward", "web_back", "web_refresh"], CrawlerBaseArgs]
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
            return command_args_dict["command"], GoArgs(
                url=command_args_dict["url"],
                session_name=session_name,
            )
        case "web_click":
            return command_args_dict["command"], ClickArgs(
                element_id=command_args_dict["element_id"],
                session_name=session_name,
            )
        case "web_type" | "web_type_submit":
            return command_args_dict["command"], TypeOrSubmitArgs(
                element_id=command_args_dict["element_id"],
                text=command_args_dict["text"],
                session_name=session_name,
            )
        case "web_scroll":
            return command_args_dict["command"], ScrollArgs(
                direction=command_args_dict["direction"],
                session_name=session_name,
            )
        case "web_forward" | "web_back" | "web_refresh":
            return command_args_dict["command"], CrawlerBaseArgs(
                session_name=session_name,
            )
        case _:
            raise ValueError("Unexpected command")


if __name__ == "__main__":
    main()
