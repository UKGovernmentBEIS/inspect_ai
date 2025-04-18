import asyncio
import uuid
from asyncio.subprocess import Process

import inspect_tool_support._remote_tools._bash_interactive._state_machine as StateMachine
from inspect_tool_support._remote_tools._bash_interactive._pseudo_terminal import (
    PseudoTerminal,
    PseudoTerminalStdIn,
)
from inspect_tool_support._remote_tools._bash_interactive._timeout_params import (
    NonInteractiveParams,
    TimeoutParams,
)
from inspect_tool_support._remote_tools._bash_interactive.tool_types import (
    BashInputResult,
)
from inspect_tool_support._util._safe_stream_reader import SafeStreamReader


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

    async def execute_input(
        self,
        command: str,
        timeout: TimeoutParams | None = None,
    ) -> BashInputResult:
        if timeout is None:
            timeout = NonInteractiveParams(timeout=30)
        return await (
            self._send_input(command, timeout)
            if self._state.type == "WaitingForModelToRequestMore"
            else self._execute_command(command, timeout)
        )

    async def _execute_command(
        self, command: str, timeout_params: TimeoutParams
    ) -> BashInputResult:
        assert (
            self._state.type == "Idle"
        ), f"must be idle to execute a command {self._state.type}"

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

        print(f"XXXXX sending input to bash: {wrapped_command}")

        # switch to the new state before going async
        self._state = StateMachine.SendingCommandOrInput(
            marker=marker, timeout_params=timeout_params
        )

        print(f"XXXX setting state to {self._state.type}")

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

        print(f"XXXX received stdout data in state {self._state.type}: {str(data)}")

        self._state.stdout_data.extend(data)
        if self._state.marker.encode("utf-8") in self._state.stdout_data:
            self._state.completed_event.set()
        if self._state.data_event:
            self._state.data_event.set()

    def _on_stderr_data(self, data: bytes) -> None:
        assert StateMachine.is_state_expecting_data(
            self._state
        ), "must have a command in progress"

        print(f"XXXX received stderr data in state {self._state.type}: {str(data)}")

        self._state.stderr_data.extend(data)
        if self._state.data_event:
            self._state.data_event.set()

    async def _send_input(
        self, command: str, timeout_params: TimeoutParams
    ) -> BashInputResult:
        assert timeout_params.interactive is True, "must be interactive"
        assert self._state.type == "WaitingForModelToRequestMore"

        marker = self._state.marker

        # switch to the new state before going async
        self._state = StateMachine.SendingCommandOrInput(
            marker=marker, timeout_params=timeout_params
        )

        print(f"XXXX setting state to {self._state.type}")

        self._pty.writer.write(command.encode("utf-8"))
        await self._pty.writer.drain()

        return await self._return_something()

    async def _return_something(self) -> BashInputResult:
        assert self._state.type == "SendingCommandOrInput"

        while True:
            # switch to the new state before going async
            new_state = StateMachine.pre_await_reducer(self._state)
            print(
                f"XXXX moving from {self._state.type} to {new_state.type} before waiting with {new_state.timeout=}"
            )
            self._state = new_state
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
                print(f"XXXXXX timeout in state: {self._state.type}")
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
                        out_str, err_str, new_state_2 = StateMachine.send_data_reducer(
                            old_state, False
                        )
                        self._state = new_state_2
                        print(
                            f"XXXX setting state to {self._state.type} and returning partial data"
                        )

                        return BashInputResult(
                            stdout=out_str,
                            stderr=err_str,
                        )
                    case x:
                        assert False, f"Unexpected timeout state: {x}"

            print(
                f"XXXXXX await completed in state: {self._state.type} w/{self._state.completed_event.is_set()=}"
            )

            if self._state.completed_event.is_set():
                break

            # This means that we received data. If we're outside the blackout
            # period, return the partial data.
            print(
                f"XXXXXX received partial data event set in state: {self._state.type}"
            )

        out_str, err_str, new_state_3 = StateMachine.send_data_reducer(
            self._state, True
        )
        # out_str now looks like:
        # <command output>CMD_COMPLETE_eecf22460a39491c9dc7de05db31c53a<exit status>\n

        parts = out_str.split(self._state.marker)

        assert len(parts) == 2, "marker not found in command output"
        command_output = parts[0]
        exit_status = parts[1].strip()
        assert exit_status.isnumeric(), "exit status not found in command output"

        self._state = new_state_3
        print(f"XXXX setting state to {self._state.type}")

        # Create the result with what we have
        return BashInputResult(
            stdout=command_output,
            stderr=err_str,
        )
