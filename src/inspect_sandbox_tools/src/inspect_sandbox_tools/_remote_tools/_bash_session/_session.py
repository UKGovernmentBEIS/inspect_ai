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
        self._retired_processes: list[Process] = []

    async def interact(
        self,
        input_text: str | None,
        wait_for_output: int,
        idle_timeout: float,
        max_output_bytes: int | None,
    ) -> InteractResult:
        return await self._process.interact(
            input_text, wait_for_output, idle_timeout, max_output_bytes
        )

    async def restart(self, timeout: int = 30) -> BashRestartResult:
        old_process = self._process
        _, new_process = await asyncio.gather(
            old_process.terminate(timeout=timeout),
            Process.create(user=self._user),
        )
        self._retired_processes.append(old_process)
        self._process = new_process
        return "shell restarted successfully"

    async def terminate(self, timeout: int = 30) -> None:
        """Terminate this session's shell process."""
        await self._process.terminate(timeout=timeout)

    async def shutdown(self, timeout: int = 30) -> None:
        """Forcefully terminate this server-owned shell during server shutdown."""
        processes = [self._process, *self._retired_processes]
        self._retired_processes.clear()
        results = await asyncio.gather(
            *(process.shutdown(timeout=timeout) for process in processes),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise RuntimeError("; ".join(str(error) for error in errors))
