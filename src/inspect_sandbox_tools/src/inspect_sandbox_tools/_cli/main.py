import argparse
import asyncio
import json
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
from inspect_sandbox_tools._util.constants import SERVER_DIR, SOCKET_PATH
from inspect_sandbox_tools._util.json_rpc_helpers import json_rpc_unix_call
from inspect_sandbox_tools._util.load_tools import load_tools
from inspect_sandbox_tools._util.user_switch import get_home_dir, switch_user


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
        case "start-server":
            start_server()
        case "server":
            server_main()
        case "model_proxy":
            asyncio.run(run_model_proxy_server())


def start_server():
    """Start the background server process (called by the server manager)."""
    server_main()


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

    # For in-process tools, extract _run_as_user and setuid before dispatching.
    # The CLI is short-lived (one invocation per request), so in-process setuid is safe.
    if tool_name in in_process_tools:
        request_data = json.loads(request_json_str)
        run_as_user = None
        if isinstance(request_data.get("params"), dict):
            run_as_user = request_data["params"].pop("_run_as_user", None)
        if run_as_user is not None:
            if not isinstance(run_as_user, str):
                raise TypeError(
                    f"_run_as_user must be a string, got {type(run_as_user).__name__}"
                )
            request_json_str = json.dumps(request_data)
            switch_user(run_as_user)
            os.environ["HOME"] = get_home_dir(run_as_user)

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


_SERVER_STDOUT_LOG = SERVER_DIR / "server-stdout.log"
_SERVER_STDERR_LOG = SERVER_DIR / "server-stderr.log"


def _ensure_server_is_running() -> None:
    if _can_connect_to_socket():
        return  # Server already running and responsive

    # Clean up any stale socket from a previously crashed server before
    # starting a new one. The server's own startup also does this, but doing
    # it here avoids a window where a concurrent caller could connect to a
    # half-started socket and falsely conclude the server is ready.
    SOCKET_PATH.unlink(missing_ok=True)

    SERVER_DIR.mkdir(exist_ok=True)
    stdout_log = open(_SERVER_STDOUT_LOG, "a")
    stderr_log = open(_SERVER_STDERR_LOG, "a")

    process = subprocess.Popen(
        (
            # Production staticx mode
            [executable_path, "start-server"]
            # Get the correct executable path for staticx bundled executables. When
            # running under staticx, sys.argv[0] points to the extracted temp executable
            # which gets deleted when the parent process exits, breaking the server.
            # The STATICX_PROG_PATH env var provides the absolute path of the program
            # being executed.
            if (executable_path := os.environ.get("STATICX_PROG_PATH"))
            # Dev/test mode: use Python interpreter with module invocation
            else [
                sys.executable,
                "-m",
                "inspect_sandbox_tools._cli.main",
                "start-server",
            ]
        ),
        stdout=stdout_log,
        stderr=stderr_log,
    )
    stdout_log.close()
    stderr_log.close()

    # Wait for socket to become available
    for _ in range(6000):  # Wait up to 600 seconds
        if _can_connect_to_socket():
            return
        # Detect early crash — no point waiting 20s if the process already exited
        if process.poll() is not None:
            raise RuntimeError(
                f"Server process exited immediately (exit code {process.returncode}). "
                f"Logs:\n{_read_server_logs()}"
            )
        time.sleep(0.1)

    process.kill()
    raise RuntimeError(
        f"Server ({process.pid}) failed to start within 120 seconds. "
        f"Logs:\n{_read_server_logs()}"
    )


def _read_server_logs() -> str:
    """Read the last 2000 chars of server stdout and stderr logs."""
    parts = []
    for label, path in [("stdout", _SERVER_STDOUT_LOG), ("stderr", _SERVER_STDERR_LOG)]:
        try:
            content = open(path).read()[-2000:]
            if content.strip():
                parts.append(f"  [{label}] {content}")
        except FileNotFoundError:
            pass
    return "\n".join(parts) if parts else "  (no log output)"


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
    except (OSError, ConnectionRefusedError, PermissionError):
        # Do NOT delete the socket here. The socket file may belong to a server
        # we just started that has bound its socket but hasn't called listen()
        # yet. Deleting it at this point would permanently break that server:
        # it would begin accepting on an FD with no filesystem path, so clients
        # would never find it. Stale socket cleanup is handled explicitly by
        # _ensure_server_is_running() before it spawns a new server.
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Tool Support CLI")
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Command to execute"
    )
    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument(dest="request", type=str, nargs="?")
    subparsers.add_parser("start-server")
    subparsers.add_parser("server")
    subparsers.add_parser("healthcheck")
    subparsers.add_parser("model_proxy")

    return parser.parse_args()


if __name__ == "__main__":
    main()
