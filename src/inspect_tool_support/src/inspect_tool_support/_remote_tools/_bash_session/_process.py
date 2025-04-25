import asyncio
import os
import re
from asyncio.subprocess import Process as AsyncIOProcess

from ..._util.pseudo_terminal import PseudoTerminal, PseudoTerminalIO
from ..._util.safe_stream_reader import SafeStreamReader
from ..._util.timeout_event import TimeoutEvent
from .tool_types import InteractResult


class Process:
    @classmethod
    async def create(cls) -> "Process":
        pty = await PseudoTerminal.create()

        return cls(
            await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-i",
                stdin=pty.subprocess_fd,
                stdout=pty.subprocess_fd,
                stderr=pty.subprocess_fd,
                env={**os.environ, "TERM": "dumb"},
                start_new_session=True,
            ),
            pty,
        )

    def __init__(self, process: AsyncIOProcess, pty: PseudoTerminalIO) -> None:
        self._process = process
        self._pty = pty
        self._terminated = False
        self._output_data = bytearray()
        self._output_reader = SafeStreamReader(pty.reader, self._receive_data)
        self._send_data_event = TimeoutEvent()
        self._idle_timeout = 0.0

    async def interact(
        self, input_text: str | None, wait_for_output: int, idle_timeout: float
    ) -> InteractResult:
        self._assert_not_terminated()
        # assert not self._send_data_event.is_set(), "send data event must be cleared"

        self._idle_timeout = idle_timeout
        if input_text:
            self._pty.writer.write(input_text.encode("utf-8"))
            await self._pty.writer.drain()

        # If there's already available data, just wait for the idle timeout.
        # Otherwise, wait the longer amount of time for output to be available.
        self._send_data_event.start_timer(
            idle_timeout if len(self._output_data) else wait_for_output
        )
        await self._send_data_event.wait()

        output = self._output_data.decode("utf-8")
        # This isn't 100% correct. Just like the stream chunks could split a
        # utf-8 character, it could also split these control sequences. The
        # downside is just that a control sequence could be left in the output.
        output = strip_control_characters(output)
        self._output_data.clear()

        return output

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

        # Cancel the reading task
        await self._output_reader.stop()

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

    def _receive_data(self, new_data: bytes) -> None:
        self._output_data.extend(new_data)

        if len(self._output_data) >= 4096:
            self._send_data_event.set()
        else:
            self._send_data_event.start_timer(self._idle_timeout)

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"


# Pattern matches most ANSI escape sequences and control characters
ansi_escape_pattern = re.compile(
    r"""
    \x1B  # ESC character
    (?:   # followed by...
        [@-Z\\-_]| # single character controls
        \[[0-9;]*[A-Za-z]| # CSI sequences like colors
        \]8;.*;| # OSC hyperlink sequences
        \([AB012]| # Select character set
        \[[0-9]+(?:;[0-9]+)*m # SGR sequences (colors, etc)
    )
""",
    re.VERBOSE,
)


def strip_control_characters(text: str) -> str:
    """Remove ANSI escape sequences and other control characters from text."""
    # Remove the ANSI escape sequences
    clean_text = ansi_escape_pattern.sub("", text)

    # Additionally remove other control characters except newlines and tabs
    clean_text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", clean_text)

    return clean_text
