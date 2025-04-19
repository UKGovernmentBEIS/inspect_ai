"""This module contains the BashSession class, which is needed because a single inspect subtask related session has a lifetime that extends beyond a single bash process.

This is because the API supports a `restart` command which is implemented by killing one bash process and starting a new one.
"""

import asyncio

from inspect_tool_support._remote_tools._bash_interactive._process import BashProcess
from inspect_tool_support._remote_tools._bash_interactive.tool_types import (
    BashRestartResult,
    InteractResult,
)


class Session:
    @classmethod
    async def create(cls) -> "Session":
        return cls(await BashProcess.create())

    def __init__(self, process: BashProcess) -> None:
        self._process = process

    async def interact(
        self, input_text: str | None, idle_timeout: int
    ) -> InteractResult:
        return await self._process.interact(input_text, idle_timeout)

    async def restart(self, timeout: int = 30) -> BashRestartResult:
        _, new_process = await asyncio.gather(
            self._process.terminate(timeout=timeout), BashProcess.create()
        )
        self._process = new_process
        return BashRestartResult()
