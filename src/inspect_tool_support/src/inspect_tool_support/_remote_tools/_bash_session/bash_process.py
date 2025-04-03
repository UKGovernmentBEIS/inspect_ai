import asyncio
import uuid
from asyncio.subprocess import Process

from inspect_tool_support._remote_tools._bash_session._pseudo_terminal import (
    PseudoTerminal,
    PseudoTerminalStdIn,
)
from inspect_tool_support._remote_tools._bash_session._safe_stream_reader import (
    SafeStreamReader,
)
from inspect_tool_support._remote_tools._bash_session.tool_types import (
    BashCommandResult,
)


class BashProcess:
    @classmethod
    async def create(cls) -> "BashProcess":
        stdin = await PseudoTerminal.create()

        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            # Hand the terminal side of the PTY to the bash process as its stdin
            stdin=stdin.terminal_fd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Create our process object with the PTY for stdin
        return cls(process, stdin)

    def __init__(self, process: Process, stdin: PseudoTerminalStdIn) -> None:
        self._process = process
        self._pyt_stdin = stdin
        assert (
            process.stdout and process.stderr
        ), "process must have 'stdout' and 'stderr'"

        self._stdout_data = bytearray()
        self._stdout_reader = SafeStreamReader(process.stdout, self._on_stdout_data)
        self._stderr_data = bytearray()
        self._stderr_reader = SafeStreamReader(process.stderr, self._on_stderr_data)
        self._current_marker: str | None = None
        self._command_completed_event: asyncio.Event | None = None
        self._execute_in_progress = False

    async def execute_command(
        self, command: str, timeout: int = 5
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
        echo "{self._current_marker}$?"
        """

        self._pyt_stdin.writer.write(wrapped_command.encode("utf-8") + b"\n")
        await self._pyt_stdin.writer.drain()

        return await self._return_command_result(timeout)

    async def terminate(self, timeout: int = 30) -> None:
        self._pyt_stdin.writer.write(b"exit\n")
        try:
            await asyncio.wait_for(self._pyt_stdin.writer.drain(), timeout=timeout)
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

        self._pyt_stdin.cleanup()

    def _on_stdout_data(self, data: bytes) -> None:
        assert (
            self._command_completed_event and self._current_marker
        ), "must have a command in progress"

        self._stdout_data.extend(data)
        if self._current_marker.encode("utf-8") in self._stdout_data:
            self._command_completed_event.set()

    def _on_stderr_data(self, data: bytes) -> None:
        self._stderr_data.extend(data)

    async def _send_input(self, command: str, timeout: int) -> BashCommandResult:
        assert self._command_completed_event, "must have a command in progress"
        self._pyt_stdin.writer.write(command.encode("utf-8"))
        await self._pyt_stdin.writer.drain()

        return await self._return_command_result(timeout)

    async def _return_command_result(self, timeout: int) -> BashCommandResult:
        assert self._command_completed_event, "must have a command in progress"

        try:
            # Wait for the command to complete or timeout
            await asyncio.wait_for(self._command_completed_event.wait(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            out_str, err_str = self._get_stream_strings()
            print(f"XXXXXX not completed\n\t{out_str=}\n\t{err_str=}")

            return BashCommandResult(
                status=None,
                stdout=out_str,
                stderr=err_str,
            )

        # Get exit status
        self._pyt_stdin.writer.write(b"cat /tmp/exit_status\n")
        await self._pyt_stdin.writer.drain()

        # Wait a short time for exit status to be available
        await asyncio.sleep(0.1)

        out_str, err_str = self._get_stream_strings()
        # out_str now looks like:
        # <command output>CMD_COMPLETE_eecf22460a39491c9dc7de05db31c53a<exit status>

        parts = out_str.split(self._current_marker)

        print(f"XXXXXX command completed\n\t{out_str=}\n\t{parts=}")

        assert len(parts) == 2, "marker not found in command output"
        command_output = parts[0]
        exit_status = parts[1].strip()
        assert exit_status.isnumeric(), "exit status not found in command output"

        self._command_completed_event = None
        self._current_marker = None

        # Create the result with what we have
        return BashCommandResult(
            status=int(exit_status),
            stdout=command_output,
            stderr=err_str,
        )

    def _get_stream_strings(self) -> tuple[str, str]:
        result = self._stdout_data.decode("utf-8"), self._stderr_data.decode("utf-8")
        self._stdout_data.clear()
        self._stderr_data.clear()
        return result
