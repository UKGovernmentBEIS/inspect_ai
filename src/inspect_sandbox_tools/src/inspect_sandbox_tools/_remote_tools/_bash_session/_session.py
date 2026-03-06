import asyncio

from ._process import Process
from .tool_types import BashRestartResult, InteractResult


class Session:
    @classmethod
    async def create(cls) -> "Session":
        return cls(await Process.create())

    def __init__(self, process: Process) -> None:
        self._process = process

    async def interact(
        self, input_text: str | None, wait_for_output: int, idle_timeout: float
    ) -> InteractResult:
        return await self._process.interact(input_text, wait_for_output, idle_timeout)

    async def restart(self, timeout: int = 30) -> BashRestartResult:
        _, new_process = await asyncio.gather(
            self._process.terminate(timeout=timeout), Process.create()
        )
        self._process = new_process
        return "shell restarted successfully"
