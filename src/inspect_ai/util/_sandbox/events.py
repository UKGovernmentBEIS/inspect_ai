import shlex
from typing import Literal, Type, Union, overload

from pydantic import JsonValue
from pydantic_core import to_jsonable_python
from typing_extensions import override

from inspect_ai._util.text import truncate_lines
from inspect_ai.util._subprocess import ExecResult

from .environment import (
    ST,
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
        from inspect_ai.log._transcript import SandboxEvent, transcript

        # make call
        result = await self._sandbox.exec(
            cmd, input, cwd, env, user, timeout, timeout_retry
        )

        # yield event
        options: dict[str, JsonValue] = {}
        if cwd:
            options["cwd"] = cwd
        if env:
            options["env"] = to_jsonable_python(env)
        if user:
            options["user"] = user
        if timeout is not None:
            options["timeout"] = timeout
        if timeout_retry is not True:
            options["timeout_retry"] = timeout_retry
        transcript()._event(
            SandboxEvent(
                action="exec",
                cmd=" ".join([shlex.quote(c) for c in cmd]),
                input=content_display(input) if input is not None else None,
                options=options,
                result=result.returncode,
                output=content_display(
                    f"{result.stderr}\n\n{result.stdout}"
                    if result.stderr
                    else result.stdout
                ),
            )
        )

        # return result
        return result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        from inspect_ai.log._transcript import SandboxEvent, transcript

        # make call
        await self._sandbox.write_file(file, contents)

        # yield event
        transcript()._event(
            SandboxEvent(
                action="write_file", file=file, input=content_display(contents)
            )
        )

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]:
        from inspect_ai.log._transcript import SandboxEvent, transcript

        # make call
        if text is True:
            output: str | bytes = await self._sandbox.read_file(file, True)
        else:
            output = await self._sandbox.read_file(file, False)

        # yield event
        transcript()._event(
            SandboxEvent(action="read_file", file=file, output=content_display(output))
        )

        # return result
        return output

    @override
    async def connection(self) -> SandboxConnection:
        return await self._sandbox.connection()

    @override
    def as_type(self, sandbox_cls: Type[ST]) -> ST:
        if isinstance(self._sandbox, sandbox_cls):
            return self._sandbox
        else:
            raise TypeError(
                f"Expected instance of {sandbox_cls.__name__}, got {type(self._sandbox).__name__}"
            )

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


def content_display(content: str | bytes) -> str:
    if isinstance(content, str):
        content, truncated = truncate_lines(content, 20)
        if truncated:
            content = f"{content}\n\nOutput truncated ({truncated} additional lines)"
        return content
    else:
        return f"binary ({pretty_size(len(content))})"


def pretty_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"

    return f"{size / (1024 * 1024):.2f} MB"
