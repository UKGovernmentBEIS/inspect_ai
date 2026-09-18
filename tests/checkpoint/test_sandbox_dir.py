"""The checkpoint strategies' root-only work area is prepared as a verified directory.

``ensure_root_sandbox_dir`` must run the framework-directory script as
``root`` with uid 0 pinned, so a provider that ignores ``user`` fails the
call instead of passing off the default user's directory as root's, and
must let a refusal propagate: checkpointing has no rootless fallback.
These tests run against a scripted fake, so they need neither root nor
Docker; the script itself is covered by ``tests/util/sandbox``.
"""

from __future__ import annotations

from typing import Literal, Union, overload

import pytest

from inspect_ai.util._checkpoint._sandbox_dir import ensure_root_sandbox_dir
from inspect_ai.util._sandbox._framework_directory import (
    _SCRIPT,
    _USER_MISMATCH_MARKER,
    _VERIFIED_MARKER,
    _VIOLATION_MARKER,
    FrameworkDirectoryError,
    FrameworkDirectoryUserError,
)
from inspect_ai.util._sandbox._privileged import SHELL_PATH
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult


class _ScriptedSandbox(SandboxEnvironment):
    """Records the one ``exec`` and answers it with a canned stderr."""

    def __init__(self, stderr: str) -> None:
        super().__init__()
        self._stderr = stderr
        self.calls: list[tuple[list[str], str | None]] = []

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
        self.calls.append((cmd, user))
        return ExecResult(success=True, returncode=0, stdout="", stderr=self._stderr)

    async def write_file(self, file: str, contents: str | bytes) -> None:
        raise NotImplementedError

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        raise NotImplementedError

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        raise NotImplementedError


async def test_ensure_root_sandbox_dir_runs_verified_script_as_root() -> None:
    sandbox = _ScriptedSandbox(f"{_VERIFIED_MARKER}\n")

    await ensure_root_sandbox_dir(sandbox, "/root/.cache/inspect")

    (cmd, user), *rest = sandbox.calls
    assert not rest and user == "root"
    # argv: sh -c SCRIPT sh <expected uid> <create> <repair> <mode> <parent> <leaf>
    assert cmd[:3] == [SHELL_PATH, "-c", _SCRIPT]
    assert cmd[4:] == ["0", "1", "0", "700", "/root/.cache", "inspect"]


async def test_ensure_root_sandbox_dir_refuses_when_not_root() -> None:
    """A provider that ran the check as another uid is an error, not a fallback."""
    sandbox = _ScriptedSandbox(
        f"{_USER_MISMATCH_MARKER}: running as uid 1000, expected uid 0\n"
    )
    with pytest.raises(FrameworkDirectoryUserError, match="expected uid 0"):
        await ensure_root_sandbox_dir(sandbox, "/root/.cache/inspect")


async def test_ensure_root_sandbox_dir_propagates_contract_violation() -> None:
    sandbox = _ScriptedSandbox(
        f"{_VIOLATION_MARKER}: /root/.cache/inspect is a symbolic link\n"
    )
    with pytest.raises(FrameworkDirectoryError, match="symbolic link"):
        await ensure_root_sandbox_dir(sandbox, "/root/.cache/inspect")
