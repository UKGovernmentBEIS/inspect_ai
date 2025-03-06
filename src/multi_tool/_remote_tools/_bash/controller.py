import asyncio
import threading
import uuid
from asyncio import Task
from asyncio.subprocess import Process

from multi_tool._remote_tools._bash.tool_types import (
    BashCommandResult,
    BashRestartResult,
)


class Controller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.__process: Process | None = None
        self._stdout_data: list[str] = []
        self._stdout_task: Task[None] | None = None
        self._stderr_data: list[str] = []
        self._stderr_task: Task[None] | None = None
        self._current_marker: str | None = None
        self._command_completed: asyncio.Event | None = None

    @property
    async def _process(self) -> Process:
        with self._lock:
            if self.__process is None:
                self.__process = await asyncio.create_subprocess_exec(
                    "/bin/bash",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # Start tasks to read stdout and stderr
                self._stdout_task = asyncio.create_task(self._read_stream(True))
                self._stderr_task = asyncio.create_task(self._read_stream(False))
        return self.__process

    async def _read_stream(self, stdout: bool) -> None:
        assert self.__process, "must have process"
        stream, data = (
            (self.__process.stdout, self._stdout_data)
            if stdout
            else (self.__process.stderr, self._stderr_data)
        )
        assert stream, "must find stream"
        while True:
            line = await stream.readline()
            if not line:  # EOF
                break

            line_str = line.decode("utf-8")
            data.append(line_str)

            # Check if line contains our marker indicating command completion
            if stdout and self._current_marker and self._current_marker in line_str:
                assert self._command_completed, (
                    "must have an event to set if we find a marker"
                )
                self._command_completed.set()

    async def execute_command(
        self, command: str, timeout: int = 30
    ) -> BashCommandResult:
        process = await self._process
        assert process.stdin, "process must have 'stdin'"

        # Clear previous output
        self._stdout_data.clear()
        self._stderr_data.clear()

        # Set up to detect command completion
        self._current_marker = f"CMD_COMPLETE_{uuid.uuid4().hex}"
        self._command_completed = asyncio.Event()

        # For each command, we have bash to 3 things
        # - execute the caller's command
        # - do an `echo` that captures the command's exit status
        # - echo a marker that will allow us to robustly detect when the command is done
        wrapped_command = f"""
        {command}
        echo $? > /tmp/exit_status
        echo "{self._current_marker}"
        """

        process.stdin.write(wrapped_command.encode("utf-8") + b"\n")
        await process.stdin.drain()

        # TODO: How do we want to handle timeouts raised from this?
        await asyncio.wait_for(self._command_completed.wait(), timeout)

        # Get exit status
        process.stdin.write(b"cat /tmp/exit_status\n")
        await process.stdin.drain()

        # Wait a short time for exit status to be available
        await asyncio.sleep(0.1)

        # stdout_data now looks like
        # [
        #   <command output line 1>,
        #   <command output line ...>,
        #   <command output line n>,
        #   CMD_COMPLETE_eecf22460a39491c9dc7de05db31c53a,
        #   <command exit value e.g. 0>
        # ]

        # Pop the last value in stdout_data into status_line
        status_line = self._stdout_data.pop().strip()
        assert status_line.isnumeric()
        status = int(status_line)

        # Pop the second to last value in stdout_data into marker_line
        marker_line = self._stdout_data.pop().strip()
        # double check it's what we think it is
        assert marker_line == self._current_marker

        stdout_result = "".join(self._stdout_data)
        stderr_result = "".join(self._stderr_data)

        return BashCommandResult(
            status=status, stdout=stdout_result, stderr=stderr_result
        )

    async def restart(self, timeout: int = 30) -> BashRestartResult:
        raise NotImplementedError

    async def _close(self) -> None:
        process = await self._process
        self.__process = None
        assert process.stdin
        process.stdin.write(b"exit\n")
        try:
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass

        # Cancel the reading tasks
        assert self._stdout_task
        assert self._stderr_task
        self._stdout_task.cancel()
        self._stderr_task.cancel()

        # Ensure the process is terminated
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=1)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
