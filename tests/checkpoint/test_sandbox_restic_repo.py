"""Regression tests for the in-sandbox restic commands' construction.

``run_sandbox_backup``: the in-sandbox ``restic backup`` runs under
``SandboxEnvironment.exec``, whose captured stdout is capped
(``MAX_EXEC_OUTPUT_SIZE``). restic's ``--json`` status stream (one line
per progress tick) is thrown away by ``from_stdout`` yet still counts
against that cap, so a long backup overflows it and
``OutputLimitExceededError`` surfaces as a failed checkpoint. The backup
must therefore run ``--quiet`` (which drops the status stream) and pin
``RESTIC_PROGRESS_FPS`` empty so an inherited container value can't
re-enable the stream despite ``--quiet``.

``inject_restic``: the root-only directory the binary lands in is
prepared through the verified framework-directory helper, not a bare
``install -d`` that would adopt whatever entry sits at the path, and the
binary is written with the re-verified directory as cwd rather than by
absolute path.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path
from typing import Literal, Union, overload
from unittest.mock import patch

import pytest
from test_helpers.local_shell_sandbox import LocalShellSandbox
from test_helpers.restic import SUMMARY_SNAPSHOT_ID, restic_summary_json

from inspect_ai.util._checkpoint._sandbox_restic.repo import (
    _SANDBOX_RESTIC_DIR,
    inject_restic,
    run_sandbox_backup,
)
from inspect_ai.util._sandbox._framework_directory import _SCRIPT, _VERIFIED_MARKER
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult


class _RecordingSandbox(SandboxEnvironment):
    """Sandbox whose ``exec`` records each ``(cmd, env)`` and returns a summary.

    Every call succeeds; the framework-directory script's verified marker
    is on stderr so its check reads as passed.
    """

    def __init__(self, stdout: str) -> None:
        super().__init__()
        self._stdout = stdout
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []
        self.users: list[str | None] = []
        self.inputs: list[str | bytes | None] = []

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
        self.users.append(user)
        self.inputs.append(input)
        return ExecResult(
            success=True,
            returncode=0,
            stdout=self._stdout,
            stderr=f"{_VERIFIED_MARKER}\n",
        )

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


async def test_inject_restic_writes_binary_in_verified_root_dir(tmp_path: Path) -> None:
    """The binary's directory is verified as root's, and the binary is written inside that verified directory."""
    binary = tmp_path / "restic"
    binary.write_bytes(b"#!/bin/sh\n")
    sandbox = _RecordingSandbox("")

    with (
        patch(
            "inspect_ai.util._checkpoint._sandbox_restic.repo.detect_sandbox_os",
            return_value={"architecture": "amd64"},
        ),
        patch(
            "inspect_ai.util._checkpoint._sandbox_restic.repo.resolve_restic",
            return_value=binary,
        ),
    ):
        await inject_restic(sandbox)

    (verify, _), (write, _) = sandbox.calls
    assert sandbox.users == ["root", "root"]
    assert verify[2] == _SCRIPT
    # <expected uid> <create> <repair> <mode> <parent> <leaf>
    assert verify[4:] == ["0", "1", "0", "700", "/root/.cache", "inspect"]
    # The write re-verifies (without creating) and runs with the directory as
    # cwd: the binary is named relative to it, never by absolute path.
    assert write[2] == _SCRIPT
    assert write[4:10] == ["0", "0", "0", "700", "/root/.cache", "inspect"]
    assert write[10:12] == ["sh", "-c"]
    assert "cat > restic" in write[12] and _SANDBOX_RESTIC_DIR not in write[12]
    assert sandbox.inputs == [None, b"#!/bin/sh\n"]


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="the directory verification script needs GNU/BusyBox stat",
)
@pytest.mark.usefixtures("rootless_sandbox_dir")
async def test_inject_restic_writes_private_binary_through_real_shell(
    tmp_path: Path,
) -> None:
    """Under the real script the binary lands in the directory as a 0700 file, and a re-inject overwrites it."""
    sandbox_dir = tmp_path / "inspect"
    binary = tmp_path / "restic-host"
    binary.write_bytes(b"v1")

    with (
        patch(
            "inspect_ai.util._checkpoint._sandbox_restic.repo._SANDBOX_RESTIC_DIR",
            str(sandbox_dir),
        ),
        patch(
            "inspect_ai.util._checkpoint._sandbox_restic.repo.detect_sandbox_os",
            return_value={"architecture": "amd64"},
        ),
        patch(
            "inspect_ai.util._checkpoint._sandbox_restic.repo.resolve_restic",
            return_value=binary,
        ),
    ):
        await inject_restic(LocalShellSandbox())
        injected = sandbox_dir / "restic"
        assert injected.read_bytes() == b"v1"
        assert stat.S_IMODE(injected.stat().st_mode) == 0o700
        assert stat.S_IMODE(sandbox_dir.stat().st_mode) == 0o700

        binary.write_bytes(b"v2")
        await inject_restic(LocalShellSandbox())
        assert injected.read_bytes() == b"v2"
        assert stat.S_IMODE(injected.stat().st_mode) == 0o700
