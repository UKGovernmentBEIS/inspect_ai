"""Tests for async-generator hooks on loops patched by nest_asyncio2."""

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest import mock

import anyio

from inspect_ai._util._async import init_nest_asyncio


async def _stream(closed: anyio.Event) -> AsyncIterator[bytes]:
    """Yield once, then clean up on close the way httpcore2's byte stream does."""
    try:
        yield b"chunk"
    except BaseException:
        with anyio.CancelScope(shield=True):
            await anyio.lowlevel.checkpoint()
        closed.set()
        raise


def _run_after_nest_asyncio(
    main: Callable[[], Awaitable[None]], unraisable: list[Any]
) -> None:
    """Run `main` on a new loop once `init_nest_asyncio()` has patched the loop class."""

    async def apply_nest_asyncio() -> None:
        init_nest_asyncio()

    asyncio.run(apply_nest_asyncio())
    loop = asyncio.new_event_loop()
    try:
        with mock.patch.object(sys, "unraisablehook", unraisable.append):
            loop.run_until_complete(main())
    finally:
        loop.close()


def test_nest_asyncio_run_until_complete_installs_asyncgen_hooks() -> None:
    hooks = sys.get_asyncgen_hooks()
    finalizers: list[Any] = []

    async def main() -> None:
        finalizers.append(sys.get_asyncgen_hooks().finalizer)

    unraisable: list[Any] = []
    _run_after_nest_asyncio(main, unraisable)
    assert finalizers[0] is not None
    assert unraisable == []
    assert sys.get_asyncgen_hooks() == hooks


def test_abandoned_stream_does_not_break_fail_after_with_nest_asyncio() -> None:
    async def main() -> None:
        closed = anyio.Event()
        with anyio.fail_after(10):
            stream = _stream(closed)
            await stream.__anext__()
            del stream
            await anyio.lowlevel.checkpoint()
        with anyio.fail_after(10):
            await closed.wait()

    unraisable: list[Any] = []
    _run_after_nest_asyncio(main, unraisable)
    assert unraisable == []
