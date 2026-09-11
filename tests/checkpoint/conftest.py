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

from inspect_ai._util import asyncfiles
from inspect_ai.util._sandbox import _privileged as privileged


@pytest.fixture(autouse=True)
def _host_tools_on_pinned_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the local-shell sandbox fakes find Homebrew coreutils on macOS.

    The strategies' in-sandbox scripts resolve utilities through the pinned
    system directories only. On Linux ``sha256sum``, ``zstd`` and friends live
    there; on macOS they come from Homebrew, so the host ``PATH`` is appended
    after the system directories for these tests (the pin itself is covered by
    ``tests/util/sandbox/test_privileged.py``).
    """
    if sys.platform == "darwin":
        monkeypatch.setattr(
            privileged,
            "SYSTEM_PATH",
            f"{privileged.SYSTEM_PATH}{os.pathsep}{os.environ.get('PATH', '')}",
        )


@pytest.fixture(autouse=True)
def _async_fs() -> Generator[None, None, None]:
    fs = asyncfiles.AsyncFilesystem()
    token = asyncfiles._current_async_fs.set(fs)
    try:
        yield
    finally:
        asyncfiles._current_async_fs.reset(token)
