import asyncio
import functools
from asyncio.subprocess import Process

from ..._util.pseudo_terminal import PseudoTerminal, PseudoTerminalStdIn
from ..._util.safe_stream_reader import SafeStreamReader
from ..._util.timeout_event import TimeoutEvent
from .tool_types import InteractResult


class BashProcess:
    @classmethod
    async def create(cls) -> "BashProcess":
        pty = await PseudoTerminal.create()

        return cls(
            await asyncio.create_subprocess_exec(
                "/bin/bash",
                # Hand the terminal side of the PTY to the bash process as its stdin
                stdin=pty.terminal_fd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            pty,
        )

    def __init__(self, process: Process, pty: PseudoTerminalStdIn) -> None:
        assert (
            process.stdout and process.stderr
        ), "process must have 'stdout' and 'stderr'"
        self._process = process
        self._pty = pty
        self._terminated = False
        self._stdout_data = bytearray()
        self._stderr_data = bytearray()
        self._send_data_event = TimeoutEvent()
        self._stdout_reader = SafeStreamReader(
            process.stdout, functools.partial(self._receive_data, self._stdout_data)
        )
        self._stderr_reader = SafeStreamReader(
            process.stderr, functools.partial(self._receive_data, self._stderr_data)
        )

    async def interact(
        self, input_text: str | None, idle_timeout: int
    ) -> InteractResult:
        self._assert_not_terminated()

        # Clear previous output
        self._stdout_data.clear()
        self._stderr_data.clear()

        # Reset the timeout handler (this now implicitly starts the timer)
        self._send_data_event.clear(idle_timeout)

        if input_text:
            self._pty.writer.write(input_text.encode("utf-8"))
            await self._pty.writer.drain()

        # Wait for data collection to complete
        self._send_data_event.start_timer()
        await self._send_data_event.wait()

        stdout = self._stdout_data.decode("utf-8")
        stderr = self._stderr_data.decode("utf-8")
        self._stdout_data.clear()
        self._stderr_data.clear()

        return InteractResult(
            stdout=stdout,
            stderr=stderr,
        )

    async def terminate(self, timeout: int = 30) -> None:
        self._assert_not_terminated()
        self._terminated = True
        self._pty.writer.write(b"exit\n")
        try:
            await asyncio.wait_for(self._pty.writer.drain(), timeout=timeout)
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

        # Clean up the timeout handler
        self._send_data_event.cancel()

        # Ensure the process is terminated
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            self._process.kill()
            await self._process.wait()

        self._pty.cleanup()

    def _receive_data(self, data: bytearray, new_data: bytes) -> None:
        data.extend(new_data)

        # Check if we've reached the buffer size threshold
        if len(data) >= 4096:
            self._send_data_event.set()
        else:
            # Otherwise, reset the idle timer since we just got new data
            self._send_data_event.start_timer()

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
