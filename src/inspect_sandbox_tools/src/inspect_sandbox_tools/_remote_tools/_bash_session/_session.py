import asyncio

from ._process import Process
from .tool_types import BashRestartResult, InteractResult


class Session:
    @classmethod
    async def create(cls, user: str | None = None) -> "Session":
        return cls(await Process.create(user=user), user=user)

    def __init__(self, process: Process, user: str | None = None) -> None:
        self._process = process
        self._user = user

    async def interact(
        self, input_text: str | None, wait_for_output: int, idle_timeout: float
    ) -> InteractResult:
        return await self._process.interact(input_text, wait_for_output, idle_timeout)

    async def restart(self, timeout: int = 30) -> BashRestartResult:
        _, new_process = await asyncio.gather(
            self._process.terminate(timeout=timeout),
            Process.create(user=self._user),
        )
        self._process = new_process
        return "shell restarted successfully"
