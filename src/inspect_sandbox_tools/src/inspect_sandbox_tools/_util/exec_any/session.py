from .process import Process


class Session:
    @classmethod
    async def create(
        cls,
        cmd: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> "Session":
        return cls(await Process.create(cmd=cmd, env=env, cwd=cwd))

    def __init__(self, process: Process) -> None:
        self._process = process

    async def interact(
        self, input_text: str | None, wait_for_output: int, idle_timeout: float
    ) -> tuple[str,str]:
        return await self._process.interact(input_text, wait_for_output, idle_timeout)

    async def terminate(self, timeout: int = 30) -> None:
        await self._process.terminate(timeout)
