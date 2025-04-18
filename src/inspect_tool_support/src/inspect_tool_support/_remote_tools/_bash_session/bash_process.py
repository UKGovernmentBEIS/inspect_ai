import asyncio
import uuid
from asyncio.subprocess import Process

from ..._util._safe_stream_reader import SafeStreamReader
from .tool_types import BashCommandResult


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
        assert (
            process.stdout and process.stderr
        ), "process must have 'stdout' and 'stderr'"
        self._process = process
        self._terminated = False
        self._stdout_data = bytearray()
        self._stderr_data = bytearray()
        self._stdout_reader = SafeStreamReader(process.stdout, self._on_stdout_data)
        self._stderr_reader = SafeStreamReader(process.stderr, self._on_stderr_data)
        self._current_marker_bytes: bytes | None = None
        self._command_completed = asyncio.Event()

    async def execute_command(
        self, command: str, timeout: int = 30
    ) -> BashCommandResult:
        self._assert_not_terminated()
        assert self._process.stdin, "process must have 'stdin'"

        # Clear previous output
        self._stdout_data.clear()
        self._stderr_data.clear()

        # Set up to detect command completion
        marker = f"CMD_COMPLETE_{uuid.uuid4().hex}"
        self._current_marker_bytes = marker.encode("utf-8")
        self._command_completed.clear()

        # For each command, we have bash to 2 things
        # - execute the caller's command
        # - do an `echo` of a marker that will allow us to robustly detect when
        #   the command is done followed by the command's exit status
        wrapped_command = f"""
        {command}
        echo "{marker}$?"
        """

        self._process.stdin.write(wrapped_command.encode("utf-8") + b"\n")
        await self._process.stdin.drain()

        # TODO: How do we want to handle timeouts raised from this?
        await asyncio.wait_for(self._command_completed.wait(), timeout)

        # stdout_data now looks like:
        # <command output>CMD_COMPLETE_eecf22460a39491c9dc7de05db31c53a<exit status>\n

        parts = self._stdout_data.decode("utf-8").split(marker)

        assert len(parts) == 2, "marker not found in command output"
        command_output = parts[0]
        exit_status = parts[1].strip()
        assert exit_status.isnumeric(), "exit status not found in command output"

        return BashCommandResult(
            status=int(exit_status),
            stdout=command_output,
            stderr=self._stderr_data.decode("utf-8"),
        )

    async def terminate(self, timeout: int = 30) -> None:
        self._assert_not_terminated()
        self._terminated = True
        assert self._process.stdin
        self._process.stdin.write(b"exit\n")
        try:
            await asyncio.wait_for(self._process.stdin.drain(), timeout=timeout)
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
            self._current_marker_bytes
            and self._current_marker_bytes in self._stdout_data
        ):
            self._current_marker_bytes = None
            self._command_completed.set()

    def _on_stderr_data(self, data: bytes) -> None:
        self._stderr_data.extend(data)

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
