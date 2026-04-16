import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from inspect_sandbox_tools._util.constants import SOCKET_PATH, SOCKET_PATH_ENV


def cleanup_socket():
    """Remove any existing socket file."""
    SOCKET_PATH.unlink(missing_ok=True)


def cleanup_server_processes():
    """Kill any running server processes."""
    try:
        subprocess.run(
            ["pkill", "-f", "inspect-sandbox-tools.*server"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Set up and tear down for each test."""
    cleanup_socket()
    cleanup_server_processes()
    yield
    cleanup_socket()
    cleanup_server_processes()


_REPO_ROOT = str(Path(__file__).resolve().parents[4])
"""Root of the inspect_sandbox_tools source tree, used as PYTHONPATH
so that the CLI subprocess can find the package from any CWD."""


def exec_rpc_request(
    request: Dict[str, Any],
    timeout: int = 10,
    cwd: str | None = None,
    env: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Execute an RPC request via the CLI and return the parsed response."""
    request_json = json.dumps(request)

    run_env = {**os.environ, "PYTHONPATH": _REPO_ROOT, **(env or {})}
    result = subprocess.run(
        ["python", "-m", "inspect_sandbox_tools._cli.main", "exec"],
        input=request_json,
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=cwd or os.getcwd(),
        env=run_env,
        check=False,
    )

    if result.returncode != 0:
        pytest.fail(f"CLI command failed: {result.stderr}")

    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as e:
        pytest.fail(f"Invalid JSON response: {result.stdout}\nError: {e}")


def test_version_method():
    """Test the version method (in-process tool)."""
    request = {"jsonrpc": "2.0", "method": "version", "id": 1}

    response = exec_rpc_request(request)

    # Verify JSON-RPC response structure
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert "result" in response
    assert "error" not in response

    # Verify version format (should be a string like "1.1.0")
    version = response["result"]
    assert isinstance(version, str)
    assert len(version.split(".")) == 3  # Major.minor.patch format


def test_socket_creation_and_permissions():
    """Test that socket is created with correct permissions after first remote call."""
    # First, make a version call (in-process, won't create socket)
    version_request = {"jsonrpc": "2.0", "method": "version", "id": 1}
    exec_rpc_request(version_request)
    assert not SOCKET_PATH.exists(), "Socket should not exist after in-process call"

    # Now try a remote method that would trigger server startup
    # This should create the socket
    response = exec_rpc_request(
        {
            "jsonrpc": "2.0",
            "method": "bash_session_new_session",
            "id": 666,
        }
    )

    assert response["result"]["session_name"] == "BashSession"

    for _ in range(50):
        if SOCKET_PATH.exists():
            break
        time.sleep(0.1)
    else:
        pytest.fail("Socket was not created within 5 seconds")

    # Check socket permissions
    stat_info = SOCKET_PATH.stat()
    permissions = oct(stat_info.st_mode)[-3:]
    assert permissions == "666", f"Socket permissions should be 666, got {permissions}"


def test_invalid_json_request():
    """Test handling of invalid JSON requests."""
    result = subprocess.run(
        ["python", "-m", "src.inspect_sandbox_tools._cli.main", "exec"],
        input="invalid json",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    # Should fail gracefully
    assert result.returncode != 0
    assert "error" in result.stderr.lower()


def test_malformed_jsonrpc_request():
    """Test handling of malformed JSON-RPC requests."""
    malformed_request = {"method": "version"}  # Missing required jsonrpc and id fields

    result = subprocess.run(
        ["python", "-m", "src.inspect_sandbox_tools._cli.main", "exec"],
        input=json.dumps(malformed_request),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    # Should fail with validation error
    assert result.returncode != 0


def test_global_server_stale_cwd():
    """Demonstrate the bug: a global server outlives its CWD.

    When the server is started from a temporary directory that is later
    deleted, child processes inherit the stale CWD and fail with
    "getcwd() failed". This is the failure mode for sandbox="local"
    where sample_cleanup deletes the TemporaryDirectory but the server
    keeps running.
    """
    # 1. Start the server from a temp dir (simulates first eval run)
    first_sandbox = tempfile.mkdtemp()
    exec_rpc_request(
        {
            "jsonrpc": "2.0",
            "method": "exec_remote_start",
            "params": {"command": "true"},
            "id": 1,
        },
        cwd=first_sandbox,
    )

    # 2. Delete the temp dir (simulates sample_cleanup)

    shutil.rmtree(first_sandbox)

    # 3. Start a new process from a different dir (simulates second eval run).
    #    The server is still alive with a dangling CWD, so child processes
    #    inherit it and get "getcwd() failed".
    second_sandbox = tempfile.mkdtemp()
    try:
        response = exec_rpc_request(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo hello"},
                "id": 2,
            },
            cwd=second_sandbox,
        )
        pid = response["result"]["pid"]

        time.sleep(0.5)

        poll_response = exec_rpc_request(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": pid, "ack_seq": 0},
                "id": 3,
            },
            cwd=second_sandbox,
        )
        stderr = poll_response["result"]["stderr"]
        assert "getcwd() failed" in stderr, (
            f"Expected stale-CWD error from global server, got stderr: {stderr!r}"
        )
    finally:
        shutil.rmtree(second_sandbox, ignore_errors=True)


def test_per_sandbox_socket_avoids_stale_cwd():
    """Fix: scoping the socket per-sandbox avoids the stale CWD bug.

    When each sandbox sets INSPECT_SANDBOX_TOOLS_SOCKET to a path inside
    its own temp dir, a fresh server is started per sandbox. Deleting the
    first sandbox's temp dir doesn't affect the second sandbox's server.
    """
    # 1. First "sandbox" — start server scoped to its temp dir
    first_sandbox = tempfile.mkdtemp()
    first_socket = str(Path(first_sandbox) / "sandbox-tools.sock")
    exec_rpc_request(
        {
            "jsonrpc": "2.0",
            "method": "exec_remote_start",
            "params": {"command": "true"},
            "id": 1,
        },
        cwd=first_sandbox,
        env={SOCKET_PATH_ENV: first_socket},
    )

    # 2. Tear down first sandbox (simulates sample_cleanup)
    shutil.rmtree(first_sandbox)

    # 3. Second "sandbox" — gets its own server with a valid CWD
    second_sandbox = tempfile.mkdtemp()
    second_socket = str(Path(second_sandbox) / "sandbox-tools.sock")
    try:
        response = exec_rpc_request(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo hello"},
                "id": 2,
            },
            cwd=second_sandbox,
            env={SOCKET_PATH_ENV: second_socket},
        )
        pid = response["result"]["pid"]

        time.sleep(0.5)

        poll_response = exec_rpc_request(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": pid, "ack_seq": 0},
                "id": 3,
            },
            cwd=second_sandbox,
            env={SOCKET_PATH_ENV: second_socket},
        )
        result = poll_response["result"]
        assert result["stderr"] == "", (
            f"Expected no errors with per-sandbox socket, got: {result['stderr']!r}"
        )
        assert "hello" in result["stdout"]
    finally:
        shutil.rmtree(second_sandbox, ignore_errors=True)
