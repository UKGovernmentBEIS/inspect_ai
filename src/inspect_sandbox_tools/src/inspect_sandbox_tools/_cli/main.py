import argparse
import asyncio
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from typing import Literal

import aiohttp
import psutil
from jsonrpcserver import async_dispatch
from pydantic import BaseModel

from inspect_sandbox_tools._agent_bridge.proxy import run_model_proxy_server
from inspect_sandbox_tools._cli.server import main as server_main
from inspect_sandbox_tools._util.common_types import JSONRPCResponseJSON
from inspect_sandbox_tools._util.constants import (
    SERVER_DIR,
    SERVER_DIR_ENV,
    SERVER_PID_PATH,
    SHUTDOWN_STATUS_PATH,
    SOCKET_PATH,
)
from inspect_sandbox_tools._util.json_rpc_chunking import (
    JSON_RPC_RESPONSE_CHUNK_METHOD,
    chunk_json_rpc_response_if_needed,
    handle_json_rpc_response_chunk_request,
)
from inspect_sandbox_tools._util.json_rpc_helpers import json_rpc_unix_call
from inspect_sandbox_tools._util.load_tools import load_tools
from inspect_sandbox_tools._util.user_switch import get_home_dir, switch_user

# Resource shutdown has a 30s graceful budget plus a 5s post-SIGKILL wait.
# This 45s CLI deadline also leaves time for HTTP shutdown; LocalSandbox's 55s
# outer limit covers this RPC call and its status wait.
_SHUTDOWN_STATUS_TIMEOUT = 45
_SERVER_STARTUP_TIMEOUT = 5
_SERVER_PROCESS_STOP_TIMEOUT = 5


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
        case "stop-server":
            stop_server()
        case "server":
            server_main()
        case "model_proxy":
            asyncio.run(run_model_proxy_server())


def start_server() -> None:
    """Start the sandbox tools server and validate it is responsive."""
    _ensure_server_is_running()
    healthcheck()


def stop_server() -> None:
    """Stop this server directory's sandbox-tools server if it is running."""
    asyncio.run(_stop_server())


async def _stop_server() -> None:
    if not _can_connect_to_socket():
        if not await _wait_for_starting_server():
            _clear_stale_server_state()
            return

    SHUTDOWN_STATUS_PATH.unlink(missing_ok=True)
    try:
        response = json.loads(
            await asyncio.wait_for(
                json_rpc_unix_call(
                    str(SOCKET_PATH),
                    '{"jsonrpc":"2.0","method":"sandbox_tools_shutdown","id":668}',
                ),
                timeout=5,
            )
        )
    except aiohttp.ClientConnectionError:
        # The daemon can stop after the probe succeeds but before it replies.
        # Wait for its shutdown status when it is still identifiable; otherwise
        # clean its stale transport files just as an idempotent stop would.
        await _wait_for_shutdown_status()
        return
    if "error" in response:
        raise RuntimeError(f"Server shutdown failed: {response['error']}")

    await _wait_for_shutdown_status()


async def _wait_for_shutdown_status() -> None:
    deadline = time.monotonic() + _SHUTDOWN_STATUS_TIMEOUT
    while time.monotonic() < deadline:
        if SHUTDOWN_STATUS_PATH.exists():
            status = json.loads(SHUTDOWN_STATUS_PATH.read_text())
            SOCKET_PATH.unlink(missing_ok=True)
            SERVER_PID_PATH.unlink(missing_ok=True)
            errors = status.get("errors", [])
            if errors:
                raise RuntimeError(
                    "Sandbox-tools server cleanup failed: " + "; ".join(errors)
                )
            return
        if not _server_process_is_running():
            _clear_stale_server_state()
            return
        await asyncio.sleep(0.05)

    raise RuntimeError(
        "Sandbox-tools server cleanup did not complete within "
        f"{_SHUTDOWN_STATUS_TIMEOUT} seconds"
    )


def healthcheck():
    asyncio.run(_exec('{"jsonrpc": "2.0", "method": "version", "id": 666}'))
    asyncio.run(_exec('{"jsonrpc": "2.0", "method": "remote_version", "id": 667}'))


# Example/testing requests
# {"jsonrpc": "2.0", "method": "editor", "id": 666, "params": {"command": "view", "path": "/tmp"}}
# {"jsonrpc": "2.0", "method": "bash", "id": 666, "params": {"command": "ls ~/Downloads"}}
async def _exec(request: str | None) -> None:
    in_process_tools = load_tools("inspect_sandbox_tools._in_process_tools")

    request_json_str = request or sys.stdin.read().strip()
    request_data = json.loads(request_json_str)
    tool_name = JSONRPCIncoming.model_validate(request_data).method
    assert isinstance(tool_name, str)

    if tool_name == JSON_RPC_RESPONSE_CHUNK_METHOD:
        print(handle_json_rpc_response_chunk_request(request_data))
        return

    # SERVER_DIR has already been resolved at import time. Do not let stateless
    # in-process tools leak this private location to their user subprocesses.
    os.environ.pop(SERVER_DIR_ENV, None)

    # For in-process tools, extract _run_as_user and setuid before dispatching.
    # The CLI is short-lived (one invocation per request), so in-process setuid is safe.
    if tool_name in in_process_tools:
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

    response = await (
        _dispatch_local_method
        if tool_name in in_process_tools
        else _dispatch_remote_method
    )(request_json_str)
    print(chunk_json_rpc_response_if_needed(request_data, response))


async def _dispatch_local_method(request_json_str: str) -> JSONRPCResponseJSON:
    return JSONRPCResponseJSON(await async_dispatch(request_json_str))


async def _dispatch_remote_method(request_json_str: str) -> JSONRPCResponseJSON:
    _ensure_server_is_running()
    return await json_rpc_unix_call(str(SOCKET_PATH), request_json_str)


_SERVER_STDOUT_LOG = SERVER_DIR / "server-stdout.log"
_SERVER_STDERR_LOG = SERVER_DIR / "server-stderr.log"
_SERVER_START_LOCK_PATH = SERVER_DIR / "server-start.lock"


def _ensure_server_is_running() -> None:
    """Start one server for this directory, waiting for a concurrent starter."""
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    with _SERVER_START_LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        _ensure_server_is_running_locked()


def _ensure_server_is_running_locked() -> None:
    if _can_connect_to_socket():
        return  # Server already running and responsive

    if SOCKET_PATH.exists() or SERVER_PID_PATH.exists():
        startup_deadline = time.monotonic() + _SERVER_STARTUP_TIMEOUT
        while time.monotonic() < startup_deadline:
            if _can_connect_to_socket():
                return
            if not _server_process_is_running():
                break
            time.sleep(0.05)
        _terminate_unresponsive_server()
        if _server_process_is_running():
            raise RuntimeError("Unresponsive sandbox-tools server did not exit")
        _clear_stale_server_state()

    SHUTDOWN_STATUS_PATH.unlink(missing_ok=True)

    SERVER_DIR.mkdir(exist_ok=True)
    stdout_log = open(_SERVER_STDOUT_LOG, "a")
    stderr_log = open(_SERVER_STDERR_LOG, "a")

    process = subprocess.Popen(
        (
            # Frozen onedir bundle: sys.executable is the stable launcher on disk
            # (no self-extraction / self-deleting temp), so re-invoke it directly.
            [sys.executable, "server"]
            if getattr(sys, "frozen", False)
            # Dev/test mode: use Python interpreter with module invocation
            else [sys.executable, "-m", "inspect_sandbox_tools._cli.main", "server"]
        ),
        stdout=stdout_log,
        stderr=stderr_log,
        env={**os.environ, SERVER_DIR_ENV: str(SERVER_DIR)},
    )
    server_process = psutil.Process(process.pid)
    SERVER_PID_PATH.write_text(
        json.dumps({"pid": process.pid, "created_at": server_process.create_time()})
        + "\n"
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
    SERVER_PID_PATH.unlink(missing_ok=True)
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
        return False


def _server_process_is_running() -> bool:
    metadata = _server_process_metadata()
    if metadata is None:
        return False
    try:
        return psutil.Process(metadata["pid"]).create_time() == metadata["created_at"]
    except psutil.NoSuchProcess:
        return False


async def _wait_for_starting_server() -> bool:
    if not _server_process_is_running():
        return False

    deadline = time.monotonic() + _SERVER_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if _can_connect_to_socket():
            return True
        if not _server_process_is_running():
            return False
        await asyncio.sleep(0.05)

    await asyncio.to_thread(_terminate_unresponsive_server)
    return False


def _terminate_unresponsive_server() -> None:
    """Stop an identified daemon before removing its socket or PID file."""
    metadata = _server_process_metadata()
    if metadata is None or not _server_process_is_running():
        return

    try:
        process = psutil.Process(metadata["pid"])
        process.terminate()
        process.wait(timeout=_SERVER_PROCESS_STOP_TIMEOUT)
    except psutil.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=_SERVER_PROCESS_STOP_TIMEOUT)
        except psutil.TimeoutExpired as ex:
            raise RuntimeError("Unresponsive sandbox-tools server did not exit") from ex
    except psutil.NoSuchProcess:
        pass


def _clear_stale_server_state() -> None:
    SOCKET_PATH.unlink(missing_ok=True)
    SERVER_PID_PATH.unlink(missing_ok=True)
    SHUTDOWN_STATUS_PATH.unlink(missing_ok=True)


def _server_process_metadata() -> dict[str, int | float] | None:
    try:
        metadata = json.loads(SERVER_PID_PATH.read_text())
        pid = metadata["pid"]
        created_at = metadata["created_at"]
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(pid, int) or not isinstance(created_at, int | float):
        return None
    return {"pid": pid, "created_at": created_at}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Tool Support CLI")
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Command to execute"
    )
    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument(dest="request", type=str, nargs="?")
    subparsers.add_parser("start-server")
    subparsers.add_parser("stop-server")
    subparsers.add_parser("server")
    subparsers.add_parser("healthcheck")
    subparsers.add_parser("model_proxy")

    return parser.parse_args()


if __name__ == "__main__":
    main()
