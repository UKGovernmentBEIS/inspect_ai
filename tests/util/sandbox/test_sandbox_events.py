import shlex
from typing import Literal, overload

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox

from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._sandbox.limits import (
    OutputLimitExceededError,
    override_max_exec_output_size,
)
from inspect_ai.util._subprocess import ExecResult


@pytest.mark.parametrize(
    "cmd",
    [
        ["bash", "-c", "echo hello # /var/tmp/sandbox-services"],
        ["cat", "/var/tmp/sandbox-services/agent.txt"],
        ["printf", "%s", "/var/tmp", "sandbox-services"],
    ],
)
async def test_service_paths_do_not_suppress_exec_events(cmd: list[str]) -> None:
    transcript = Transcript()
    init_transcript(transcript)
    result = ExecResult(success=True, returncode=0, stdout="hello", stderr="")
    proxy = SandboxEnvironmentProxy(CannedSandbox.returning(result))

    assert await proxy.exec(cmd) == result

    events = [e for e in transcript.events if isinstance(e, SandboxEvent)]
    assert len(events) == 1
    assert events[0].cmd == shlex.join(cmd)
    assert events[0].output == "hello"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_service_paths_do_not_bypass_output_limits(stream: str) -> None:
    init_transcript(Transcript())
    result = ExecResult(
        success=True,
        returncode=0,
        stdout="x" * 17 if stream == "stdout" else "",
        stderr="x" * 17 if stream == "stderr" else "",
    )
    proxy = SandboxEnvironmentProxy(CannedSandbox.returning(result))

    with override_max_exec_output_size(16):
        with pytest.raises(OutputLimitExceededError):
            await proxy.exec(["echo", "/var/tmp/sandbox-services"])


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

    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        pass

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, *, user: str | None = None
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], *, user: str | None = None
    ) -> bytes: ...

    async def read_file(
        self, file: str, text: bool = True, *, user: str | None = None
    ) -> str | bytes:
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


def _exec_events(transcript: Transcript) -> list[str | None]:
    return [
        e.cmd
        for e in transcript.events
        if isinstance(e, SandboxEvent) and e.action == "exec"
    ]


async def test_nested_no_events_restores_outer_block() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    proxy = SandboxEnvironmentProxy(_GatedSandbox())

    with proxy.no_events():
        with proxy.no_events():
            await proxy.exec(["inner"])
        await proxy.exec(["outer"])
    await proxy.exec(["after"])

    assert _exec_events(transcript) == ["after"]


async def test_task_started_inside_no_events_stays_suppressed() -> None:
    transcript = Transcript()
    init_transcript(transcript)
    proxy = SandboxEnvironmentProxy(_GatedSandbox())
    parent_exited = anyio.Event()

    async def child() -> None:
        await parent_exited.wait()
        await proxy.exec(["child"])

    async with anyio.create_task_group() as tg:
        with proxy.no_events():
            tg.start_soon(child)
        await proxy.exec(["parent"])
        parent_exited.set()

    assert _exec_events(transcript) == ["parent"]
