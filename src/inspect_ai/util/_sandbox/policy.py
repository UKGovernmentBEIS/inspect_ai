from __future__ import annotations

from typing import Protocol,runtime_checkable

from inspect_ai._util.error import SandboxPolicyViolationError

from .environment import (
    ExecResult,
    SandboxConnection,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)


@runtime_checkable
class SandboxPolicy(Protocol):
    """Policy for sandbox actions."""

    def check_exec(self, cmd: list[str]) -> None:
        """Check if an execution command is allowed.

        Args:
           cmd: Command to be executed.

        Raises:
           SandboxPolicyViolationError: If the command is not allowed.
        """
        ...

    def check_read_file(self, file: str) -> None:
        """Check if reading a file is allowed.

        Args:
           file: Path to file.

        Raises:
           SandboxPolicyViolationError: If reading the file is not allowed.
        """
        ...

    def check_write_file(self, file: str) -> None:
        """Check if writing a file is allowed.

        Args:
           file: Path to file.

        Raises:
           SandboxPolicyViolationError: If writing the file is not allowed.
        """
        ...


class PolicySandboxEnvironment(SandboxEnvironment):
    """Sandbox environment that enforces a policy."""

    def __init__(self, sandbox: SandboxEnvironment, policy: SandboxPolicy) -> None:
        self._sandbox = sandbox
        self._policy = policy

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self._policy.check_exec(cmd)
        return await self._sandbox.exec(
            cmd=cmd,
            input=input,
            cwd=cwd,
            env=env,
            user=user,
            timeout=timeout,
            timeout_retry=timeout_retry,
            concurrency=concurrency,
        )

    async def write_file(self, file: str, contents: str | bytes) -> None:
        self._policy.check_write_file(file)
        await self._sandbox.write_file(file, contents)

    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        self._policy.check_read_file(file)
        # Type ignore explanation: verify implementation matches protocol overload but type checker might complain
        return await self._sandbox.read_file(file, text=text) # type: ignore

    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        return await self._sandbox.connection(user=user)

    def as_type(self, sandbox_cls: type[SandboxEnvironment]) -> SandboxEnvironment:
        # Delegate to inner sandbox to allow unwrapping or finding specialized methods
        try:
            return self._sandbox.as_type(sandbox_cls)
        except TypeError:
            # If inner sandbox is not the type, check if WE are the type
             if isinstance(self, sandbox_cls):
                return self
             raise

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        # No-op: cleanup is handled by the underlying concrete environments
        # (e.g. DockerSandboxEnvironment) which are unwrapped by the cleanup
        # infrastructure before calling sample_cleanup specific to that provider.
        pass
