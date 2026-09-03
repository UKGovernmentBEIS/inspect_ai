"""A ``SandboxEnvironment`` fake that runs ``exec`` on the host shell.

File APIs map to host paths and ``user="root"`` is ignored, so code whose
in-sandbox side is plain ``sh`` (tar, dd, find, comm, restic-as-a-binary)
executes for real against a temp dir — no Docker required.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal, Union, overload

from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult


class LocalShellSandbox(SandboxEnvironment):
    """Sandbox fake that executes ``exec`` on the host shell.

    ``extra_env`` overlays the inherited environment (e.g. a ``PATH``
    with a shim dir prepended) for every ``exec``; a per-call ``env``
    is layered on top of that.
    """

    def __init__(self, extra_env: dict[str, str] | None = None) -> None:
        self._extra_env = extra_env

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
        input_bytes = input.encode() if isinstance(input, str) else input
        run_env = {**os.environ, **(self._extra_env or {}), **(env or {})}
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            capture_output=True,
            timeout=120,
            env=run_env,
            cwd=cwd,
        )
        return ExecResult(
            success=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout.decode(errors="replace"),
            stderr=proc.stderr.decode(errors="replace"),
        )

    async def write_file(self, file: str, contents: str | bytes) -> None:
        data = contents.encode() if isinstance(contents, str) else contents
        Path(file).write_bytes(data)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        if text:
            return Path(file).read_text()
        return Path(file).read_bytes()

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass
