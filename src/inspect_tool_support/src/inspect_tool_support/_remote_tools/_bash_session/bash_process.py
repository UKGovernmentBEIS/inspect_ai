import asyncio
import uuid
from asyncio.subprocess import Process

import inspect_tool_support._remote_tools._bash_session._state_machine as StateMachine
from inspect_tool_support._remote_tools._bash_session._pseudo_terminal import (
    PseudoTerminal,
    PseudoTerminalStdIn,
)
from inspect_tool_support._remote_tools._bash_session._safe_stream_reader import (
    SafeStreamReader,
)
from inspect_tool_support._remote_tools._bash_session._timeout_params import (
    NonInteractiveParams,
    TimeoutParams,
)
from inspect_tool_support._remote_tools._bash_session.tool_types import (
    BashCommandResult,
)


class BashProcess:
    @classmethod
    async def create(cls) -> "BashProcess":
        pty = await PseudoTerminal.create()

        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            # Hand the terminal side of the PTY to the bash process as its stdin
            stdin=pty.terminal_fd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return cls(process, pty)

    def __init__(self, process: Process, pty: PseudoTerminalStdIn) -> None:
        self._process = process
        self._pty = pty
        assert (
            process.stdout and process.stderr
        ), "process must have 'stdout' and 'stderr'"

        self._stdout_reader = SafeStreamReader(process.stdout, self._on_stdout_data)
        self._stderr_reader = SafeStreamReader(process.stderr, self._on_stderr_data)
        self._state: StateMachine.State = StateMachine.Idle()

    @property
    def _execute_in_progress(self) -> bool:
        return self._state.type != "Idle"

    async def execute_command(
        self,
        command: str,
        timeout: TimeoutParams | None = None,
    ) -> BashCommandResult:
        if timeout is None:
            timeout = NonInteractiveParams(timeout=30)
        return await (
            self._send_input(command, timeout)
            if self._state.type == "WaitingForModelToRequestMore"
            else self._execute_command(command, timeout)
        )

    async def _execute_command(
        self, command: str, timeout_params: TimeoutParams
    ) -> BashCommandResult:
        assert self._state.type == "Idle", "must be idle to execute a command"

        # Set up to detect command completion
        marker = f"CMD_COMPLETE_{uuid.uuid4().hex}"

        # For each command, we have bash to 3 things
        # - execute the caller's command
        # - do an `echo` that captures the command's exit status
        # - echo a marker that will allow us to robustly detect when the command is done
        wrapped_command = f"""
        {command}
        echo "{marker}$?"
        """

        # switch to the new state before going async
        self._state = StateMachine.SendingCommandOrInput(
            marker=marker, timeout_params=timeout_params
        )

        self._pty.writer.write(wrapped_command.encode("utf-8") + b"\n")
        await self._pty.writer.drain()

        return await self._return_something()

    async def terminate(self, timeout: int = 30) -> None:
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

        # Ensure the process is terminated
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            self._process.kill()
            await self._process.wait()

        self._pty.cleanup()

    def _on_stdout_data(self, data: bytes) -> None:
        assert StateMachine.is_state_expecting_data(
            self._state
        ), "must have a command in progress"

        self._state.stdout_data.extend(data)
        if self._state.marker.encode("utf-8") in self._state.stdout_data:
            self._state.completed_event.set()
        if self._state.data_event:
            self._state.data_event.set()

    def _on_stderr_data(self, data: bytes) -> None:
        assert StateMachine.is_state_expecting_data(
            self._state
        ), "must have a command in progress"
        self._state.stderr_data.extend(data)
        if self._state.data_event:
            self._state.data_event.set()

    async def _send_input(
        self, command: str, timeout_params: TimeoutParams
    ) -> BashCommandResult:
        assert timeout_params.interactive is True, "must be interactive"
        assert self._state.type == "WaitingForModelToRequestMore"

        marker = self._state.marker

        # switch to the new state before going async
        self._state = StateMachine.SendingCommandOrInput(
            marker=marker, timeout_params=timeout_params
        )

        self._pty.writer.write(command.encode("utf-8"))
        await self._pty.writer.drain()

        return await self._return_something()

    async def _return_something(self) -> BashCommandResult:
        assert self._state.type == "SendingCommandOrInput"

        while True:
            # switch to the new state before going async
            self._state = StateMachine.reducer(self._state)
            try:
                await asyncio.wait_for(
                    asyncio.wait(
                        [
                            asyncio.create_task(event.wait())
                            for event in (
                                self._state.completed_event,
                                self._state.data_event,
                            )
                            if event is not None
                        ],
                        return_when=asyncio.FIRST_COMPLETED,
                    ),
                    timeout=self._state.timeout,
                )
            except (asyncio.TimeoutError, TimeoutError):
                print(f"XXXXXX timeout in state: {self._state}")
                match self._state:
                    case (
                        StateMachine.WaitingForData()
                        | StateMachine.WaitingForComplete()
                    ):
                        # if we get here, the command didn't complete (if in
                        # non-interactive mode) or didn't send any data (if in
                        # interactive mode) within the timeout
                        raise
                    case StateMachine.WaitingForDebounce() as old_state:
                        # getting here means that we hit the end of the debounce blackout
                        # with data ready to be returned
                        out_str, err_str = self._get_stream_strings()
                        self._state = StateMachine.WaitingForModelToRequestMore(
                            marker=old_state.marker,
                            completed_event=old_state.completed_event,
                            stdout_data=old_state.stdout_data,
                            stderr_data=old_state.stderr_data,
                        )
                        return BashCommandResult(
                            status=None,
                            stdout=out_str,
                            stderr=err_str,
                        )
                    case x:
                        assert False, f"Unexpected timeout state: {x}"

            print(
                f"XXXXXX await completed in state: {self._state} w/{self._state.completed_event.is_set()=}"
            )

            if self._state.completed_event.is_set():
                break

            # This means that we received data. If we're outside the blackout
            # period, return the partial data.
            print(f"XXXXXX received partial data event set in state: {self._state}")

        # switch to the new state before going async
        self._state = StateMachine.ProcessingCompletion(self._state.marker)

        # Get exit status
        self._pty.writer.write(b"cat /tmp/exit_status\n")
        await self._pty.writer.drain()

        # Wait a short time for exit status to be available
        await asyncio.sleep(0.1)

        out_str, err_str = self._get_stream_strings()
        # out_str now looks like:
        # <command output>CMD_COMPLETE_eecf22460a39491c9dc7de05db31c53a<exit status>

        parts = out_str.split(self._state.marker)

        print(f"XXXXXX command completed\n\t{out_str=}\n\t{parts=}")

        assert len(parts) == 2, "marker not found in command output"
        command_output = parts[0]
        exit_status = parts[1].strip()
        assert exit_status.isnumeric(), "exit status not found in command output"

        self._state = StateMachine.Idle()

        # Create the result with what we have
        return BashCommandResult(
            status=int(exit_status),
            stdout=command_output,
            stderr=err_str,
        )

    def _get_stream_strings(self) -> tuple[str, str]:
        assert StateMachine.is_state_expecting_data(
            self._state
        ), "must have a command in progress"

        result = self._state.stdout_data.decode(
            "utf-8"
        ), self._state.stderr_data.decode("utf-8")
        self._state.stdout_data.clear()
        self._state.stderr_data.clear()
        return result
