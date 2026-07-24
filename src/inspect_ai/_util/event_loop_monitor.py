"""Background watchdog that detects event loop stalls.

Wakes up at a fixed cadence and records whenever the actual wake-up
arrives later than expected — a proxy for sync I/O or other blocking
work that's pinning the loop. Useful both as a production watchdog
(logs stalls over a threshold) and as a test instrument (the yielded
stats expose the largest stall observed).

Usage:
    from inspect_ai._util.event_loop_monitor import event_loop_monitor

    async with event_loop_monitor():
        await do_work()

    # Custom cadence/threshold (seconds); inspect the stats afterwards:
    async with event_loop_monitor(interval=0.005, threshold=0.25) as stats:
        await do_work()
    assert stats.max_lateness_ms < 50

`interval` controls how often the watchdog checks the loop; `threshold`
is the lateness (in seconds) above which a warning is logged. Warnings
go to the module logger (`inspect_ai._util.event_loop_monitor`) at
WARNING level — ensure logging is configured to surface them.

Backend-agnostic (anyio), so it works under both asyncio and trio.
"""

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import anyio

from inspect_ai.util._anyio import inner_exception

logger = logging.getLogger(__name__)


@dataclass
class EventLoopMonitorStats:
    """Observations collected by a running event-loop monitor."""

    max_lateness: float = 0.0
    """Largest observed tick lateness, in seconds."""

    stalls: int = 0
    """Number of ticks whose lateness exceeded the threshold."""

    @property
    def max_lateness_ms(self) -> float:
        return self.max_lateness * 1000


async def _monitor_loop(
    interval: float, threshold: float, stop: anyio.Event, stats: EventLoopMonitorStats
) -> None:
    next_tick = time.monotonic()
    while not stop.is_set():
        next_tick += interval
        delay = next_tick - time.monotonic()
        if delay > 0:
            await anyio.sleep(delay)
        # Measure lateness before honoring `stop`: a block that ends right
        # before teardown leaves us parked in the sleep above with `stop`
        # already set, and that final wake-up is exactly the stall we want
        # to record. Returning early here would discard it.
        lateness = time.monotonic() - next_tick
        if lateness > stats.max_lateness:
            stats.max_lateness = lateness
        if lateness > threshold:
            stats.stalls += 1
            logger.warning(
                "event loop blocked for ~%.0fms (threshold=%.0fms)",
                lateness * 1000,
                threshold * 1000,
            )
            # Reset baseline so a single stall doesn't generate
            # a cascade of catch-up warnings.
            next_tick = time.monotonic()
        if stop.is_set():
            return


@asynccontextmanager
async def event_loop_monitor(
    interval: float = 0.1,
    threshold: float = 1.0,
) -> AsyncIterator[EventLoopMonitorStats]:
    """Scoped event-loop monitor.

    Yields a stats object that is updated live as the monitored block
    runs and is final once the block exits.
    """
    stats = EventLoopMonitorStats()
    stop = anyio.Event()
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_monitor_loop, interval, threshold, stop, stats)
            try:
                yield stats
            finally:
                stop.set()
    except Exception as ex:
        # anyio task groups wrap body exceptions in an ExceptionGroup;
        # unwrap so callers' `except SpecificError` keeps working
        raise inner_exception(ex) from None
