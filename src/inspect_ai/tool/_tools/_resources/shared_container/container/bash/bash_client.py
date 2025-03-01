import argparse
import sys

from pydantic import BaseModel

from bash.constants import SERVER_PORT
from rpc_client_helpers import RPCError, rpc_call

_SERVER_URL = f"http://localhost:{SERVER_PORT}/"


class CommandResponse(BaseModel):
    status: int
    stdout: str
    stderr: str


def main() -> None:
    if len(sys.argv) > 1:
        _execute_command(parser.parse_args())
    else:
        _interactive_mode()


def _execute_command(namespace: argparse.Namespace) -> None:
    try:
        response = (
            rpc_call(_SERVER_URL, "restart", None, CommandResponse)
            if namespace.restart
            else rpc_call(
                _SERVER_URL, "restart", {"command": namespace.command}, CommandResponse
            )
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
        "  command <cmd> - The bash command to run.\n"
        "  restart - This will restart this tool."
    )

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


def _create_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="bash_client")

    group = result.add_mutually_exclusive_group(required=True)
    group.add_argument("--command", type=str, help="The bash command to run.")
    group.add_argument("--restart", action="store_true", help="Restart the tool.")

    return result


parser = _create_parser()


if __name__ == "__main__":
    main()
