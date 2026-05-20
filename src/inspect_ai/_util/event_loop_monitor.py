"""Background watchdog that detects event loop stalls.

Wakes up at a fixed cadence and logs whenever the actual wake-up
arrives later than expected by more than a threshold. Useful for
catching sync I/O or other blocking work that's pinning the loop.

Usage:
    from inspect_ai._util.event_loop_monitor import event_loop_monitor

    async with event_loop_monitor():
        await do_work()

    # Custom cadence/threshold (seconds):
    async with event_loop_monitor(interval=0.05, threshold=0.25):
        await do_work()

`interval` controls how often the watchdog checks the loop; `threshold`
is the lateness (in seconds) above which a warning is logged. Warnings
go to the module logger (`inspect_ai._util.event_loop_monitor`) at
WARNING level — ensure logging is configured to surface them.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class _EventLoopMonitor:
    """Handle for a running event-loop monitor task."""

    _task: asyncio.Task[None]
    _stop: asyncio.Event

    async def stop(self) -> None:
        self._stop.set()
        await self._task


async def _monitor_loop(interval: float, threshold: float, stop: asyncio.Event) -> None:
    next_tick = time.monotonic()
    while not stop.is_set():
        next_tick += interval
        delay = next_tick - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        if stop.is_set():
            return
        lateness = time.monotonic() - next_tick
        if lateness > threshold:
            logger.warning(
                "event loop blocked for ~%.0fms (threshold=%.0fms)",
                lateness * 1000,
                threshold * 1000,
            )
            # Reset baseline so a single stall doesn't generate
            # a cascade of catch-up warnings.
            next_tick = time.monotonic()


def _start_event_loop_monitor(
    interval: float = 0.1,
    threshold: float = 1.0,
) -> _EventLoopMonitor:
    """Start a background monitor; returns a handle for stopping."""
    stop = asyncio.Event()
    task = asyncio.create_task(_monitor_loop(interval, threshold, stop))
    return _EventLoopMonitor(_task=task, _stop=stop)


@asynccontextmanager
async def event_loop_monitor(
    interval: float = 0.1,
    threshold: float = 1.0,
) -> AsyncIterator[None]:
    """Scoped event-loop monitor."""
    monitor = _start_event_loop_monitor(interval, threshold)
    try:
        yield
    finally:
        await monitor.stop()
