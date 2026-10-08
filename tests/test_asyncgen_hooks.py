"""Tests for the async-generator hooks conftest gives every async test."""

import asyncio
import functools
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest import mock

import anyio
import pytest
from test_helpers.utils import with_asyncgen_hooks

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


async def _abandon_stream(wait_for_close: bool) -> None:
    """Start a stream and drop it unclosed inside a `fail_after` scope."""
    closed = anyio.Event()
    with anyio.fail_after(10):
        stream = _stream(closed)
        await stream.__anext__()
        del stream
        if wait_for_close:
            await closed.wait()
        else:
            await anyio.lowlevel.checkpoint()


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


def test_abandoned_stream_breaks_fail_after_without_hooks() -> None:
    unraisable: list[Any] = []
    with pytest.raises(RuntimeError, match="isn't the current tasks's current cancel"):
        _run_after_nest_asyncio(
            functools.partial(_abandon_stream, wait_for_close=False), unraisable
        )
    assert [str(u.exc_value) for u in unraisable] == [
        "async generator ignored GeneratorExit"
    ]


def test_with_asyncgen_hooks_closes_abandoned_stream_in_its_own_task() -> None:
    hooks = sys.get_asyncgen_hooks()
    unraisable: list[Any] = []
    _run_after_nest_asyncio(
        with_asyncgen_hooks(functools.partial(_abandon_stream, wait_for_close=True)),
        unraisable,
    )
    assert unraisable == []
    assert sys.get_asyncgen_hooks() == hooks


async def test_async_tests_run_with_asyncgen_hooks() -> None:
    assert sys.get_asyncgen_hooks().finalizer is not None
