import tempfile
from pathlib import Path
from typing import Literal, Union, cast, overload

import aiofiles
from typing_extensions import override

from inspect_ai.util import ExecResult, subprocess

from ..tool import ToolError
from .environment import ToolEnvironment
from .registry import toolenv


@toolenv(name="local")
class LocalToolEnvironment(ToolEnvironment):
    @override
    @classmethod
    async def sample_init(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> dict[str, ToolEnvironment]:
        return {"default": LocalToolEnvironment()}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: str | None,
        environments: dict[str, ToolEnvironment],
        interrupted: bool,
    ) -> None:
        for environment in environments.values():
            env = cast(LocalToolEnvironment, environment)
            env.directory.cleanup()

    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        env: dict[str, str] = {},
        timeout: int | None = None,
    ) -> ExecResult[str]:
        try:
            return await subprocess(
                args=cmd, input=input, cwd=self.directory.name, env=env, timeout=timeout
            )
        except UnicodeDecodeError:
            raise ToolError(
                "Unicode decoding error reading command output (it is likely binary rather than text)"
            )

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        # resolve file and ensure the parent dir exists
        file = self._resolve_file(file)
        Path(file).parent.mkdir(parents=True, exist_ok=True)

        if isinstance(contents, str):
            async with aiofiles.open(file, "w", encoding="utf-8") as f:
                await f.write(contents)
        else:
            async with aiofiles.open(file, "wb") as f:
                await f.write(contents)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]:
        file = self._resolve_file(file)
        if text:
            async with aiofiles.open(file, "r", encoding="utf-8") as f:
                return await f.read()
        else:
            async with aiofiles.open(file, "rb") as f:
                return await f.read()

    def _resolve_file(self, file: str) -> str:
        path = Path(file)
        if path.is_absolute():
            return file
        else:
            return (Path(self.directory.name) / Path(file)).as_posix()
