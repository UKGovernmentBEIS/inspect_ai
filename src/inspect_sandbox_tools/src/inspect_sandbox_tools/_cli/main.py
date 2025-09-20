import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from typing import Literal

from jsonrpcserver import async_dispatch
from pydantic import BaseModel

from inspect_sandbox_tools._agent_bridge.proxy import run_model_proxy_server
from inspect_sandbox_tools._cli.server import main as server_main
from inspect_sandbox_tools._util.common_types import JSONRPCResponseJSON
from inspect_sandbox_tools._util.constants import SOCKET_PATH
from inspect_sandbox_tools._util.json_rpc_helpers import json_rpc_unix_call
from inspect_sandbox_tools._util.load_tools import load_tools


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
        case "healthcheck":
            healthcheck()
        case "exec":
            asyncio.run(_exec(args.request))
        case "server":
            server_main()
        case "model_proxy":
            asyncio.run(run_model_proxy_server())


def healthcheck():
    asyncio.run(_exec('{"jsonrpc": "2.0", "method": "version", "id": 666}'))
    asyncio.run(_exec('{"jsonrpc": "2.0", "method": "remote_version", "id": 667}'))


# Example/testing requests
# {"jsonrpc": "2.0", "method": "editor", "id": 666, "params": {"command": "view", "path": "/tmp"}}
# {"jsonrpc": "2.0", "method": "bash", "id": 666, "params": {"command": "ls ~/Downloads"}}
async def _exec(request: str | None) -> None:
    in_process_tools = load_tools("inspect_sandbox_tools._in_process_tools")

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
    return await json_rpc_unix_call(str(SOCKET_PATH), request_json_str)


def _ensure_server_is_running() -> None:
    # TODO: Pipe stdout and stderr to proc 1
    if _can_connect_to_socket():
        return  # Server already running and responsive

    # Get the correct executable path for staticx bundled executables. When running
    # under staticx, sys.argv[0] points to the extracted temp executable which gets
    # deleted when the parent process exits, breaking the server. The STATICX_PROG_PATH
    # env var provides the absolute path of the program being executed.
    executable_path = os.environ.get("STATICX_PROG_PATH")
    if executable_path is None:
        raise RuntimeError("STATICX_PROG_PATH environment variable not found. ")

    # Start server (it will handle socket cleanup on startup)
    process = subprocess.Popen(
        [executable_path, "server"],
    )

    # Wait for socket to become available
    for _ in range(200):  # Wait up to 20 seconds
        if _can_connect_to_socket():
            return
        time.sleep(0.1)

    process.kill()
    raise RuntimeError(f"Server ({process.pid}) failed to start within 20 seconds")


def _can_connect_to_socket() -> bool:
    """Test if we can connect to the Unix domain socket."""
    if not SOCKET_PATH.exists():
        return False

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(str(SOCKET_PATH))
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        # Remove stale socket on connection failure
        SOCKET_PATH.unlink(missing_ok=True)
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Tool Support CLI")
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Command to execute"
    )
    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument(dest="request", type=str, nargs="?")
    subparsers.add_parser("server")
    subparsers.add_parser("healthcheck")
    subparsers.add_parser("model_proxy")

    return parser.parse_args()


if __name__ == "__main__":
    main()
