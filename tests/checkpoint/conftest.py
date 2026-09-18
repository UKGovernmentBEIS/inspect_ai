"""Checkpoint test fixtures.

The checkpointing code path runs under a shared ``AsyncFilesystem``
context that the production entrypoint (``inspect_ai._eval.eval``)
installs via ``with_async_fs(...)``. Tests bypass that wrapper, so
this autouse fixture supplies the same context for every test in
this directory — sync or async, since the ``ContextVar`` install is
itself synchronous and a no-op for tests that don't touch the fs.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator

import pytest
from test_helpers.local_shell_sandbox import sandbox_path

from inspect_ai._util import asyncfiles
from inspect_ai.util._checkpoint import _sandbox_dir
from inspect_ai.util._sandbox import _privileged as privileged
from inspect_ai.util._sandbox._framework_directory import ensure_framework_directory
from inspect_ai.util._sandbox.environment import SandboxEnvironment


@pytest.fixture(autouse=True)
def _async_fs() -> Generator[None, None, None]:
    fs = asyncfiles.AsyncFilesystem()
    token = asyncfiles._current_async_fs.set(fs)
    try:
        yield
    finally:
        asyncfiles._current_async_fs.reset(token)


@pytest.fixture(autouse=True)
def _linux_like_system_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Framework commands run by the shell fake resolve utilities via its linux-like ``PATH``.

    ``privileged_exec``/``privileged_shell`` pin ``PATH`` to the system
    directories, so on a macOS host they would find bsdtar rather than
    the GNU-format shim :func:`sandbox_path` puts first. Pointing the pin
    at that path models an image whose system tar is a Linux one.
    """
    monkeypatch.setattr(privileged, "SYSTEM_PATH", sandbox_path())


@pytest.fixture
def rootless_sandbox_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """The strategies' root-only directory is verified for the test user instead of root.

    ``LocalShellSandbox`` ignores ``user="root"`` and runs every command
    as the test user, so ``ensure_root_sandbox_dir`` (which pins uid 0)
    would refuse every directory. This re-points it at the same
    verification for the default user: the real script still runs, so a
    symlink, a foreign owner or a wrong mode at the path is still refused;
    only the uid it expects changes. On a non-Linux host the script cannot
    run at all (it needs GNU/BusyBox ``stat -c``), so the directory is
    created outright instead; tests that expect a refusal must skip there.
    Opt-in rather than autouse so the Docker-backed tests keep the real
    root check.
    """
    verified = ensure_framework_directory

    async def as_test_user(
        env: SandboxEnvironment,
        path: str,
        *,
        user: str | None,
        expected_uid: int | None,
    ) -> None:
        assert user == "root" and expected_uid == 0, "production call must pin root"
        if sys.platform == "linux":
            await verified(env, path, user=None)
        else:
            os.makedirs(path, mode=0o700, exist_ok=True)

    monkeypatch.setattr(_sandbox_dir, "ensure_framework_directory", as_test_user)
