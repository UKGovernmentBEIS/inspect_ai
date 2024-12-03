from typing import Literal, Union, overload

from pydantic import BaseModel
from typing_extensions import override

from inspect_ai.util import ExecResult, SandboxEnvironment, SandboxEnvironmentConfigType


class PodmanSandboxEnvironment(SandboxEnvironment):
    def __init__(self, socket_path: str | None) -> None:
        self.socket_path = socket_path

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        if isinstance(config, PodmanSandboxEnvironmentConfig):
            return {"default": PodmanSandboxEnvironment(config.socket_path)}
        return {"default": PodmanSandboxEnvironment(None)}

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass

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
        return ExecResult(success=True, returncode=0, stdout="Hello!", stderr="")

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        pass

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]:
        return ""


class PodmanSandboxEnvironmentConfig(BaseModel, frozen=True):
    socket_path: str
