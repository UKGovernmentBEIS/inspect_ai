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

from inspect_ai._util import asyncfiles


@pytest.fixture(autouse=True)
def _async_fs() -> Generator[None, None, None]:
    fs = asyncfiles.AsyncFilesystem()
    token = asyncfiles._current_async_fs.set(fs)
    try:
        yield
    finally:
        asyncfiles._current_async_fs.reset(token)
