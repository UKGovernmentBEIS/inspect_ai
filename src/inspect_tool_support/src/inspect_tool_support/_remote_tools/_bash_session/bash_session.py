"""This module contains the BashSession class, which is needed because a single inspect subtask related session has a lifetime that extends beyond a single bash process.

This is because the API supports a `restart` command which is implemented by killing one bash process and starting a new one.
"""

import asyncio

from inspect_tool_support._remote_tools._bash_session._timeout_params import (
    InteractiveParams,
)
from inspect_tool_support._remote_tools._bash_session.bash_process import BashProcess
from inspect_tool_support._remote_tools._bash_session.tool_types import (
    BashCommandResult,
    BashRestartResult,
)


class BashSession:
    @classmethod
    async def create(cls) -> "BashSession":
        return cls(await BashProcess.create())

    def __init__(self, process: BashProcess) -> None:
        self._process = process

    async def execute_command(
        self, command: str, timeout: int = 30
    ) -> BashCommandResult:
        # TODO: For now, just force us into interactive mode
        return await self._process.execute_command(
            command, timeout=InteractiveParams(first_data_timeout=timeout, debounce=5)
        )

    async def restart(self, timeout: int = 30) -> BashRestartResult:
        _, new_process = await asyncio.gather(
            self._process.terminate(timeout=timeout), BashProcess.create()
        )
        self._process = new_process
        return BashRestartResult()
