"""End-to-end checks of the ``exec`` CLI entry point against a real server."""

import json
import subprocess
import time
from typing import Any

import pytest
from inspect_sandbox_tools._util.constants import SOCKET_PATH

from tests.conftest import RpcClient

pytestmark = pytest.mark.usefixtures("sandbox_server_cleanup")


def _run_exec(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", "-m", "inspect_sandbox_tools._cli.main", "exec"],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_version_method(rpc_client: RpcClient) -> None:
    """The version method is answered in-process."""
    response = rpc_client({"jsonrpc": "2.0", "method": "version", "id": 1}, 10)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert "error" not in response
    version = response["result"]
    assert isinstance(version, str)
    assert len(version.split(".")) == 3


def test_socket_creation_and_permissions(rpc_client: RpcClient) -> None:
    """The first remote call starts the server with state private to its user."""
    rpc_client({"jsonrpc": "2.0", "method": "version", "id": 1}, 10)
    assert not SOCKET_PATH.exists(), "Socket should not exist after in-process call"

    response: dict[str, Any] = rpc_client(
        {"jsonrpc": "2.0", "method": "bash_session_new_session", "id": 666}, 10
    )
    assert response["result"]["session_name"] == "BashSession"

    for _ in range(50):
        if SOCKET_PATH.exists():
            break
        time.sleep(0.1)
    else:
        pytest.fail("Socket was not created within 5 seconds")

    # Only the CLI wrapper, running as the server's user, may connect.
    socket_mode = SOCKET_PATH.stat().st_mode & 0o777
    assert socket_mode & 0o077 == 0, (
        f"Socket is reachable by other users: {socket_mode:o}"
    )
    directory_mode = SOCKET_PATH.parent.stat().st_mode & 0o777
    assert directory_mode == 0o700, (
        f"Server directory should be 0700, got {directory_mode:o}"
    )


def test_invalid_json_request() -> None:
    result = _run_exec("invalid json")

    assert result.returncode != 0
    assert "error" in result.stderr.lower()


def test_malformed_jsonrpc_request() -> None:
    result = _run_exec(json.dumps({"method": "version"}))

    assert result.returncode != 0
