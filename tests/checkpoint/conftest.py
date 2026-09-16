"""Checkpoint test fixtures.

The checkpointing code path runs under a shared ``AsyncFilesystem``
context that the production entrypoint (``inspect_ai._eval.eval``)
installs via ``with_async_fs(...)``. Tests bypass that wrapper, so
this autouse fixture supplies the same context for every test in
this directory — sync or async, since the ``ContextVar`` install is
itself synchronous and a no-op for tests that don't touch the fs.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from test_helpers.local_shell_sandbox import sandbox_path

from inspect_ai._util import asyncfiles
from inspect_ai.util._sandbox import _privileged as privileged


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
