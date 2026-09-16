"""Tests for ``resolve_sandbox_backup_paths`` (auto-home-dir defaulting)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Literal, Union, overload

import pytest

from inspect_ai.util._checkpoint._restore_scope import RestoreScopeError
from inspect_ai.util._checkpoint.sandbox_paths import (
    SandboxBackupPaths,
    resolve_sandbox_backup_paths,
)
from inspect_ai.util._sandbox.context import sandbox_environments_context_var
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult


class FakeSandbox(SandboxEnvironment):
    """Minimal sandbox whose ``exec`` returns a canned home + cache lookup.

    Mirrors ``_resolve_home_and_cache``'s ``echo "$h"; printf %s "<cache>"``
    output: home on the first line, cache dir on the second. ``cache``
    defaults to ``<home>/.cache``.
    """

    def __init__(self, home: str | None, cache: str | None = None) -> None:
        super().__init__()
        self._home = home
        self._cache = cache if cache is not None else (home and f"{home}/.cache")

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
        return ExecResult(
            success=True,
            returncode=0,
            stdout=f"{self._home}\n{self._cache}",
            stderr="",
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
    # Auto-home: capture home; exclude the XDG cache dir + all .cache dirs.
    # `home` marks the include set as the auto-included home dir, so
    # resume re-owns what it restores under it.
    assert resolved.paths == {
        "default": SandboxBackupPaths(
            include=["/root"], exclude=["/root/.cache", "**/.cache"], home="/root"
        )
    }


async def test_no_entry_honors_xdg_cache_home() -> None:
    with _sandboxes({"default": FakeSandbox("/root", cache="/var/cache/agent")}):
        resolved = await resolve_sandbox_backup_paths({})
    assert resolved.paths == {
        "default": SandboxBackupPaths(
            include=["/root"], exclude=["/var/cache/agent", "**/.cache"], home="/root"
        )
    }


async def test_entry_still_excludes_caches() -> None:
    with _sandboxes({"default": FakeSandbox("/root")}):
        resolved = await resolve_sandbox_backup_paths(
            {"default": ["/workspace", "/opt/state"]}
        )
    # Configured includes win, but caches are excluded even so. The home
    # dir is not the include set, so `home` is unset: configured paths
    # keep their recorded ownership on resume.
    assert resolved.paths == {
        "default": SandboxBackupPaths(
            include=["/workspace", "/opt/state"],
            exclude=["/root/.cache", "**/.cache"],
            home=None,
        )
    }


async def test_empty_list_opts_out() -> None:
    with _sandboxes({"default": FakeSandbox("/root")}):
        resolved = await resolve_sandbox_backup_paths({"default": []})
    assert resolved.paths == {}
    assert resolved.unscopable == {}


async def test_unresolvable_home_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with _sandboxes({"default": FakeSandbox(None)}):
        with caplog.at_level(
            logging.WARNING, logger="inspect_ai.util._checkpoint.sandbox_paths"
        ):
            resolved = await resolve_sandbox_backup_paths({})
    assert resolved.paths == {}
    # Unresolvable is not unscopable: the pin check treats it as transient.
    assert resolved.unscopable == {}
    assert any("could not resolve home dir" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "include, message",
    [
        (["workspace"], "not an absolute path"),
        (["/workspace", "relative/state"], "not an absolute path"),
        (["/"], "capture root of '/'"),
    ],
)
async def test_unrestorable_configured_entry_fails_at_provisioning(
    include: list[str], message: str
) -> None:
    # A configured include set is validated with the restore's own rules
    # so a capture that could never be restored fails before the first
    # checkpoint is taken, not when the retry tries to resume.
    with _sandboxes({"default": FakeSandbox("/root")}):
        with pytest.raises(RestoreScopeError, match=message) as excinfo:
            await resolve_sandbox_backup_paths({"default": include})
    assert "sandbox_paths for sandbox 'default'" in str(excinfo.value)


async def test_unscopeable_home_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # An image with HOME=/ has no home dir a restore can scope to; like an
    # unresolvable home, that is the image's doing, not a config error.
    with _sandboxes({"default": FakeSandbox("/"), "tools": FakeSandbox("/root")}):
        with caplog.at_level(
            logging.WARNING, logger="inspect_ai.util._checkpoint.sandbox_paths"
        ):
            resolved = await resolve_sandbox_backup_paths({})
    assert set(resolved.paths) == {"tools"}
    # Reported so the resume-time pin check can name the permanent cause.
    assert set(resolved.unscopable) == {"default"}
    assert "cannot be scoped for restore" in resolved.unscopable["default"]
    assert any(
        "home dir of sandbox 'default'" in r.message
        and "skipping sandbox backup" in r.message
        for r in caplog.records
    )


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
    assert resolved.paths == {
        "default": SandboxBackupPaths(
            include=["/root"], exclude=["/root/.cache", "**/.cache"], home="/root"
        ),
        "tools": SandboxBackupPaths(
            include=["/opt/agent-state"], exclude=["/home/agent/.cache", "**/.cache"]
        ),
    }
