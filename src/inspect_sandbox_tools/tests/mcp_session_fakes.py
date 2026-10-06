"""Shared process fakes for MCPServerSession reader tests."""

import asyncio


class FakeStdin:
    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass


class FakeProcess:
    def __init__(self, stdout: asyncio.StreamReader) -> None:
        self.stdout = stdout
        self.stdin = FakeStdin()
        self.pid: int | None = None

    def terminate(self) -> None:
        pass

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass
