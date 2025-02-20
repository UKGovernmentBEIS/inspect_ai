import shlex
from typing import Any, Literal, Union, overload

from typing_extensions import override

from inspect_ai.util._subprocess import ExecResult

from .environment import (
    SandboxConnection,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)


class SandboxEnvironmentProxy(SandboxEnvironment):
    def __init__(self, sandbox: SandboxEnvironment) -> None:
        self._sandbox = sandbox

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
    ) -> ExecResult[str]:
        command_summary = " ".join([shlex.quote(c) for c in cmd])
        if input:
            command_summary = f"{command_summary} (input: {content_summary(input)})"
        self._sandbox_event("exec", f"```bash\n{command_summary}\n```")
        return await self._sandbox.exec(
            cmd, input, cwd, env, user, timeout, timeout_retry
        )

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        self._sandbox_event("write_file", f"file: {file} ({content_summary(contents)})")
        await self._sandbox.write_file(file, contents)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]:
        self._sandbox_event("read_file", f"file: {file}")
        if text is True:
            return await self._sandbox.read_file(file, True)
        else:
            return await self._sandbox.read_file(file, False)

    @override
    async def connection(self) -> SandboxConnection:
        return await self._sandbox.connection()

    @override
    def context(self) -> Any:
        """Per sandbox type context."""
        return self._sandbox.context()

    def _sandbox_event(
        self, action: Literal["exec", "read_file", "write_file"], summary: str
    ) -> None:
        from inspect_ai.log._transcript import SandboxEvent, transcript

        transcript()._event(SandboxEvent(action=action, summary=summary))

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


def content_summary(content: str | bytes) -> str:
    if isinstance(content, str):
        file_info = f"text - {(len(content.splitlines()),)} lines"
    else:
        file_info = f"binary - {(len(content),)} bytes"
    return file_info
