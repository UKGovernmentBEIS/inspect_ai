"""Fail a sample attempt while a stubbed provider request is pending, for provider-boundary sentinel tests."""

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, NamedTuple

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream

from inspect_ai._sentinel._context import (
    SentinelFailure,
    SentinelFailures,
    sentinel_failures,
    sentinel_refusal,
)
from inspect_ai._sentinel._scope import sentinel_run
from inspect_ai._util._async import tg_collect
from inspect_ai.model._providers.util.batch import BatchRequest

DENIED = "sentinel denied"


class FailDuringRequest:
    """Keep a sentinel failure for an attempt while a stubbed SDK endpoint waits.

    The stub awaits `pending()`. A sibling task runs `fail()`, which waits for
    the request to start, keeps the failure, and then lets the request return.
    """

    def __init__(self) -> None:
        self._started = anyio.Event()
        self._failed = anyio.Event()

    async def pending(self) -> None:
        self._started.set()
        await self._failed.wait()

    async def fail(self, attempt: SentinelFailures) -> None:
        await self._started.wait()
        attempt.keep(SentinelFailure(PermissionError(DENIED)))
        self._failed.set()


def is_refusal(result: object) -> bool:
    """Whether `result` is the kept failure `FailDuringRequest` raised again."""
    return isinstance(result, SentinelFailure) and str(result.error) == DENIED


class QueuedRequest(NamedTuple):
    request: BatchRequest[Any]
    attempt: SentinelFailures
    result: MemoryObjectReceiveStream[Any]


def queued_request(request: dict[str, Any], custom_id: str) -> QueuedRequest:
    """A batch request queued from its own sample attempt, as `Batcher.generate_for_request()` queues it."""
    with sentinel_failures() as attempt:
        refusal = sentinel_refusal()
    send_stream, receive_stream = anyio.create_memory_object_stream[Any](1)
    return QueuedRequest(
        BatchRequest(
            request=request,
            result_stream=send_stream,
            custom_id=custom_id,
            refusal=refusal,
        ),
        attempt,
        receive_stream,
    )


async def outcome_while_failing(
    call: Callable[[], Awaitable[Any]],
    during: FailDuringRequest,
    monitor: bool = False,
) -> Any:
    """Run `call` in a sample attempt that `during` fails, and return its result or error.

    With `monitor`, `call` runs as a sentinel's monitor (`sentinel_run()`), which
    a kept failure does not stop.
    """
    outcome: list[Any] = []

    async def run() -> None:
        try:
            if monitor:
                with sentinel_run():
                    outcome.append(await call())
            else:
                outcome.append(await call())
        except Exception as ex:
            outcome.append(ex)

    with sentinel_failures() as attempt:
        await while_failing(run, during, attempt)
    return outcome[0]


async def while_failing(
    call: Callable[[], Awaitable[object]],
    during: FailDuringRequest,
    attempt: SentinelFailures,
) -> None:
    """Run `call` while `during` fails `attempt`."""

    async def run() -> None:
        await call()

    tasks: list[Callable[[], Awaitable[None]]] = [run, partial(during.fail, attempt)]
    await tg_collect(tasks)
