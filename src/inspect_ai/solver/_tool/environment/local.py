import tempfile
from pathlib import Path
from typing import Literal, Union, overload

import aiofiles
from typing_extensions import override

from inspect_ai.util import ExecResult, subprocess

from .environment import ToolEnvironment, ToolEnvironments
from .registry import toolenv


@toolenv(name="local")
class LocalToolEnvironment(ToolEnvironment):
    @classmethod
    async def setup(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> ToolEnvironments:
        # local tool environments just provide a single default tool env
        environment = LocalToolEnvironment()
        return ToolEnvironments(
            environments={"default": environment}, cleanup=environment.cleanup
        )

    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    @override
    async def exec(
        self,
        cmd: str | list[str],
        input: str | bytes | None = None,
        env: dict[str, str] = {},
        timeout: int | None = None,
    ) -> ExecResult[str]:
        return await subprocess(
            args=cmd, input=input, cwd=self.directory.name, env=env, timeout=timeout
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

    async def cleanup(self) -> None:
        self.directory.cleanup()

    def _resolve_file(self, file: str) -> str:
        path = Path(file)
        if path.is_absolute():
            return file
        else:
            return (Path(self.directory.name) / Path(file)).as_posix()
