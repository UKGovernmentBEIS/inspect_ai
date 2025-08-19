import json
import os
import subprocess
import time
from typing import Any, Dict

import pytest

from inspect_tool_support._util.constants import SOCKET_PATH


def cleanup_socket():
    """Remove any existing socket file."""
    SOCKET_PATH.unlink(missing_ok=True)


def cleanup_server_processes():
    """Kill any running server processes."""
    try:
        subprocess.run(
            ["pkill", "-f", "inspect-tool-support.*server"],
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


def exec_rpc_request(request: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    """Execute an RPC request via the CLI and return the parsed response."""
    request_json = json.dumps(request)

    result = subprocess.run(
        ["python", "-m", "src.inspect_tool_support._cli.main", "exec"],
        input=request_json,
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=os.getcwd(),
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
        ["python", "-m", "src.inspect_tool_support._cli.main", "exec"],
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
        ["python", "-m", "src.inspect_tool_support._cli.main", "exec"],
        input=json.dumps(malformed_request),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    # Should fail with validation error
    assert result.returncode != 0
