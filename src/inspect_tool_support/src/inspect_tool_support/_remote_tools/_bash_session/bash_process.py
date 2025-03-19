import asyncio
import uuid
from asyncio.subprocess import Process

from inspect_tool_support._remote_tools._bash_session._safe_stream_reader import (
    SafeStreamReader,
)
from inspect_tool_support._remote_tools._bash_session.tool_types import (
    BashCommandResult,
)


class BashProcess:
    @classmethod
    async def create(cls) -> "BashProcess":
        return cls(
            await asyncio.create_subprocess_exec(
                "/bin/bash",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        )

    def __init__(self, process: Process) -> None:
        self._process = process
        assert (
            process.stdin and process.stdout and process.stderr
        ), "process must have 'stdin', 'stdout', and 'stderr'"
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._stderr = process.stderr
        self._stdout_data: bytearray = bytearray()
        self._stdout_reader = SafeStreamReader(self._stdout, self._on_stdout_data)
        self._stderr_data: bytearray = bytearray()
        self._stderr_reader = SafeStreamReader(self._stderr, self._on_stderr_data)
        self._current_marker: str | None = None
        self._command_completed_event: asyncio.Event | None = None
        self._execute_in_progress = False

    async def execute_command(
        self, command: str, timeout: int = 30
    ) -> BashCommandResult:
        assert not self._execute_in_progress, "must not nest executes"
        self._execute_in_progress = True

        try:
            return await (
                self._send_input(command, timeout)
                if self._command_completed_event
                else self._execute_command(command, timeout)
            )

        finally:
            self._execute_in_progress = False

    async def _execute_command(self, command: str, timeout: int) -> BashCommandResult:
        assert not self._command_completed_event, "must not have a command in progress"

        # Set up to detect command completion
        self._current_marker = f"CMD_COMPLETE_{uuid.uuid4().hex}"
        self._command_completed_event = asyncio.Event()

        # For each command, we have bash to 3 things
        # - execute the caller's command
        # - do an `echo` that captures the command's exit status
        # - echo a marker that will allow us to robustly detect when the command is done
        wrapped_command = f"""
        {command}
        echo $? > /tmp/exit_status
        echo "{self._current_marker}"
        """

        self._stdin.write(wrapped_command.encode("utf-8") + b"\n")
        await self._stdin.drain()

        return await self._return_command_result(timeout)

    async def terminate(self, timeout: int = 30) -> None:
        self._stdin.write(b"exit\n")
        try:
            await asyncio.wait_for(self._stdin.drain(), timeout=timeout)
        except (
            BrokenPipeError,
            ConnectionResetError,
            TimeoutError,
            asyncio.TimeoutError,
        ):
            pass

        # Cancel the reading tasks
        await self._stdout_reader.stop()
        await self._stderr_reader.stop()

        # Ensure the process is terminated
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            self._process.kill()
            await self._process.wait()

    def _on_stdout_data(self, data: bytes) -> None:
        self._stdout_data.extend(data)
        if (
            self._command_completed_event
            and self._current_marker
            and (self._current_marker.encode("utf-8") in self._stdout_data)
        ):
            self._command_completed_event.set()

    def _on_stderr_data(self, data: bytes) -> None:
        self._stderr_data.extend(data)

    async def _send_input(self, command: str, timeout: int) -> BashCommandResult:
        assert self._command_completed_event, "must have a command in progress"
        self._stdin.write(command.encode("utf-8"))
        await self._stdin.drain()

        return await self._return_command_result(timeout)

    async def _return_command_result(self, timeout: int) -> BashCommandResult:
        assert self._command_completed_event, "must have a command in progress"

        try:
            # Wait for the command to complete or timeout
            await asyncio.wait_for(self._command_completed_event.wait(), timeout)
            command_completed = True
        except (asyncio.TimeoutError, TimeoutError):
            command_completed = False

        # Process the available output regardless of whether the command completed
        stdout_str = self._stdout_data.decode("utf-8")
        stderr_str = self._stderr_data.decode("utf-8")

        if not command_completed:
            return BashCommandResult(
                status=None,
                stdout=stdout_str,
                stderr=stderr_str,
            )

        command_output = stdout_str

        # Get exit status
        self._stdin.write(b"cat /tmp/exit_status\n")
        await self._stdin.drain()

        # Wait a short time for exit status to be available
        await asyncio.sleep(0.1)

        # TODO: Revise this to avoid splitting and later rejoining the output
        std_out_lines = stdout_str.splitlines()
        # stdout_lines now looks like
        # [
        #   <command output line 1>,
        #   <command output line ...>,
        #   <command output line n>,
        #   CMD_COMPLETE_eecf22460a39491c9dc7de05db31c53a,
        #   <command exit value e.g. 0>
        # ]

        # Find and remove the marker line
        marker_index = stdout_str.find(self._current_marker)
        if marker_index != -1:
            # Extract all content before the marker
            command_output = stdout_str[:marker_index]

            # Find exit status - it should be after the marker
            status_start = (
                marker_index + len(self._current_marker) + 1
            )  # +1 for newline
            status_end = stdout_str.find("\n", status_start)
            if status_end == -1:
                status_end = len(stdout_str)

            status_line = stdout_str[status_start:status_end].strip()

            if status_line.isnumeric():
                status = int(status_line)

        # Create the result with what we have
        result = BashCommandResult(
            status=status,
            stdout=command_output,
            stderr=stderr_str,
        )

        # Clean up
        self._stdout_data.clear()
        self._stderr_data.clear()

        if command_completed:
            self._command_completed_event = None
            self._current_marker = None

        return result
