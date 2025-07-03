import argparse
import asyncio
import subprocess
import sys
from typing import Literal

import psutil
from jsonrpcserver import async_dispatch
from pydantic import BaseModel

from inspect_tool_support._cli._post_install import post_install
from inspect_tool_support._cli.server import main as server_main
from inspect_tool_support._util.common_types import JSONRPCResponseJSON
from inspect_tool_support._util.constants import SERVER_PORT
from inspect_tool_support._util.json_rpc_helpers import json_rpc_http_call
from inspect_tool_support._util.load_tools import load_tools

_SERVER_URL = f"http://localhost:{SERVER_PORT}/"


class JSONRPCIncoming(BaseModel):
    jsonrpc: Literal["2.0"]
    method: str
    params: list[object] | dict[str, object] | None = None


class JSONRPCRequest(JSONRPCIncoming):
    id: int | float | str


class JSONRPCNotification(JSONRPCIncoming):
    pass


def main() -> None:
    args = _parse_args()
    match args.command:
        case "exec":
            asyncio.run(_exec(args.request))
        case "post-install":
            post_install(no_web_browser=args.no_web_browser)
        case "server":
            server_main()


# Example/testing requests
# {"jsonrpc": "2.0", "method": "editor", "id": 666, "params": {"command": "view", "path": "/tmp"}}
# {"jsonrpc": "2.0", "method": "bash", "id": 666, "params": {"command": "ls ~/Downloads"}}
async def _exec(request: str | None) -> None:
    in_process_tools = load_tools("inspect_tool_support._in_process_tools")

    request_json_str = request or sys.stdin.read().strip()
    tool_name = JSONRPCIncoming.model_validate_json(request_json_str).method
    assert isinstance(tool_name, str)

    print(
        await (
            _dispatch_local_method
            if tool_name in in_process_tools
            else _dispatch_remote_method
        )(request_json_str)
    )


async def _dispatch_local_method(request_json_str: str) -> JSONRPCResponseJSON:
    return JSONRPCResponseJSON(await async_dispatch(request_json_str))


async def _dispatch_remote_method(request_json_str: str) -> JSONRPCResponseJSON:
    _ensure_server_is_running()
    return await json_rpc_http_call(_SERVER_URL, request_json_str)


def _ensure_server_is_running() -> None:
    # TODO: Pipe stdout and stderr to proc 1
    if not any(
        (cmdline := x.info["cmdline"])
        and len(cmdline) >= 2
        and cmdline[-1] == "server"
        and cmdline[-2].endswith("/inspect-tool-support")
        for x in psutil.process_iter(["name", "cmdline"])
    ):
        subprocess.Popen(
            ["inspect-tool-support", "server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Tool Support CLI")
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Command to execute"
    )
    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument(dest="request", type=str, nargs="?")
    subparsers.add_parser("server")
    post_install_parser = subparsers.add_parser("post-install")
    post_install_parser.add_argument("--no-web-browser", action="store_true")

    return parser.parse_args()


if __name__ == "__main__":
    main()
