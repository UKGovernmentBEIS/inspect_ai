import tempfile
import warnings
from logging import getLogger
from pathlib import Path
from typing import Literal, Union, overload

from typing_extensions import override

from .._subprocess import ExecResult, subprocess
from ._cli import SANDBOX_CLI
from .environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from .limits import (
    SandboxEnvironmentLimits,
    verify_read_file_size,
)
from .registry import sandboxenv

logger = getLogger(__name__)


@sandboxenv(name="local")
class LocalSandboxEnvironment(SandboxEnvironment):
    # Also defined in inspect_sandbox_tools._util.constants — keep in sync.
    _SANDBOX_TOOLS_DIR_ENV = "INSPECT_SANDBOX_TOOLS_DIR"
    # The server allows up to 30s for resource termination plus bounded HTTP
    # shutdown; the CLI waits 45s for its status, leaving this 55s host limit.
    _SANDBOX_TOOLS_STOP_TIMEOUT = 55
    _INTERRUPTED_SANDBOX_TOOLS_STOP_TIMEOUT = 5

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
        stop_timeout = (
            cls._INTERRUPTED_SANDBOX_TOOLS_STOP_TIMEOUT
            if interrupted
            else cls._SANDBOX_TOOLS_STOP_TIMEOUT
        )
        for environment in environments.values():
            sandbox = environment.as_type(LocalSandboxEnvironment)
            try:
                await sandbox._stop_sandbox_tools(timeout=stop_timeout)
            except Exception as ex:
                logger.warning("Failed to stop local sandbox-tools server: %s", ex)
            finally:
                sandbox.directory.cleanup()

    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._sandbox_tools_dir = Path(self.directory.name) / "sandbox-tools"
        self._sandbox_tools_used = False

    @override
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
        if user is not None:
            warnings.warn(
                "The 'user' parameter is ignored in LocalSandboxEnvironment. Commands will run as the current user.",
                UserWarning,
            )

        final_cwd = Path(self.directory.name if cwd is None else cwd)
        if not final_cwd.is_absolute():
            final_cwd = self.directory.name / final_cwd

        final_env = env
        if cmd and cmd[0] == SANDBOX_CLI:
            self._sandbox_tools_used = True
            final_env = {
                **(env or {}),
                self._SANDBOX_TOOLS_DIR_ENV: str(self._sandbox_tools_dir),
            }

        result = await subprocess(
            args=cmd,
            input=input,
            cwd=final_cwd,
            env=final_env,
            timeout=timeout,
            output_limit=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE,
            concurrency=concurrency,
        )
        return result

    async def _stop_sandbox_tools(self, *, timeout: int) -> None:
        if not self._sandbox_tools_used or not self._sandbox_tools_dir.exists():
            return
        if not Path(SANDBOX_CLI).exists():
            raise RuntimeError("Cannot stop local sandbox-tools server: CLI is missing")

        result = await self.exec(
            [SANDBOX_CLI, "stop-server"],
            cwd="/",
            timeout=timeout,
            timeout_retry=False,
        )
        if not result.success:
            raise RuntimeError(
                "Failed to stop local sandbox-tools server: "
                f"{result.stderr or result.stdout}"
            )

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        # resolve file and ensure the parent dir exists
        file = self._resolve_file(file)
        Path(file).parent.mkdir(parents=True, exist_ok=True)

        if isinstance(contents, str):
            with open(file, "w", encoding="utf-8") as f:
                f.write(contents)
        else:
            with open(file, "wb") as f:
                f.write(contents)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]:
        file = self._resolve_file(file)
        verify_read_file_size(file)
        if text:
            with open(file, "r", newline="", encoding="utf-8") as f:
                return f.read()
        else:
            with open(file, "rb") as f:
                return f.read()

    def default_polling_interval(self) -> float:
        return 0.2

    def _resolve_file(self, file: str) -> str:
        path = Path(file)
        if path.is_absolute():
            return file
        else:
            return (Path(self.directory.name) / Path(file)).as_posix()
