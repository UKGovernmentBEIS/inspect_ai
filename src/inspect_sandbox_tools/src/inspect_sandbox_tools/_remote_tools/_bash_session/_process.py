import asyncio
import os
import re
from asyncio.subprocess import Process as AsyncIOProcess

from ..._util.pseudo_terminal import PseudoTerminal, PseudoTerminalIO
from ..._util.timeout_event import TimeoutEvent
from ..._util.user_switch import get_home_dir, make_preexec
from .tool_types import InteractResult

# Keep each JSON-RPC response below the host exec-output cap.
_DEFAULT_MAX_BASH_SESSION_RESPONSE_BYTES = 10 * 1024**2
_JSON_RPC_RESPONSE_HEADROOM_BYTES = 64 * 1024
_TRUNCATION_NOTICE_BUDGET = 512


class Process:
    @classmethod
    async def create(cls, user: str | None = None) -> "Process":
        pty = await PseudoTerminal.create()

        env = {**os.environ, "TERM": "dumb"}
        if user is not None:
            env["HOME"] = get_home_dir(user)

        return cls(
            await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-i",
                stdin=pty.subprocess_fd,
                stdout=pty.subprocess_fd,
                stderr=pty.subprocess_fd,
                env=env,
                start_new_session=True,
                preexec_fn=make_preexec(user),
            ),
            pty,
        )

    def __init__(self, process: AsyncIOProcess, pty: PseudoTerminalIO) -> None:
        self._process = process
        self._pty = pty
        self._terminated = False
        self._output_data = bytearray()
        self._dropped_output_bytes = 0
        self._output_limit = _bash_session_output_limit(None)
        self._read_task = asyncio.create_task(self._read_loop())
        self._send_data_event = TimeoutEvent()
        self._idle_timeout = 0.0

    async def interact(
        self,
        input_text: str | None,
        wait_for_output: int,
        idle_timeout: float,
        max_output_bytes: int | None,
    ) -> InteractResult:
        self._assert_not_terminated()
        self._send_data_event.clear()

        self._output_limit = _bash_session_output_limit(max_output_bytes)
        self._trim_output_data()

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

        output = strip_control_characters(self._format_output())
        self._output_data.clear()
        self._dropped_output_bytes = 0

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
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        # Clean up the timeout handler
        self._send_data_event.cancel()

        # Ensure the process is terminated
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            self._process.kill()
            await self._process.wait()
        except ProcessLookupError:
            # the process has already ended
            pass

        self._pty.cleanup()

    async def _read_loop(self) -> None:
        """Read decoded data from the PTY and process it."""
        try:
            while not self._terminated:
                decoded_str = await self._pty.read(4096)
                if not decoded_str:  # EOF
                    break

                self._receive_data(decoded_str)
        except (asyncio.CancelledError, BrokenPipeError, ConnectionResetError):
            # These are expected during termination
            pass

    def _receive_data(self, new_data: str) -> None:
        self._output_data.extend(new_data.encode("utf-8", errors="replace"))
        self._trim_output_data()

        if len(self._output_data) >= 4096:
            self._send_data_event.set()
        else:
            self._send_data_event.start_timer(self._idle_timeout)

    def _trim_output_data(self) -> None:
        if len(self._output_data) <= self._output_limit:
            return

        tail_limit = max(0, self._output_limit - _TRUNCATION_NOTICE_BUDGET)
        dropped_bytes = len(self._output_data) - tail_limit
        del self._output_data[:dropped_bytes]
        self._dropped_output_bytes += dropped_bytes

    def _format_output(self) -> str:
        output = self._output_data.decode("utf-8", errors="replace")
        if not self._dropped_output_bytes:
            return output

        notice = (
            "\n[inspect_sandbox_tools: bash_session output exceeded "
            f"{_human_readable_size(self._output_limit)}; showing the tail; "
            f"{self._dropped_output_bytes} bytes omitted]\n"
        )
        return f"{notice}{output}"

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


def _bash_session_output_limit(max_output_bytes: int | None) -> int:
    if max_output_bytes is None or max_output_bytes <= 0:
        max_output_bytes = _DEFAULT_MAX_BASH_SESSION_RESPONSE_BYTES

    headroom = min(max_output_bytes // 20, _JSON_RPC_RESPONSE_HEADROOM_BYTES)
    return max(1, max_output_bytes - headroom)


def _human_readable_size(size_bytes: int) -> str:
    if size_bytes >= 1024**3 and size_bytes % 1024**3 == 0:
        return f"{size_bytes // 1024**3} GiB"
    if size_bytes >= 1024**2 and size_bytes % 1024**2 == 0:
        return f"{size_bytes // 1024**2} MiB"
    if size_bytes >= 1024 and size_bytes % 1024 == 0:
        return f"{size_bytes // 1024} KiB"
    return f"{size_bytes} bytes"
