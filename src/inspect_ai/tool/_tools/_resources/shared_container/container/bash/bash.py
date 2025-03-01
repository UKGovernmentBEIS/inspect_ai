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
        print(f"XXXX execute_cmd called with {command=}")
        # for now, we'll just simulate a response
        return BashResponse(status=0, stdout="asdf", stderr="")
        # process = await self._process
        # assert process.stdin
        # print(f"XXXX about to write {command.encode()} to stdin")
        # process.stdin.write(command.encode())
        # await process.stdin.drain()
        # assert process.stdout

        # print(f"XXXX about to read from stdout")
        # result = await process.stdout.readline()
        # print(f"XXXX read {result} from stdout")
        # return result

    async def restart(self, command: str) -> BashResponse:
        process = await self._process
        assert process.stdin
        process.stdin.write(command.encode())
        await process.stdin.drain()
        assert process.stdout
        return await process.stdout.readline()
