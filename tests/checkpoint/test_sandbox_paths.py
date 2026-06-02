"""Tests for ``resolve_sandbox_backup_paths`` (auto-home-dir defaulting)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Literal, Union, overload

import pytest

from inspect_ai.util._checkpoint.sandbox_paths import resolve_sandbox_backup_paths
from inspect_ai.util._sandbox.context import sandbox_environments_context_var
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult


class FakeSandbox(SandboxEnvironment):
    """Minimal sandbox whose ``exec`` returns a canned home-dir lookup."""

    def __init__(self, home: str | None) -> None:
        super().__init__()
        self._home = home

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
        if self._home is None:
            return ExecResult(success=False, returncode=1, stdout="", stderr="boom")
        return ExecResult(success=True, returncode=0, stdout=self._home, stderr="")

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


@contextmanager
def _sandboxes(envs: dict[str, SandboxEnvironment]) -> Iterator[None]:
    token = sandbox_environments_context_var.set(envs)
    try:
        yield
    finally:
        sandbox_environments_context_var.reset(token)


async def test_no_entry_defaults_to_home() -> None:
    with _sandboxes({"default": FakeSandbox("/root")}):
        resolved = await resolve_sandbox_backup_paths({})
    assert resolved == {"default": ["/root"]}


async def test_entry_used_verbatim() -> None:
    with _sandboxes({"default": FakeSandbox("/root")}):
        resolved = await resolve_sandbox_backup_paths(
            {"default": ["/workspace", "/opt/state"]}
        )
    # Configured paths win; home dir is not appended.
    assert resolved == {"default": ["/workspace", "/opt/state"]}


async def test_empty_list_opts_out() -> None:
    with _sandboxes({"default": FakeSandbox("/root")}):
        resolved = await resolve_sandbox_backup_paths({"default": []})
    assert resolved == {}


async def test_unresolvable_home_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with _sandboxes({"default": FakeSandbox(None)}):
        with caplog.at_level(logging.WARNING):
            resolved = await resolve_sandbox_backup_paths({})
    assert resolved == {}
    assert any("could not resolve home dir" in r.message for r in caplog.records)


async def test_mixed_sandboxes() -> None:
    with _sandboxes(
        {
            "default": FakeSandbox("/root"),  # auto-home
            "tools": FakeSandbox("/home/agent"),  # overridden below
            "scratch": FakeSandbox("/home/scratch"),  # opted out below
        }
    ):
        resolved = await resolve_sandbox_backup_paths(
            {"tools": ["/opt/agent-state"], "scratch": []}
        )
    assert resolved == {
        "default": ["/root"],
        "tools": ["/opt/agent-state"],
    }
