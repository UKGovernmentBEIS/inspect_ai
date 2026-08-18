"""Optional S3 traffic monitor for saturation diagnostics.

Enabled by setting ``INSPECT_S3_MONITOR=1`` (or ``true``/``yes``). When
enabled, monkey-patches ``AsyncFilesystem._create_s3_client_async`` so
that every newly-created aioboto3 S3 client (across all
``AsyncFilesystem`` instances in this process) has ``before-call`` /
``after-call`` event hooks attached. Counters accumulate into a single
per-process ``S3Stats``; a background ticker prints a snapshot every
``interval`` seconds and a FINAL summary on exit.

Useful signals:
- ``in_flight`` and ``peak`` vs. ``max_pool_connections`` (50 by default)
  tell you whether you're saturating the connection pool.
- ``MB/s`` vs. expected S3 bandwidth tells you whether you're saturating
  the network.
- ``ops`` distribution shows which operations are doing the work.
"""

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .asyncfiles import AsyncFilesystem

_ENABLED_ENV = "INSPECT_S3_MONITOR"


def s3_monitor_enabled() -> bool:
    """True if the INSPECT_S3_MONITOR env var is set to a truthy value."""
    return os.getenv(_ENABLED_ENV, "").lower() in ("1", "true", "yes")


@dataclass
class S3Stats:
    """Mutable S3 traffic counters. Internally locked for thread safety."""

    label: str = ""
    in_flight: int = 0
    peak_in_flight: int = 0
    total_requests: int = 0
    total_response_bytes: int = 0
    started_at: float = field(default_factory=time.monotonic)
    by_operation: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)


def _attach_hooks(client: Any, stats: S3Stats) -> None:
    """Register before-call/after-call event hooks on a boto3/aioboto3 client.

    Handlers accept ``**kwargs`` because the hook system passes keyword
    args that vary by event (``model``, ``params``, ``parsed``, etc.);
    the operation name comes from ``model.name`` rather than a dedicated
    kwarg.
    """

    def _before_call(**kwargs: Any) -> None:
        model = kwargs.get("model")
        op_name = getattr(model, "name", "unknown") if model is not None else "unknown"
        with stats._lock:
            stats.in_flight += 1
            if stats.in_flight > stats.peak_in_flight:
                stats.peak_in_flight = stats.in_flight
            stats.total_requests += 1
            stats.by_operation[op_name] = stats.by_operation.get(op_name, 0) + 1

    def _after_call(**kwargs: Any) -> None:
        parsed = kwargs.get("parsed")
        with stats._lock:
            if stats.in_flight > 0:
                stats.in_flight -= 1
            if isinstance(parsed, dict):
                headers = parsed.get("ResponseMetadata", {}).get("HTTPHeaders", {})
                cl = headers.get("content-length")
                if cl:
                    try:
                        stats.total_response_bytes += int(cl)
                    except (ValueError, TypeError):
                        pass

    client.meta.events.register("before-call.s3.*", _before_call)
    client.meta.events.register("after-call.s3.*", _after_call)


# Module-level (per-process) state for the monkey-patch
_patch_installed = False
_current_stats: S3Stats | None = None
_orig_create_s3_client_async: Any = None


def _ensure_patched() -> None:
    """Idempotently monkey-patch AsyncFilesystem._create_s3_client_async.

    The wrapper invokes the original factory, then attaches event hooks
    that route into the current ``_current_stats``. Each process patches
    once on first use.
    """
    global _patch_installed, _orig_create_s3_client_async
    if _patch_installed:
        return
    _patch_installed = True
    _orig_create_s3_client_async = AsyncFilesystem._create_s3_client_async

    async def _wrapped(anonymous: bool = False, region_name: str | None = None) -> Any:
        client = await _orig_create_s3_client_async(
            anonymous=anonymous, region_name=region_name
        )
        if _current_stats is not None:
            _attach_hooks(client, _current_stats)
        return client

    # Intentional monkey-patch for diagnostics; mypy flags it as
    # method-assign which is expected here.
    AsyncFilesystem._create_s3_client_async = staticmethod(_wrapped)  # type: ignore[method-assign]


def _format(stats: S3Stats, *, final: bool = False) -> str:
    elapsed = time.monotonic() - stats.started_at
    with stats._lock:
        mb = stats.total_response_bytes / 1e6
        mbps = mb / elapsed if elapsed > 0 else 0.0
        ops = dict(stats.by_operation)
        in_flight = stats.in_flight
        peak = stats.peak_in_flight
        total = stats.total_requests
    label_str = f"{stats.label} " if stats.label else ""
    prefix = "FINAL " if final else ""
    return (
        f"[S3 monitor] {prefix}{label_str}"
        f"t={elapsed:5.1f}s "
        f"in_flight={in_flight} peak={peak} "
        f"reqs={total} recv={mb:.1f}MB ({mbps:.1f}MB/s) "
        f"ops={ops}"
    )


async def _ticker(stats: S3Stats, interval: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        print(_format(stats), flush=True)


@asynccontextmanager
async def monitor_s3_traffic(
    *, interval: float = 1.0, label: str = ""
) -> AsyncIterator[S3Stats | None]:
    """No-op unless INSPECT_S3_MONITOR is set.

    Installs a per-process monkey-patch on first use that attaches event
    hooks to every newly-created aioboto3 S3 client. Within a process
    only one monitor scope should be active at a time.
    """
    if not s3_monitor_enabled():
        yield None
        return

    global _current_stats
    stats = S3Stats(label=label)
    _current_stats = stats
    _ensure_patched()

    stop = asyncio.Event()
    task = asyncio.create_task(_ticker(stats, interval, stop))
    try:
        yield stats
    finally:
        stop.set()
        try:
            await task
        except Exception:
            pass
        print(_format(stats, final=True), flush=True)
        _current_stats = None
