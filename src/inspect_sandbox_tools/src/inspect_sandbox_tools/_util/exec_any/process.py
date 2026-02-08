import asyncio
import os
from asyncio.subprocess import Process as AsyncIOProcess

from ..pseudo_terminal import PseudoTerminal, PseudoTerminalIO
from ..timeout_event import TimeoutEvent


class Process:
    @classmethod
    async def create(
        cls,
        cmd: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> "Process":
        pty_stdout = await PseudoTerminal.create()
        pty_stderr = await PseudoTerminal.create()

        process_env = {**os.environ}
        if env:
            process_env.update(env)

        return cls(
            await asyncio.create_subprocess_exec(
                *cmd,
                stdin=pty_stdout.subprocess_fd,
                stdout=pty_stdout.subprocess_fd,
                stderr=pty_stderr.subprocess_fd,
                env=process_env,
                cwd=cwd,
                start_new_session=True,
            ),
            pty_stdout,
            pty_stderr,
        )

    def __init__(self, process: AsyncIOProcess, pty_stdout: PseudoTerminalIO, pty_stderr: PseudoTerminalIO) -> None:
        self._process = process
        self._pty_stdout = pty_stdout
        self._pty_stderr = pty_stderr
        self._terminated = False
        self._stdout_data: list[str] = []
        self._stderr_data: list[str] = []
        self._read_task_stdout = asyncio.create_task(self._read_loop(self._pty_stdout, is_stdout=True))
        self._read_task_stderr = asyncio.create_task(self._read_loop(self._pty_stderr, is_stdout=False))
        self._send_data_event = TimeoutEvent()
        self._idle_timeout = 0.0

    async def interact(
        self, input_text: str | None, wait_for_output: int, idle_timeout: float
    ) -> tuple[str, str]:
        self._assert_not_terminated()
        self._send_data_event.clear()

        self._idle_timeout = idle_timeout
        if input_text:
            self._pty_stdout.writer.write(input_text.encode("utf-8"))
            await self._pty_stdout.writer.drain()

        # If there's already available data, just wait for the idle timeout.
        # Otherwise, wait the longer amount of time for output to be available.
        has_data = len(self._stdout_data) > 0 or len(self._stderr_data) > 0
        self._send_data_event.start_timer(
            idle_timeout if has_data else wait_for_output
        )
        await self._send_data_event.wait()

        stdout = "".join(self._stdout_data)
        stderr = "".join(self._stderr_data)
        self._stdout_data.clear()
        self._stderr_data.clear()

        return stdout, stderr

    async def terminate(self, timeout: int = 30) -> None:
        self._assert_not_terminated()
        self._terminated = True
        self._pty_stdout.writer.write(b"exit\n")
        try:
            await asyncio.wait_for(self._pty_stdout.writer.drain(), timeout=timeout)
        except (
            BrokenPipeError,
            ConnectionResetError,
            TimeoutError,
            asyncio.TimeoutError,
        ):
            pass

        # Cancel the reading tasks
        for task in [self._read_task_stdout, self._read_task_stderr]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Clean up the timeout handler
        self._send_data_event.cancel()

        # Ensure the process is terminated
        if self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=timeout)
            except (TimeoutError, asyncio.TimeoutError):
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
        else:
            try:
                await self._process.wait()
            except ProcessLookupError:
                pass

        self._pty_stdout.cleanup()
        self._pty_stderr.cleanup()

    async def _read_loop(self, pty: PseudoTerminalIO, is_stdout: bool) -> None:
        """Read decoded data from the PTY and process it."""
        try:
            while not self._terminated:
                decoded_str = await pty.read(4096)
                if not decoded_str:  # EOF
                    break

                self._receive_data(decoded_str, is_stdout=is_stdout)
        except (asyncio.CancelledError, BrokenPipeError, ConnectionResetError):
            pass

    def _receive_data(self, new_data: str, is_stdout: bool) -> None:
        if is_stdout:
            self._stdout_data.append(new_data)
            total_size = sum(len(data) for data in self._stdout_data)
        else:
            self._stderr_data.append(new_data)
            total_size = sum(len(data) for data in self._stderr_data)

        if total_size >= 4096:
            self._send_data_event.set()
        else:
            self._send_data_event.start_timer(self._idle_timeout)

    def _assert_not_terminated(self) -> None:
        assert not self._terminated, "process must not be terminated"
