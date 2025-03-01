import asyncio
from asyncio.subprocess import Process

from bash.bash_types import BashResponse


class BashSubprocess:
    def __init__(self) -> None:
        self.__process: Process | None = None
        self._lock = asyncio.Lock()

    @property
    async def _process(self) -> Process:
        async with self._lock:
            if self.__process is None:
                self.__process = await asyncio.create_subprocess_exec(
                    "bash",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
        return self.__process

    async def execute_cmd(self, command: str) -> BashResponse:
        process = await self._process
        assert process.stdin
        process.stdin.write(command.encode())
        await process.stdin.drain()
        assert process.stdout
        return await process.stdout.readline()

    async def restart(self, command: str) -> BashResponse:
        process = await self._process
        assert process.stdin
        process.stdin.write(command.encode())
        await process.stdin.drain()
        assert process.stdout
        return await process.stdout.readline()
