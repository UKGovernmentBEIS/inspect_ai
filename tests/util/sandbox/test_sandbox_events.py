from typing import Literal, overload

import anyio

from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._subprocess import ExecResult


class _GatedSandbox(SandboxEnvironment):
    """`poll` waits for `release`; other commands return at once."""

    def __init__(self) -> None:
        super().__init__()
        self.release = anyio.Event()

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        if cmd == ["poll"]:
            await self.release.wait()
        return ExecResult(success=True, returncode=0, stdout="", stderr="")

    async def write_file(self, file: str, contents: str | bytes) -> None:
        pass

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        return "" if text else b""

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


async def test_no_events_suppresses_only_the_calling_task() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    sandbox = _GatedSandbox()
    proxy = SandboxEnvironmentProxy(sandbox)
    polling = anyio.Event()

    async def poll() -> None:
        with proxy.no_events():
            polling.set()
            await proxy.exec(["poll"])
            await proxy.write_file("hidden.txt", "hidden")
            await proxy.read_file("hidden.txt")

    async with anyio.create_task_group() as tg:
        tg.start_soon(poll)
        await polling.wait()
        await proxy.exec(["work"])
        await proxy.write_file("shown.txt", "shown")
        await proxy.read_file("shown.txt")
        sandbox.release.set()

    events = [e for e in transcript.events if isinstance(e, SandboxEvent)]
    assert [(e.action, e.cmd or e.file) for e in events] == [
        ("exec", "work"),
        ("write_file", "shown.txt"),
        ("read_file", "shown.txt"),
    ]
