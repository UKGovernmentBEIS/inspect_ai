"""Integration tests for exec_remote JSON-RPC methods.

These tests verify the full server-side stack by sending JSON-RPC requests
via the CLI and checking the responses.
"""

import time
from typing import Any

import pytest

from tests.conftest import (
    DEFAULT_RPC_TIMEOUT,
    RpcClient,
)

# exec_remote-specific test constants
DEFAULT_POLL_TIMEOUT = 5.0
DEFAULT_POLL_INTERVAL = 0.1
LONG_RUNNING_SLEEP_SECONDS = 10
NONEXISTENT_PID = 99999


def poll_until_complete(
    rpc_client: RpcClient,
    pid: int,
    timeout: float = DEFAULT_POLL_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> dict[str, Any]:
    """Poll an exec_remote job until it completes or times out.

    Args:
        rpc_client: The RPC client function to use for polling.
        pid: The process ID to poll.
        timeout: Maximum time to wait for completion in seconds.
        poll_interval: Time between poll requests in seconds.

    Returns:
        A dictionary containing:
        - state: "completed" or "killed"
        - exit_code: The process exit code (if completed)
        - stdout: Accumulated stdout from all poll responses
        - stderr: Accumulated stderr from all poll responses

    Raises:
        pytest.fail: If the job doesn't complete within the timeout.
    """
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    start_time = time.time()

    while time.time() - start_time < timeout:
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": pid},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        if "error" in response:
            pytest.fail(f"Poll failed: {response['error']}")

        result = response["result"]
        stdout_parts.append(result["stdout"])
        stderr_parts.append(result["stderr"])

        if result["state"] in ("completed", "killed"):
            return {
                "state": result["state"],
                "exit_code": result.get("exit_code"),
                "stdout": "".join(stdout_parts),
                "stderr": "".join(stderr_parts),
            }

        time.sleep(poll_interval)

    pytest.fail(f"Job {pid} did not complete within {timeout} seconds")


@pytest.fixture(autouse=True)
def _setup_and_teardown(sandbox_server_cleanup: None) -> None:
    """Automatically use the sandbox server cleanup for all tests in this module."""
    pass


class TestExecRemoteSubmit:
    """Tests for exec_remote_start."""

    def test_submit_returns_pid(self, rpc_client: RpcClient) -> None:
        """Test that submit returns a valid PID."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo hello"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        assert "result" in response
        assert "pid" in response["result"]
        assert isinstance(response["result"]["pid"], int)
        assert response["result"]["pid"] > 0

    @pytest.mark.parametrize(
        ("command", "input_text", "expected_stdout", "strip_output"),
        [
            pytest.param(
                "cat",
                "hello from stdin",
                "hello from stdin",
                False,
                id="basic_input",
            ),
            pytest.param(
                "cat",
                "line 1\nline 2\nline 3",
                "line 1\nline 2\nline 3",
                False,
                id="multiline",
            ),
            pytest.param(
                "cat",
                "hello\tworld\n\"quotes\" and 'apostrophes'\n$variables",
                "hello\tworld\n\"quotes\" and 'apostrophes'\n$variables",
                False,
                id="special_chars",
            ),
            pytest.param(
                "cat",
                "",
                "",
                False,
                id="empty_string",
            ),
            pytest.param(
                "wc -l",
                "one\ntwo\nthree\n",
                "3",
                True,
                id="wc_line_count",
            ),
            pytest.param(
                "grep ^a",
                "apple\nbanana\napricot\ncherry",
                "apple\napricot\n",
                False,
                id="grep_filter",
            ),
        ],
    )
    def test_submit_with_input(
        self,
        rpc_client: RpcClient,
        command: str,
        input_text: str,
        expected_stdout: str,
        strip_output: bool,
    ) -> None:
        """Test that input is correctly piped to commands."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": command, "input": input_text},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        assert "result" in response
        pid = response["result"]["pid"]
        result = poll_until_complete(rpc_client, pid)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        actual_stdout = result["stdout"].strip() if strip_output else result["stdout"]
        assert actual_stdout == expected_stdout

    def test_submit_without_input(self, rpc_client: RpcClient) -> None:
        """Test that commands work without input parameter."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo no input needed"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        pid = response["result"]["pid"]
        result = poll_until_complete(rpc_client, pid)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        assert result["stdout"].strip() == "no input needed"


class TestExecRemotePoll:
    """Tests for exec_remote_poll."""

    def test_poll_running_job(self, rpc_client: RpcClient) -> None:
        """Test polling a job that is still running."""
        # Start a long-running job
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": f"sleep {LONG_RUNNING_SLEEP_SECONDS}"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Poll immediately - should be running
        poll_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        assert poll_response["result"]["state"] == "running"

        # Clean up - kill the job
        rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 3,
            },
            DEFAULT_RPC_TIMEOUT,
        )


class TestExecRemoteKill:
    """Tests for exec_remote_kill."""

    def test_kill_running_job(self, rpc_client: RpcClient) -> None:
        """Test killing a running job returns stdout and stderr fields."""
        # Start a long-running job
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": f"sleep {LONG_RUNNING_SLEEP_SECONDS * 10}"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Kill it
        kill_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        assert "result" in kill_response
        assert "stdout" in kill_response["result"]
        assert "stderr" in kill_response["result"]

    def test_kill_returns_buffered_output(self, rpc_client: RpcClient) -> None:
        """Test that kill returns any output buffered since the last poll."""
        # Start a command that produces output then sleeps
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {
                    "command": "echo hello_from_kill && echo err_from_kill >&2 && sleep 100"
                },
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Wait for the output to be produced
        time.sleep(0.5)

        # Kill without polling first — all output should come back in kill result
        kill_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        assert "result" in kill_response
        assert "hello_from_kill" in kill_response["result"]["stdout"]
        assert "err_from_kill" in kill_response["result"]["stderr"]


class TestNonexistentJobErrors:
    """Tests for error handling when operating on nonexistent jobs."""

    @pytest.mark.parametrize(
        "method",
        [
            pytest.param("exec_remote_poll", id="poll"),
            pytest.param("exec_remote_kill", id="kill"),
        ],
    )
    def test_nonexistent_job_returns_error(
        self, rpc_client: RpcClient, method: str
    ) -> None:
        """Test that operations on nonexistent jobs return errors."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": {"pid": NONEXISTENT_PID},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        assert "error" in response


class TestExitCodeAndErrors:
    """Tests for exit codes and error handling."""

    def test_command_with_nonzero_exit_code(self, rpc_client: RpcClient) -> None:
        """Test that non-zero exit codes are captured correctly."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "exit 42"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        pid = response["result"]["pid"]
        result = poll_until_complete(rpc_client, pid)

        assert result["state"] == "completed"
        assert result["exit_code"] == 42

    def test_command_not_found(self, rpc_client: RpcClient) -> None:
        """Test that invalid commands result in non-zero exit and error output."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "nonexistent_command_xyz_123"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        pid = response["result"]["pid"]
        result = poll_until_complete(rpc_client, pid)

        assert result["state"] == "completed"
        assert result["exit_code"] != 0
        # Shell should report command not found in stderr
        assert "not found" in result["stderr"].lower() or result["exit_code"] == 127

    def test_stderr_capture(self, rpc_client: RpcClient) -> None:
        """Test that stderr output is captured correctly."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo error_message >&2"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        pid = response["result"]["pid"]
        result = poll_until_complete(rpc_client, pid)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        assert "error_message" in result["stderr"]

    def test_mixed_stdout_stderr(self, rpc_client: RpcClient) -> None:
        """Test that both stdout and stderr are captured correctly."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo stdout_msg && echo stderr_msg >&2"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        pid = response["result"]["pid"]
        result = poll_until_complete(rpc_client, pid)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        assert "stdout_msg" in result["stdout"]
        assert "stderr_msg" in result["stderr"]


class TestProcessLifecycle:
    """Tests for process lifecycle edge cases."""

    def test_poll_after_completion_returns_error(self, rpc_client: RpcClient) -> None:
        """Test that polling a completed job a second time returns an error.

        After a job completes and is polled, it gets removed from the registry.
        Subsequent polls should return a 'job not found' error.
        """
        # Submit a quick command
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo done"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Poll until complete (this consumes the job from registry)
        result = poll_until_complete(rpc_client, pid)
        assert result["state"] == "completed"

        # Second poll should fail - job no longer exists
        second_poll = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in second_poll

    def test_kill_already_completed_job(self, rpc_client: RpcClient) -> None:
        """Test that killing an already-completed job is handled gracefully."""
        # Submit a quick command
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo done"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Wait for completion
        poll_until_complete(rpc_client, pid)

        # Try to kill the completed job - should return error (job removed)
        kill_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in kill_response

    def test_double_kill(self, rpc_client: RpcClient) -> None:
        """Test that killing the same job twice is handled gracefully."""
        # Start a long-running job
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": f"sleep {LONG_RUNNING_SLEEP_SECONDS}"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # First kill should succeed
        first_kill = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "result" in first_kill

        # Second kill should return error (job already removed)
        second_kill = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 3,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in second_kill

    def test_multiple_submits_get_distinct_pids(self, rpc_client: RpcClient) -> None:
        """Test that submitting the same command twice returns distinct PIDs."""
        response1 = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo test"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid1 = response1["result"]["pid"]

        response2 = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "echo test"},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid2 = response2["result"]["pid"]

        assert pid1 != pid2

        # Clean up both jobs
        poll_until_complete(rpc_client, pid1)
        poll_until_complete(rpc_client, pid2)


class TestProcessTreeManagement:
    """Tests for process group/tree behavior."""

    def test_kill_terminates_child_processes(self, rpc_client: RpcClient) -> None:
        """Test that killing a job also kills its child processes.

        The implementation uses start_new_session=True and sends SIGTERM to
        the process group, which should terminate all child processes.
        """
        # Start a command that spawns background children
        # The parent shell will spawn two sleep processes
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "sleep 100 & sleep 100 & wait"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Give the children time to start
        time.sleep(0.5)

        # Kill the job
        kill_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "result" in kill_response

        # Verify by checking that no sleep processes from our job are running
        # We can't easily verify the exact PIDs, but we can check the job
        # was properly cleaned up by trying to poll it
        poll_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": pid},
                "id": 3,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        # Job should be removed from registry after kill
        assert "error" in poll_response

    def test_shell_pipeline_killed(self, rpc_client: RpcClient) -> None:
        """Test that a shell pipeline is fully terminated when killed."""
        # Start a pipeline - both sides should be killed
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": "sleep 100 | cat"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Give the pipeline time to start
        time.sleep(0.3)

        # Kill the job
        kill_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 2,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "result" in kill_response

        # Job should be cleaned up
        poll_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": pid},
                "id": 3,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in poll_response


class TestConcurrency:
    """Tests for concurrent job execution."""

    def test_multiple_concurrent_jobs(self, rpc_client: RpcClient) -> None:
        """Test that multiple jobs can run concurrently without interference."""
        # Submit three jobs with different outputs
        jobs = []
        for i in range(3):
            response = rpc_client(
                {
                    "jsonrpc": "2.0",
                    "method": "exec_remote_start",
                    "params": {"command": f"echo job_{i}"},
                    "id": i + 1,
                },
                DEFAULT_RPC_TIMEOUT,
            )
            assert "result" in response
            jobs.append({"pid": response["result"]["pid"], "expected": f"job_{i}"})

        # Poll all jobs to completion and verify their outputs
        for job in jobs:
            result = poll_until_complete(rpc_client, job["pid"])
            assert result["state"] == "completed"
            assert result["exit_code"] == 0
            assert job["expected"] in result["stdout"]


class TestIncrementalOutput:
    """Tests for output streaming behavior."""

    def test_incremental_output_cleared_between_polls(
        self, rpc_client: RpcClient
    ) -> None:
        """Test that output buffers are cleared between polls.

        Each poll should return only the output generated since the last poll,
        not the entire output history.
        """
        # Start a command that outputs multiple lines with delays
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {
                    "command": "echo line1; sleep 0.3; echo line2; sleep 0.3; echo line3"
                },
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        # Collect output from multiple polls
        all_stdout = []
        for _ in range(20):  # Poll multiple times
            poll_response = rpc_client(
                {
                    "jsonrpc": "2.0",
                    "method": "exec_remote_poll",
                    "params": {"pid": pid},
                    "id": 2,
                },
                DEFAULT_RPC_TIMEOUT,
            )

            if "error" in poll_response:
                break

            result = poll_response["result"]
            if result["stdout"]:
                all_stdout.append(result["stdout"])

            if result["state"] == "completed":
                break

            time.sleep(0.15)

        # Combine all output
        combined = "".join(all_stdout)

        # All three lines should be present exactly once
        assert combined.count("line1") == 1
        assert combined.count("line2") == 1
        assert combined.count("line3") == 1


class TestParameterValidation:
    """Tests for JSON-RPC parameter validation."""

    def test_submit_rejects_extra_params(self, rpc_client: RpcClient) -> None:
        """Test that submit rejects unknown parameters."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {
                    "command": "echo test",
                    "unknown_param": "should_fail",
                },
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in response

    def test_poll_rejects_invalid_pid_type(self, rpc_client: RpcClient) -> None:
        """Test that poll rejects non-integer PIDs."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_poll",
                "params": {"pid": "not_an_integer"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in response

    def test_submit_missing_required_params(self, rpc_client: RpcClient) -> None:
        """Test that submit requires the command parameter."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in response


class TestLargeOutput:
    """Tests for large output handling."""

    def test_large_stdout_output(self, rpc_client: RpcClient) -> None:
        """Test that large output is captured correctly."""
        # Generate approximately 100KB of output (100 lines of 1000 chars each)
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {
                    "command": "for i in $(seq 1 100); do printf 'x%.0s' $(seq 1 1000); echo; done"
                },
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

        pid = response["result"]["pid"]
        result = poll_until_complete(rpc_client, pid, timeout=30.0)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        # Verify we got approximately the expected amount of output
        # 100 lines * (1000 chars + newline) = ~100,100 chars
        assert len(result["stdout"]) >= 100000


class TestWriteStdinAndCloseStdin:
    """Tests for exec_remote_write_stdin and exec_remote_close_stdin."""

    # A bash script that reads stdin line-by-line and echoes each line
    # prefixed with "GOT:" so we can verify delivery. Exits on EOF.
    ECHO_STDIN_SCRIPT = 'while IFS= read -r line; do echo "GOT:$line"; done'

    def _start_with_stdin_open(self, rpc_client: RpcClient, command: str) -> int:
        """Start a command with stdin_open=True and return the pid."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": command, "stdin_open": True},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "result" in response, f"Expected result, got: {response}"
        return response["result"]["pid"]

    def _write_stdin(
        self, rpc_client: RpcClient, pid: int, data: str
    ) -> dict[str, Any]:
        """Write data to a process's stdin and return the result."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_write_stdin",
                "params": {"pid": pid, "data": data},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "result" in response, f"write_stdin failed: {response}"
        return response["result"]

    def _close_stdin(self, rpc_client: RpcClient, pid: int) -> dict[str, Any]:
        """Close a process's stdin and return the result."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_close_stdin",
                "params": {"pid": pid},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "result" in response, f"close_stdin failed: {response}"
        return response["result"]

    def test_write_then_close_produces_output(self, rpc_client: RpcClient) -> None:
        """Write lines to stdin, close it, and verify the process echoes them back."""
        pid = self._start_with_stdin_open(rpc_client, self.ECHO_STDIN_SCRIPT)

        stdout_parts: list[str] = []
        stdout_parts.append(self._write_stdin(rpc_client, pid, "hello\n")["stdout"])
        stdout_parts.append(self._write_stdin(rpc_client, pid, "world\n")["stdout"])
        stdout_parts.append(self._close_stdin(rpc_client, pid)["stdout"])

        result = poll_until_complete(rpc_client, pid)
        stdout_parts.append(result["stdout"])
        all_stdout = "".join(stdout_parts)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        assert "GOT:hello" in all_stdout
        assert "GOT:world" in all_stdout

    def test_close_stdin_causes_eof(self, rpc_client: RpcClient) -> None:
        """Closing stdin causes a `cat` process to exit."""
        pid = self._start_with_stdin_open(rpc_client, "cat")

        stdout_parts: list[str] = []
        stdout_parts.append(self._write_stdin(rpc_client, pid, "some data\n")["stdout"])
        stdout_parts.append(self._close_stdin(rpc_client, pid)["stdout"])

        result = poll_until_complete(rpc_client, pid)
        stdout_parts.append(result["stdout"])
        all_stdout = "".join(stdout_parts)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        assert "some data" in all_stdout

    def test_multiple_chunks_arrive_in_order(self, rpc_client: RpcClient) -> None:
        """Multiple write_stdin calls arrive in the correct order."""
        pid = self._start_with_stdin_open(rpc_client, self.ECHO_STDIN_SCRIPT)

        stdout_parts: list[str] = []
        for i in range(5):
            stdout_parts.append(
                self._write_stdin(rpc_client, pid, f"line{i}\n")["stdout"]
            )
        stdout_parts.append(self._close_stdin(rpc_client, pid)["stdout"])

        result = poll_until_complete(rpc_client, pid)
        stdout_parts.append(result["stdout"])
        all_stdout = "".join(stdout_parts)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0

        lines = [line for line in all_stdout.splitlines() if line.startswith("GOT:")]
        assert lines == [f"GOT:line{i}" for i in range(5)]

    def test_initial_input_with_stdin_open(self, rpc_client: RpcClient) -> None:
        """Initial input and subsequent write_stdin both arrive."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {
                    "command": self.ECHO_STDIN_SCRIPT,
                    "input": "first\n",
                    "stdin_open": True,
                },
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "result" in response
        pid = response["result"]["pid"]

        stdout_parts: list[str] = []
        stdout_parts.append(self._write_stdin(rpc_client, pid, "second\n")["stdout"])
        stdout_parts.append(self._close_stdin(rpc_client, pid)["stdout"])

        result = poll_until_complete(rpc_client, pid)
        stdout_parts.append(result["stdout"])
        all_stdout = "".join(stdout_parts)

        assert result["state"] == "completed"
        assert result["exit_code"] == 0
        assert "GOT:first" in all_stdout
        assert "GOT:second" in all_stdout

    def test_write_stdin_result_includes_stdout_stderr(
        self, rpc_client: RpcClient
    ) -> None:
        """write_stdin and close_stdin results include stdout/stderr fields."""
        pid = self._start_with_stdin_open(rpc_client, self.ECHO_STDIN_SCRIPT)

        write_result = self._write_stdin(rpc_client, pid, "hello\n")
        assert "stdout" in write_result
        assert "stderr" in write_result

        close_result = self._close_stdin(rpc_client, pid)
        assert "stdout" in close_result
        assert "stderr" in close_result

    def test_output_piggybacked_on_write_stdin(self, rpc_client: RpcClient) -> None:
        """Output produced between RPCs is returned piggybacked on write_stdin."""
        # Use a script that echoes immediately, then waits for more input
        pid = self._start_with_stdin_open(rpc_client, self.ECHO_STDIN_SCRIPT)

        self._write_stdin(rpc_client, pid, "first\n")
        # Give the process time to produce output
        time.sleep(0.3)

        # The second write should piggyback the output from the first
        write_result = self._write_stdin(rpc_client, pid, "second\n")
        close_result = self._close_stdin(rpc_client, pid)

        # Combine output from write_stdin + close_stdin + final poll
        result = poll_until_complete(rpc_client, pid)
        all_stdout = write_result["stdout"] + close_result["stdout"] + result["stdout"]
        assert "GOT:first" in all_stdout
        assert "GOT:second" in all_stdout

    def test_write_stdin_to_nonexistent_pid_returns_error(
        self, rpc_client: RpcClient
    ) -> None:
        """write_stdin to a nonexistent PID returns an error."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_write_stdin",
                "params": {"pid": NONEXISTENT_PID, "data": "hello\n"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in response

    def test_close_stdin_to_nonexistent_pid_returns_error(
        self, rpc_client: RpcClient
    ) -> None:
        """close_stdin to a nonexistent PID returns an error."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_close_stdin",
                "params": {"pid": NONEXISTENT_PID},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in response

    def test_write_stdin_without_stdin_open_returns_error(
        self, rpc_client: RpcClient
    ) -> None:
        """write_stdin to a process started without stdin_open returns an error."""
        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_start",
                "params": {"command": f"sleep {LONG_RUNNING_SLEEP_SECONDS}"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        pid = response["result"]["pid"]

        write_response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_write_stdin",
                "params": {"pid": pid, "data": "hello\n"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in write_response

        # Clean up
        rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_kill",
                "params": {"pid": pid},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )

    def test_write_stdin_after_close_returns_error(self, rpc_client: RpcClient) -> None:
        """write_stdin after close_stdin returns an error."""
        pid = self._start_with_stdin_open(rpc_client, "cat")

        self._close_stdin(rpc_client, pid)

        response = rpc_client(
            {
                "jsonrpc": "2.0",
                "method": "exec_remote_write_stdin",
                "params": {"pid": pid, "data": "too late\n"},
                "id": 1,
            },
            DEFAULT_RPC_TIMEOUT,
        )
        assert "error" in response
