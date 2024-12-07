import tempfile
import warnings
from pathlib import Path
from typing import Literal, Union, cast, overload

import aiofiles
from typing_extensions import override

from .._subprocess import ExecResult, subprocess
from .environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from .limits import (
    SandboxEnvironmentLimits,
    verify_exec_result_size,
    verify_read_file_size,
)
from .registry import sandboxenv


@sandboxenv(name="local")
class LocalSandboxEnvironment(SandboxEnvironment):
    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        return {"default": LocalSandboxEnvironment()}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        for environment in environments.values():
            env = cast(LocalSandboxEnvironment, environment)
            env.directory.cleanup()

    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
    ) -> ExecResult[str]:
        if user is not None:
            warnings.warn(
                "The 'user' parameter is ignored in LocalSandboxEnvironment. Commands will run as the current user.",
                UserWarning,
            )

        final_cwd = Path(self.directory.name if cwd is None else cwd)
        if not final_cwd.is_absolute():
            final_cwd = self.directory.name / final_cwd

        result = await subprocess(
            args=cmd,
            input=input,
            cwd=final_cwd,
            env=env,
            timeout=timeout,
            output_limit=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE,
        )
        verify_exec_result_size(result)
        return result

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
        verify_read_file_size(file)
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
