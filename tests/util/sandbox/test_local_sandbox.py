from pathlib import Path

import pytest

from inspect_ai.util._sandbox.local import LocalSandboxEnvironment


@pytest.mark.anyio
async def test_local_sandbox_sets_per_instance_server_dir():
    """Local sandbox scopes INSPECT_SANDBOX_TOOLS_DIR to its temp directory.

    Otherwise the sandbox-tools server outlives its CWD and breaks subsequent runs.
    """
    sandbox = LocalSandboxEnvironment()
    try:
        result = await sandbox.exec(["sh", "-c", "echo $INSPECT_SANDBOX_TOOLS_DIR"])
        server_dir = result.stdout.strip()
        assert server_dir == str(Path(sandbox.directory.name) / "sandbox-tools"), (
            f"Expected per-sandbox server dir, got: {server_dir!r}"
        )
    finally:
        sandbox.directory.cleanup()


@pytest.mark.anyio
async def test_local_sandbox_server_dir_unique_per_instance():
    """Each sandbox instance gets a distinct server dir."""
    sandbox_a = LocalSandboxEnvironment()
    sandbox_b = LocalSandboxEnvironment()
    try:
        result_a = await sandbox_a.exec(["sh", "-c", "echo $INSPECT_SANDBOX_TOOLS_DIR"])
        result_b = await sandbox_b.exec(["sh", "-c", "echo $INSPECT_SANDBOX_TOOLS_DIR"])
        assert result_a.stdout.strip() != result_b.stdout.strip()
    finally:
        sandbox_a.directory.cleanup()
        sandbox_b.directory.cleanup()


@pytest.mark.anyio
async def test_local_sandbox_exec_merges_caller_env():
    """Caller-provided env vars are passed through alongside the server dir env."""
    sandbox = LocalSandboxEnvironment()
    try:
        result = await sandbox.exec(
            ["sh", "-c", "echo $MY_VAR:$INSPECT_SANDBOX_TOOLS_DIR"],
            env={"MY_VAR": "hello"},
        )
        my_var, server_dir = result.stdout.strip().split(":", 1)
        assert my_var == "hello"
        assert server_dir == str(Path(sandbox.directory.name) / "sandbox-tools")
    finally:
        sandbox.directory.cleanup()


@pytest.mark.anyio
async def test_local_sandbox_caller_cant_override_server_dir():
    """Callers can't silently disable per-sandbox scoping by passing the env var."""
    sandbox = LocalSandboxEnvironment()
    try:
        result = await sandbox.exec(
            ["sh", "-c", "echo $INSPECT_SANDBOX_TOOLS_DIR"],
            env={"INSPECT_SANDBOX_TOOLS_DIR": "/tmp/attacker-controlled"},
        )
        server_dir = result.stdout.strip()
        assert server_dir == str(Path(sandbox.directory.name) / "sandbox-tools"), (
            f"Sandbox should override caller's env var, got: {server_dir!r}"
        )
    finally:
        sandbox.directory.cleanup()
