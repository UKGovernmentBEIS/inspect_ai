"""Tests for _monitor_proxy proxy death detection."""

from typing import AsyncIterator

import pytest

from inspect_ai.agent._bridge.sandbox.bridge import _monitor_proxy
from inspect_ai.util._sandbox.exec_remote import (
    ExecCompleted,
    ExecOutput,
    ExecStderr,
)


class FakeProcess:
    """Minimal async iterator standing in for ExecRemoteProcess."""

    def __init__(self, events: list[ExecOutput]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> AsyncIterator[ExecOutput]:
        return self

    async def __anext__(self) -> ExecOutput:
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration


async def test_monitor_proxy_failure() -> None:
    """Proxy exits with exit_code=1 → raises RuntimeError with 'failure'."""
    proc = FakeProcess(
        [
            ExecStderr(data="something went wrong"),
            ExecCompleted(exit_code=1),
        ]
    )

    with pytest.raises(RuntimeError, match="failure"):
        await _monitor_proxy(proc)  # type: ignore[arg-type]


async def test_monitor_proxy_success() -> None:
    """Proxy exits with exit_code=0 → returns silently, no exception."""
    proc = FakeProcess(
        [
            ExecCompleted(exit_code=0),
        ]
    )

    await _monitor_proxy(proc)  # type: ignore[arg-type]
