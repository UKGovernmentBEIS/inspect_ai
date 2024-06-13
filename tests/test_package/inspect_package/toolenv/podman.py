from typing import Literal, Union, overload

from typing_extensions import override

from inspect_ai.solver import ToolEnvironment, toolenv
from inspect_ai.util import ExecResult


@toolenv(name="podman")
class PodmanToolEnvironment(ToolEnvironment):
    @classmethod
    async def sample_init(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> dict[str, ToolEnvironment]:
        return {"default": PodmanToolEnvironment()}

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: str | None,
        environments: dict[str, ToolEnvironment],
        interrupted: bool,
    ) -> None:
        pass

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        env: dict[str, str] = {},
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
