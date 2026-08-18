"""Regression tests for ``run_sandbox_backup`` command construction.

The in-sandbox ``restic backup`` runs under ``SandboxEnvironment.exec``,
whose captured stdout is capped (``MAX_EXEC_OUTPUT_SIZE``). restic's
``--json`` status stream (one line per progress tick) is thrown away by
``from_stdout`` yet still counts against that cap, so a long backup
overflows it and ``OutputLimitExceededError`` surfaces as a failed
checkpoint. The backup must therefore run ``--quiet`` (which drops the
status stream) and pin ``RESTIC_PROGRESS_FPS`` empty so an inherited
container value can't re-enable the stream despite ``--quiet``.
"""

from __future__ import annotations

from typing import Literal, Union, overload

from test_helpers.restic import SUMMARY_SNAPSHOT_ID, restic_summary_json

from inspect_ai.util._checkpoint._sandbox_restic.repo import run_sandbox_backup
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult


class _RecordingSandbox(SandboxEnvironment):
    """Sandbox whose ``exec`` records each ``(cmd, env)`` and returns a summary."""

    def __init__(self, stdout: str) -> None:
        super().__init__()
        self._stdout = stdout
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []

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
        self.calls.append((cmd, env))
        return ExecResult(success=True, returncode=0, stdout=self._stdout, stderr="")

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


async def test_run_sandbox_backup_passes_quiet() -> None:
    sandbox = _RecordingSandbox(restic_summary_json())

    summary = await run_sandbox_backup(sandbox, "pw", ["/root"], "tag")

    cmd, _env = sandbox.calls[-1]
    assert "--quiet" in cmd
    assert summary.snapshot_id == SUMMARY_SNAPSHOT_ID  # quiet summary still parses


async def test_run_sandbox_backup_pins_progress_fps_empty() -> None:
    sandbox = _RecordingSandbox(restic_summary_json())

    await run_sandbox_backup(sandbox, "pw", ["/root"], "tag")

    _cmd, env = sandbox.calls[-1]
    assert env is not None and env.get("RESTIC_PROGRESS_FPS") == ""
