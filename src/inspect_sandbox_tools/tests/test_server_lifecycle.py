import asyncio
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil
import pytest
from aiohttp import ClientConnectionError
from aiohttp.web import Application
from inspect_sandbox_tools._cli import main as main_module
from inspect_sandbox_tools._cli import server as server_module
from inspect_sandbox_tools._remote_tools._bash_session import (
    json_rpc_methods as bash_session_methods,
)
from inspect_sandbox_tools._remote_tools._exec_remote import (
    json_rpc_methods as exec_remote_methods,
)
from inspect_sandbox_tools._remote_tools._mcp import json_rpc_methods as mcp_methods
from inspect_sandbox_tools._util.constants import server_socket_path

SERVER_DIR_ENV = "INSPECT_SANDBOX_TOOLS_DIR"


def _run_cli(
    command: str,
    *,
    server_dir: Path,
    cwd: Path,
    request: dict[str, Any] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "inspect_sandbox_tools._cli.main", command],
        input=json.dumps(request) if request is not None else None,
        text=True,
        capture_output=True,
        timeout=15,
        cwd=cwd,
        env={**os.environ, SERVER_DIR_ENV: str(server_dir)},
        check=False,
    )
    if check and result.returncode != 0:
        pytest.fail(f"CLI {command!r} failed with {result.returncode}: {result.stderr}")
    return result


def _rpc(request: dict[str, Any], *, server_dir: Path, cwd: Path) -> dict[str, Any]:
    result = _run_cli("exec", server_dir=server_dir, cwd=cwd, request=request)
    response = json.loads(result.stdout)
    assert "error" not in response, response
    return response


def _wait_for_file(path: Path, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for {path}")


def _wait_for_exit(label: str, pid: int, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return
        except psutil.NoSuchProcess:
            return
        time.sleep(0.05)
    state = subprocess.run(
        ["ps", "-o", "pid=,ppid=,pgid=,state=,command=", "-p", str(pid)],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    pytest.fail(f"{label} process {pid} remained alive after server shutdown: {state}")


def _force_kill(pid: int) -> None:
    for kill in (
        lambda: os.killpg(pid, signal.SIGKILL),
        lambda: os.kill(pid, signal.SIGKILL),
    ):
        try:
            kill()
        except (ProcessLookupError, PermissionError):
            pass


def _server_pid_for_cwd(cwd: Path) -> int:
    matches: list[int] = []
    for process in psutil.process_iter(["cmdline"]):
        try:
            cmdline = process.info["cmdline"] or []
            if (
                cmdline[-3:]
                == [
                    "-m",
                    "inspect_sandbox_tools._cli.main",
                    "server",
                ]
                and Path(process.cwd()).resolve() == cwd.resolve()
            ):
                matches.append(process.pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
    assert len(matches) == 1, matches
    return matches[0]


def test_server_socket_path_uses_private_directory_unless_it_is_too_long() -> None:
    short_server_dir = Path("/tmp/sample/sandbox-tools")
    server_dir = Path("/private/var/folders/" + "segment/" * 40 + "sandbox-tools")

    socket_path = server_socket_path(server_dir)

    assert (
        server_socket_path(short_server_dir) == short_server_dir / "sandbox-tools.sock"
    )
    assert socket_path == server_socket_path(server_dir)
    assert socket_path != server_socket_path(server_dir.with_name("other-tools"))
    assert socket_path.parent.parent == Path("/tmp")
    assert len(str(socket_path)) < 100


def test_prepare_socket_parent_uses_private_server_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = tmp_path / "sandbox-tools"
    monkeypatch.setattr(server_module, "SERVER_DIR", server_dir)
    monkeypatch.setattr(server_module, "SOCKET_PATH", server_dir / "sandbox-tools.sock")

    server_module._prepare_socket_parent()

    assert not server_dir.exists()


def test_prepare_socket_parent_creates_private_long_path_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = tmp_path / "sandbox-tools"
    fallback_dir = tmp_path / "fallback"
    monkeypatch.setattr(server_module, "SERVER_DIR", server_dir)
    monkeypatch.setattr(server_module, "SOCKET_PATH", fallback_dir / "server.sock")

    server_module._prepare_socket_parent()

    assert fallback_dir.is_dir()
    assert fallback_dir.stat().st_mode & 0o777 == 0o700


def test_prepare_socket_parent_tolerates_concurrent_fallback_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_dir = tmp_path / "sandbox-tools"
    fallback_dir = tmp_path / "fallback"
    monkeypatch.setattr(server_module, "SERVER_DIR", server_dir)
    monkeypatch.setattr(server_module, "SOCKET_PATH", fallback_dir / "server.sock")

    original_mkdir = Path.mkdir

    def concurrent_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        if path == fallback_dir:
            original_mkdir(path, *args, **kwargs)
            raise FileExistsError
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", concurrent_mkdir)

    server_module._prepare_socket_parent()

    assert fallback_dir.is_dir()
    assert fallback_dir.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("unsafe_parent", ("symlink", "file", "foreign_owner"))
def test_prepare_socket_parent_rejects_unsafe_long_path_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe_parent: str
) -> None:
    server_dir = tmp_path / "sandbox-tools"
    fallback_dir = tmp_path / "fallback"
    monkeypatch.setattr(server_module, "SERVER_DIR", server_dir)
    monkeypatch.setattr(server_module, "SOCKET_PATH", fallback_dir / "server.sock")

    if unsafe_parent == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        fallback_dir.symlink_to(target, target_is_directory=True)
    elif unsafe_parent == "file":
        fallback_dir.write_text("not a directory")
    else:
        fallback_dir.mkdir()
        current_uid = os.getuid()
        monkeypatch.setattr(server_module.os, "getuid", lambda: current_uid + 1)

    with pytest.raises(RuntimeError, match="Unsafe sandbox-tools socket directory"):
        server_module._prepare_socket_parent()


@pytest.mark.usefixtures("sandbox_server_cleanup")
def test_stop_server_without_running_server_is_idempotent() -> None:
    test_root = Path(tempfile.mkdtemp(prefix="ist-no-server-"))
    server_dir = test_root / "sandbox-tools"
    try:
        _run_cli("stop-server", server_dir=server_dir, cwd=test_root)
        _run_cli("stop-server", server_dir=server_dir, cwd=test_root)
        assert not server_socket_path(server_dir).exists()
        assert not (server_dir / "shutdown-status.json").exists()
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.mark.usefixtures("sandbox_server_cleanup")
def test_concurrent_server_start_uses_one_daemon() -> None:
    test_root = Path(tempfile.mkdtemp(prefix="ist-concurrent-start-"))
    server_dir = test_root / "sandbox-tools"
    processes: list[subprocess.Popen[str]] = []
    try:
        command = [
            sys.executable,
            "-m",
            "inspect_sandbox_tools._cli.main",
            "start-server",
        ]
        environment = {**os.environ, SERVER_DIR_ENV: str(server_dir)}
        processes = [
            subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=test_root,
                env=environment,
            )
            for _ in range(2)
        ]

        results = [process.communicate(timeout=20) for process in processes]
        assert [process.returncode for process in processes] == [0, 0], results
        assert _server_pid_for_cwd(test_root) > 0
    finally:
        _run_cli("stop-server", server_dir=server_dir, cwd=test_root, check=False)
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.mark.usefixtures("sandbox_server_cleanup")
def test_per_sample_server_shutdown_terminates_resources_and_preserves_next_cwd() -> (
    None
):
    test_root = Path(tempfile.mkdtemp(prefix="ist-lifecycle-"))
    first_cwd = test_root / "sample-one"
    second_cwd = test_root / "sample-two"
    first_cwd.mkdir()
    second_cwd.mkdir()
    first_server_dir = first_cwd / "sandbox-tools"
    second_server_dir = second_cwd / "sandbox-tools"
    owned_pids: list[tuple[str, int]] = []

    try:
        exec_pid_file = first_cwd / "exec-child.pid"
        exec_response = _rpc(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {
                    "command": (
                        f"sleep 300 & echo $! > {shlex.quote(str(exec_pid_file))}"
                    )
                },
                "id": 1,
            },
            server_dir=first_server_dir,
            cwd=first_cwd,
        )
        _wait_for_file(exec_pid_file)
        owned_pids.append(("exec_remote child", int(exec_pid_file.read_text())))
        exec_poll = _rpc(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": exec_response["result"]["pid"], "ack_seq": 0},
                "id": 2,
            },
            server_dir=first_server_dir,
            cwd=first_cwd,
        )
        deadline = time.monotonic() + 5
        while exec_poll["result"]["state"] == "running":
            assert time.monotonic() < deadline
            time.sleep(0.05)
            exec_poll = _rpc(
                {
                    "jsonrpc": "2.0",
                    "method": "exec_remote_poll",
                    "params": {
                        "pid": exec_response["result"]["pid"],
                        "ack_seq": exec_poll["result"]["seq"],
                    },
                    "id": 2,
                },
                server_dir=first_server_dir,
                cwd=first_cwd,
            )
        assert exec_poll["result"]["state"] == "completed"

        bash_response = _rpc(
            {
                "jsonrpc": "2.0",
                "method": "bash_session_new_session",
                "params": {},
                "id": 3,
            },
            server_dir=first_server_dir,
            cwd=first_cwd,
        )
        bash_output = _rpc(
            {
                "jsonrpc": "2.0",
                "method": "bash_session",
                "params": {
                    "session_name": bash_response["result"]["session_name"],
                    "input": (
                        "echo SANDBOX_BASH_PID=$$; "
                        "sleep 300 & echo SANDBOX_BASH_CHILD_PID=$!\n"
                    ),
                    "wait_for_output": 2,
                    "idle_timeout": 0.1,
                },
                "id": 4,
            },
            server_dir=first_server_dir,
            cwd=first_cwd,
        )["result"]
        match = re.search(r"SANDBOX_BASH_PID=(\d+)", bash_output)
        assert match is not None, bash_output
        owned_pids.append(("bash shell", int(match.group(1))))
        child_match = re.search(r"SANDBOX_BASH_CHILD_PID=(\d+)", bash_output)
        assert child_match is not None, bash_output
        owned_pids.append(("bash child", int(child_match.group(1))))
        _rpc(
            {
                "jsonrpc": "2.0",
                "method": "bash_session",
                "params": {
                    "session_name": bash_response["result"]["session_name"],
                    "restart": True,
                },
                "id": 5,
            },
            server_dir=first_server_dir,
            cwd=first_cwd,
        )

        mcp_pid_file = first_cwd / "mcp.pid"
        mcp_script = (
            "import os,subprocess; "
            "child=subprocess.Popen(['sleep', '300']); "
            f"open({str(mcp_pid_file)!r}, 'w').write("
            "str(os.getpid()) + ' ' + str(child.pid)); "
            "import time; time.sleep(300)"
        )
        _rpc(
            {
                "jsonrpc": "2.0",
                "method": "mcp_launch_server",
                "params": {
                    "server_params": {
                        "command": sys.executable,
                        "args": ["-c", mcp_script],
                    }
                },
                "id": 6,
            },
            server_dir=first_server_dir,
            cwd=first_cwd,
        )
        _wait_for_file(mcp_pid_file)
        mcp_pid, mcp_child_pid = (int(pid) for pid in mcp_pid_file.read_text().split())
        owned_pids.extend((("MCP server", mcp_pid), ("MCP child", mcp_child_pid)))
        assert os.getpgid(mcp_child_pid) == mcp_pid
        owned_pids.append(("sandbox-tools server", _server_pid_for_cwd(first_cwd)))

        assert server_socket_path(first_server_dir).exists()
        _run_cli("stop-server", server_dir=first_server_dir, cwd=first_cwd)

        for label, pid in owned_pids:
            _wait_for_exit(label, pid)
        assert not server_socket_path(first_server_dir).exists()
        assert json.loads((first_server_dir / "shutdown-status.json").read_text()) == {
            "errors": []
        }

        shutil.rmtree(first_cwd)

        second_response = _rpc(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {
                    "command": (
                        "printf '%s\\n%s\\n' \"$PWD\" "
                        '"${INSPECT_SANDBOX_TOOLS_DIR-unset}"'
                    )
                },
                "id": 5,
            },
            server_dir=second_server_dir,
            cwd=second_cwd,
        )
        second_pid = second_response["result"]["pid"]
        poll_response = _rpc(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": second_pid, "ack_seq": 0},
                "id": 6,
            },
            server_dir=second_server_dir,
            cwd=second_cwd,
        )
        stdout = poll_response["result"]["stdout"]
        stderr = poll_response["result"]["stderr"]
        deadline = time.monotonic() + 5
        while poll_response["result"]["state"] == "running":
            assert time.monotonic() < deadline
            time.sleep(0.05)
            poll_response = _rpc(
                {
                    "jsonrpc": "2.0",
                    "method": "exec_remote_poll",
                    "params": {
                        "pid": second_pid,
                        "ack_seq": poll_response["result"]["seq"],
                    },
                    "id": 7,
                },
                server_dir=second_server_dir,
                cwd=second_cwd,
            )
            stdout += poll_response["result"]["stdout"]
            stderr += poll_response["result"]["stderr"]

        assert stderr == ""
        output_lines = stdout.splitlines()
        assert Path(output_lines[0]) == second_cwd.resolve()
        assert output_lines[1] == "unset"
        assert server_socket_path(second_server_dir).exists()
        assert first_server_dir != second_server_dir
    finally:
        _run_cli(
            "stop-server", server_dir=second_server_dir, cwd=second_cwd, check=False
        )
        _run_cli(
            "stop-server", server_dir=first_server_dir, cwd=second_cwd, check=False
        )
        for _, pid in owned_pids:
            _force_kill(pid)
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.mark.usefixtures("sandbox_server_cleanup")
def test_stop_server_bounds_inflight_request_shutdown() -> None:
    test_root = Path(tempfile.mkdtemp(prefix="ist-inflight-"))
    server_dir = test_root / "sandbox-tools"
    mcp_pid_file = test_root / "mcp.pid"
    request_process: subprocess.Popen[str] | None = None
    mcp_pid: int | None = None

    try:
        launch_response = _rpc(
            {
                "jsonrpc": "2.0",
                "method": "mcp_launch_server",
                "params": {
                    "server_params": {
                        "command": sys.executable,
                        "args": [
                            "-c",
                            (
                                "import os,time; "
                                f"open({str(mcp_pid_file)!r}, 'w').write(str(os.getpid())); "
                                "time.sleep(300)"
                            ),
                        ],
                    }
                },
                "id": 1,
            },
            server_dir=server_dir,
            cwd=test_root,
        )
        _wait_for_file(mcp_pid_file)
        mcp_pid = int(mcp_pid_file.read_text())

        request_process = subprocess.Popen(
            [sys.executable, "-m", "inspect_sandbox_tools._cli.main", "exec"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=test_root,
            env={**os.environ, SERVER_DIR_ENV: str(server_dir)},
        )
        assert request_process.stdin is not None
        request_process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "mcp_send_request",
                    "params": {
                        "session_id": launch_response["result"],
                        "request": {
                            "jsonrpc": "2.0",
                            "id": 99,
                            "method": "tools/list",
                            "params": {},
                        },
                    },
                    "id": 2,
                }
            )
        )
        request_process.stdin.close()
        time.sleep(0.5)
        assert request_process.poll() is None

        started = time.monotonic()
        _run_cli("stop-server", server_dir=server_dir, cwd=test_root)
        assert time.monotonic() - started < 12

        _wait_for_exit("MCP server", mcp_pid)
        request_process.wait(timeout=5)
    finally:
        _run_cli("stop-server", server_dir=server_dir, cwd=test_root, check=False)
        if request_process is not None and request_process.poll() is None:
            request_process.kill()
            request_process.wait(timeout=5)
        if mcp_pid is not None:
            _force_kill(mcp_pid)
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.mark.asyncio
async def test_server_cleanup_runs_resource_groups_concurrently_and_records_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: set[str] = set()
    all_started = asyncio.Event()

    async def cleanup(name: str) -> None:
        started.add(name)
        if len(started) == 3:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        if name == "bash_session":
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(
        exec_remote_methods.controller, "shutdown", lambda: cleanup("exec_remote")
    )
    monkeypatch.setattr(
        bash_session_methods.controller, "shutdown", lambda: cleanup("bash_session")
    )
    monkeypatch.setattr(mcp_methods, "shutdown", lambda: cleanup("mcp"))

    server_module._shutdown_errors.clear()
    server_module._shutdown_complete = False
    try:
        await server_module._cleanup_remote_resources(Application())

        assert started == {"exec_remote", "bash_session", "mcp"}
        assert server_module._shutdown_errors == ["bash_session: cleanup failed"]
        assert server_module._shutdown_complete is True
    finally:
        server_module._shutdown_errors.clear()
        server_module._shutdown_complete = False


@pytest.mark.asyncio
async def test_stop_server_waits_for_starting_daemon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    socket_path = tmp_path / "sandbox-tools.sock"
    status_path = tmp_path / "shutdown-status.json"
    pid_path = tmp_path / "server.pid"
    socket_path.touch()
    checks = 0
    calls: list[tuple[str, str]] = []

    def can_connect() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    async def shutdown_call(socket: str, request: str) -> str:
        calls.append((socket, request))
        status_path.write_text('{"errors": []}')
        return '{"jsonrpc":"2.0","result":null,"id":668}'

    monkeypatch.setattr(main_module, "SOCKET_PATH", socket_path)
    monkeypatch.setattr(main_module, "SHUTDOWN_STATUS_PATH", status_path)
    monkeypatch.setattr(main_module, "SERVER_PID_PATH", pid_path)
    monkeypatch.setattr(main_module, "_can_connect_to_socket", can_connect)
    monkeypatch.setattr(main_module, "_server_process_is_running", lambda: True)
    monkeypatch.setattr(main_module, "json_rpc_unix_call", shutdown_call)

    await main_module._stop_server()

    assert checks >= 2
    assert calls == [
        (
            str(socket_path),
            '{"jsonrpc":"2.0","method":"sandbox_tools_shutdown","id":668}',
        )
    ]
    assert not socket_path.exists()


@pytest.mark.asyncio
async def test_stop_server_ignores_connection_loss_after_socket_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    socket_path = tmp_path / "sandbox-tools.sock"
    status_path = tmp_path / "shutdown-status.json"
    pid_path = tmp_path / "server.pid"
    socket_path.touch()
    pid_path.write_text('{"pid": 99, "created_at": 1.0}')

    async def shutdown_call(_socket: str, _request: str) -> str:
        raise ClientConnectionError("server stopped")

    monkeypatch.setattr(main_module, "SOCKET_PATH", socket_path)
    monkeypatch.setattr(main_module, "SHUTDOWN_STATUS_PATH", status_path)
    monkeypatch.setattr(main_module, "SERVER_PID_PATH", pid_path)
    monkeypatch.setattr(main_module, "_can_connect_to_socket", lambda: True)
    monkeypatch.setattr(main_module, "_server_process_is_running", lambda: False)
    monkeypatch.setattr(main_module, "json_rpc_unix_call", shutdown_call)

    await main_module._stop_server()

    assert not socket_path.exists()
    assert not pid_path.exists()


@pytest.mark.asyncio
async def test_exec_hides_server_directory_from_in_process_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(main_module.SERVER_DIR_ENV, "/private/server-dir")
    monkeypatch.setattr(main_module, "load_tools", lambda _module: {"in_process"})

    async def dispatch(_request: str) -> str:
        assert main_module.SERVER_DIR_ENV not in os.environ
        return '{"jsonrpc":"2.0","result":null,"id":1}'

    monkeypatch.setattr(main_module, "_dispatch_local_method", dispatch)

    await main_module._exec('{"jsonrpc":"2.0","method":"in_process","id":1}')
