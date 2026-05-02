import contextlib
import time
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from logging import getLogger
from typing import Any, AsyncIterator, Protocol

import anyio
from pydantic import BaseModel, Field, model_validator

from inspect_ai._util.constants import HTTP
from inspect_ai._util.working import sample_waiting_for

logger = getLogger(__name__)


class AdaptiveConcurrency(BaseModel):
    """Bounds for an adaptive concurrency controller.

    Configures the bounds within which an adaptive controller is allowed to
    scale: starting at `start`, growing up to `max`, and never falling below
    `min`. Accepts a string shorthand ("min-max" or "min-start-max") for use
    in CLI flags and config files.
    """

    min: int = Field(default=1)
    """Minimum concurrency (must be >= 1)."""

    max: int = Field(default=200)
    """Maximum concurrency."""

    start: int = Field(default=20)
    """Starting concurrency (must be within [min, max])."""

    @model_validator(mode="before")
    @classmethod
    def parse_shorthand(cls, data: Any) -> Any:
        # Accept "min-max" or "min-start-max" string shorthand, and clamp the
        # implicit start (= field default of 20) into [min, max] when start is
        # not explicitly provided. Without clamping, AdaptiveConcurrency(min=1, max=15)
        # would fail bounds validation because the default start exceeds max.
        DEFAULT_START = 20

        if isinstance(data, str):
            parts = data.split("-")
            try:
                ints = [int(p) for p in parts]
            except ValueError:
                raise ValueError(
                    f"Invalid AdaptiveConcurrency shorthand {data!r}: "
                    "expected 'min-max' or 'min-start-max'"
                )
            if len(ints) == 2:
                min_val, max_val = ints
                return {
                    "min": min_val,
                    "max": max_val,
                    "start": max(min_val, min(DEFAULT_START, max_val)),
                }
            elif len(ints) == 3:
                return {"min": ints[0], "start": ints[1], "max": ints[2]}
            else:
                raise ValueError(
                    f"Invalid AdaptiveConcurrency shorthand {data!r}: "
                    "expected 'min-max' or 'min-start-max'"
                )

        # struct form: clamp implicit start when min/max are provided but
        # start is not, so AdaptiveConcurrency(min=1, max=15) just works
        if isinstance(data, dict) and "start" not in data:
            min_val = data.get("min", 1)
            max_val = data.get("max", 200)
            if isinstance(min_val, int) and isinstance(max_val, int):
                data = dict(data)
                data["start"] = max(min_val, min(DEFAULT_START, max_val))

        return data

    @model_validator(mode="after")
    def validate_bounds(self) -> "AdaptiveConcurrency":
        if self.min < 1:
            raise ValueError(f"AdaptiveConcurrency min must be >= 1 (got {self.min})")
        if self.max < self.min:
            raise ValueError(
                f"AdaptiveConcurrency max ({self.max}) must be >= min ({self.min})"
            )
        if self.start < self.min or self.start > self.max:
            raise ValueError(
                f"AdaptiveConcurrency start ({self.start}) must be within "
                f"[min={self.min}, max={self.max}]"
            )
        return self


class ConcurrencySemaphore(Protocol):
    """Protocol for concurrency semaphores."""

    name: str
    concurrency: int
    semaphore: contextlib.AbstractAsyncContextManager[Any]
    visible: bool

    @property
    def value(self) -> int:
        """Return the number of available tokens in the semaphore."""
        ...


class ConcurrencySemaphoreRegistry(Protocol):
    """Protocol for managing a registry of concurrency semaphores.

    This abstraction allows plugging in different storage strategies
    (e.g., local dict vs cross-process shared storage).
    """

    async def get_or_create(
        self,
        name: str,
        concurrency: int,
        key: str | None,
        visible: bool,
        adaptive: AdaptiveConcurrency | None = None,
    ) -> ConcurrencySemaphore:
        """Get existing semaphore or create a new one.

        Args:
            name: Display name for the semaphore
            concurrency: Maximum concurrent holders (ignored when adaptive is set)
            key: Unique key for storage (defaults to name if None)
            visible: Whether visible in status display
            adaptive: Adaptive bounds (when set, creates an
                AdaptiveConcurrencyController instead of a fixed Semaphore)

        Returns:
            The semaphore instance
        """
        ...

    def values(self) -> Iterable[ConcurrencySemaphore]:
        """Return all registered semaphores for status display."""
        ...


async def get_or_create_semaphore(
    name: str,
    concurrency: int,
    key: str | None,
    visible: bool,
    adaptive: AdaptiveConcurrency | None = None,
) -> ConcurrencySemaphore:
    """Get or create a concurrency semaphore.

    Delegates to the global _concurrency_registry.
    """
    return await _concurrency_registry.get_or_create(
        name, concurrency, key, visible, adaptive
    )


@contextlib.asynccontextmanager
async def concurrency(
    name: str,
    concurrency: int,
    key: str | None = None,
    visible: bool = True,
    adaptive: AdaptiveConcurrency | None = None,
) -> AsyncIterator[ConcurrencySemaphore]:
    """Concurrency context manager.

    A concurrency context can be used to limit the number of coroutines
    executing a block of code (e.g calling an API). For example, here
    we limit concurrent calls to an api ('api-name') to 10:

    ```python
    async with concurrency("api-name", 10):
        # call the api
    ```

    Note that concurrency for model API access is handled internally
    via the `max_connections` generation config option. Concurrency
    for launching subprocesses is handled via the `subprocess` function.

    Args:
      name: Name for concurrency context. This serves as the
         display name for the context, and also the unique context
         key (if the `key` parameter is omitted)
      concurrency: Maximum number of coroutines that can
         enter the context (ignored if `adaptive` is set).
      key: Unique context key for this context. Optional.
         Used if the unique key isn't human readable -- e.g. includes
         api tokens or account ids so that the more readable `name`
         can be presented to users e.g in console UI>
      visible: Should context utilization be visible in the status bar.
      adaptive: When set, creates an adaptive controller managing a
         CapacityLimiter that scales between `adaptive.min` and
         `adaptive.max` based on retry feedback.
    """
    # sort out key
    key = key if key else name

    # do we have an existing semaphore? if not create one and store it
    semaphore = await get_or_create_semaphore(name, concurrency, key, visible, adaptive)

    # wait and yield to protected code (sample_waiting_for tracks concurrent waits
    # to avoid double-counting overlapping wait times within a sample)
    async with sample_waiting_for(semaphore.semaphore):
        yield semaphore


def concurrency_status_display() -> dict[str, tuple[int, int]]:
    status: dict[str, tuple[int, int]] = {}
    semaphores = list(_concurrency_registry.values())
    names = [c.name for c in semaphores]
    for c in semaphores:
        # respect visibility
        if not c.visible:
            continue

        # compute name for status display. some resources (e.g. models) use
        # a / prefix. if there are no duplicates of a given prefix then shorten
        # it to be only the prefix (e.g. 'openai' rather than 'openai/gpt-4o')
        prefix = c.name.split("/")[0]
        prefix_count = sum([1 for name in names if name.startswith(prefix + "/")])
        if prefix_count == 1:
            name = prefix
        else:
            name = c.name

        # status display entry
        status[name] = (c.concurrency - c.value, c.concurrency)

    return status


def init_concurrency(
    registry: ConcurrencySemaphoreRegistry | None = None,
) -> None:
    """Initialize the concurrency system with a custom registry.

    Args:
        registry: A ConcurrencySemaphoreRegistry instance, or None for default local registry.
    """
    global _concurrency_registry
    _concurrency_registry = _AnyIOSemaphoreRegistry() if registry is None else registry
    # clear controller-creation observers so each eval starts fresh
    _controller_created_observers.clear()


class _AnyIOSemaphoreRegistry:
    """Default local semaphore registry using anyio.Semaphore."""

    def __init__(self) -> None:
        self._semaphores: dict[str, ConcurrencySemaphore] = {}

    async def get_or_create(
        self,
        name: str,
        concurrency: int,
        key: str | None,
        visible: bool,
        adaptive: AdaptiveConcurrency | None = None,
    ) -> ConcurrencySemaphore:
        # Adaptive and static modes get separate storage entries even when they
        # share the same caller-provided `key`. Otherwise: (a) a static call
        # followed by an adaptive call would return the existing Semaphore but
        # the caller's `assert isinstance(..., AdaptiveConcurrencyController)`
        # would fail, and (b) an adaptive call followed by a static call would
        # silently get the AdaptiveConcurrencyController, defeating the
        # "explicit max_connections wins" precedence rule.
        base = key if key else name
        k = f"{base}#adaptive" if adaptive is not None else f"{base}#static"
        if k in self._semaphores:
            return self._semaphores[k]

        sem: ConcurrencySemaphore
        if adaptive is not None:
            ctrl = AdaptiveConcurrencyController(name, adaptive, visible)
            self._semaphores[k] = ctrl
            _fire_controller_created(ctrl)
            return ctrl
        sem = _create_anyio_semaphore(name, concurrency, visible)
        self._semaphores[k] = sem
        return sem

    def values(self) -> Iterable[ConcurrencySemaphore]:
        return self._semaphores.values()


def _create_anyio_semaphore(
    name: str, concurrency: int, visible: bool
) -> ConcurrencySemaphore:
    """Create a local ConcurrencySemaphore using anyio.Semaphore."""

    class _ConcurrencySemaphore(ConcurrencySemaphore):
        def __init__(self, name: str, concurrency: int, visible: bool) -> None:
            self.name = name
            self.concurrency = concurrency
            self.visible = visible
            self._sem = anyio.Semaphore(concurrency)
            self.semaphore: contextlib.AbstractAsyncContextManager[Any] = self._sem

        @property
        def value(self) -> int:
            return self._sem.value

    return _ConcurrencySemaphore(name, concurrency, visible)


# Global registry instance
_concurrency_registry: ConcurrencySemaphoreRegistry = _AnyIOSemaphoreRegistry()


# Module-level observer list invoked when a new AdaptiveConcurrencyController is
# created by the registry. DynamicSampleLimiter uses this so it can subscribe to
# every controller eagerly — including ones born mid-eval (graders, etc.).
_controller_created_observers: list[
    "Callable[[AdaptiveConcurrencyController], None]"
] = []


def add_controller_created_observer(
    callback: "Callable[[AdaptiveConcurrencyController], None]",
) -> None:
    """Register a callback fired when a new AdaptiveConcurrencyController is created."""
    _controller_created_observers.append(callback)


def _fire_controller_created(ctrl: "AdaptiveConcurrencyController") -> None:
    for obs in list(_controller_created_observers):
        obs(ctrl)


# ContextVars for adaptive concurrency controller signal flow.
# Set by Model._connection_concurrency at the start of a generate call,
# read by report_http_retry() and by the post-generate success notification.
_active_controller: ContextVar["AdaptiveConcurrencyController | None"] = ContextVar(
    "_active_controller", default=None
)
_request_had_retry: ContextVar[bool] = ContextVar("_request_had_retry", default=False)

# Set to True when a generate() returns from the cache without making an actual
# provider call. Cache hits are neutral for the adaptive controller — they
# neither succeeded nor failed against the rate limit.
_request_was_cache_hit: ContextVar[bool] = ContextVar(
    "_request_was_cache_hit", default=False
)


# Internal tuple record of a single scale change held by AdaptiveConcurrencyController.
# The second element is the controller's display name (e.g. "openai/gpt-4o"),
# never the secret-bearing connection_key from the provider.
LimitChangeRecord = tuple[float, str, int, int, str]
"""(timestamp, model_name, old_limit, new_limit, reason)."""


class AdaptiveConcurrencyController:
    """Adaptive concurrency controller using anyio.CapacityLimiter.

    Implements slow-start + AIMD based on retry signals:
      * notify_success(): one logical request completed without retries
      * notify_retry(): a rate-limit / transient error retry occurred

    Tuning constants:
      * DECREASE_FACTOR (0.8): multiplicative decrease on retry episode
      * COOLDOWN_SECONDS (15): debounce between scale-down events
      * ROUND_SIZE_FLOOR (4): minimum successes before evaluating scale-up
      * SCALE_UP_PERCENT (0.05): steady-state additive increase as % of current
    """

    DECREASE_FACTOR = 0.8
    COOLDOWN_SECONDS = 15.0
    ROUND_SIZE_FLOOR = 4
    SCALE_UP_PERCENT = 0.05
    HISTORY_LIMIT = 200

    def __init__(
        self,
        name: str,
        config: AdaptiveConcurrency,
        visible: bool,
    ) -> None:
        self.name = name
        self._config = config
        self.visible = visible
        self._limiter = anyio.CapacityLimiter(config.start)
        self.semaphore: contextlib.AbstractAsyncContextManager[Any] = self._limiter
        # `concurrency` mirrors the limiter's `total_tokens` (kept in sync via
        # _set_limit). It's a plain attribute to satisfy the ConcurrencySemaphore
        # Protocol (which expects a settable int).
        self.concurrency: int = config.start
        self._success_count = 0
        self._first_retry_seen = False
        self._cooldown_until = 0.0
        self._history: list[LimitChangeRecord] = []
        # observers notified on each scale change as (old_limit, new_limit)
        self._observers: list[Callable[[int, int], None]] = []

    def add_observer(self, callback: Callable[[int, int], None]) -> None:
        """Register a callback fired on each scale change as (old_limit, new_limit)."""
        self._observers.append(callback)

    @property
    def value(self) -> int:
        """Tokens currently available (== limit - borrowed).

        Status display computes `concurrency - value` to show borrowed count,
        matching the Semaphore-based path.
        """
        return int(self._limiter.total_tokens - self._limiter.borrowed_tokens)

    @property
    def history(self) -> list[LimitChangeRecord]:
        """Bounded history of scale changes for eval log capture."""
        return list(self._history)

    def notify_success(self) -> None:
        """Record a successful logical request (no retries occurred).

        Successful-after-retry calls are treated as neutral by the caller
        (which checks `_request_had_retry` before calling here).
        """
        # During the retry cooldown, suppress success accounting entirely.
        # Successes arriving during cooldown were almost certainly in flight
        # from before the rate-limit cut, so they tell us nothing about whether
        # the new lower limit is sustainable. Counting them would let
        # back-pressure evaporate immediately after a cut (e.g. a cut from 100
        # to 80 followed by 80 in-flight clean completions could trigger
        # steady_state_up to 85 inside the cooldown window).
        if time.monotonic() < self._cooldown_until:
            return

        self._success_count += 1
        old = self.concurrency
        round_size = max(old, self.ROUND_SIZE_FLOOR)
        if self._success_count < round_size:
            return

        self._success_count = 0
        if not self._first_retry_seen:
            new = min(old * 2, self._config.max)
            reason = "slow_start"
        else:
            increment = max(1, round(old * self.SCALE_UP_PERCENT))
            new = min(_ceil_to_nice(old + increment), self._config.max)
            reason = "steady_state_up"
        if new != old:
            self._set_limit(new, reason)

    def notify_retry(self) -> None:
        """Record a retry signal (rate-limit or transient error).

        Cooldown debounces the *limit cut* — a single rate-limit episode
        produces multiple retries (Inspect-level + SDK-internal) and we
        cut at most once per episode. But success-counting is reset on
        every retry signal regardless of cooldown, so a debounced retry
        still invalidates the in-progress clean window. Without this,
        under high throughput the controller could climb to a scale-up
        immediately after a suppressed retry.
        """
        # always reset success accounting on any retry signal (even debounced)
        self._success_count = 0
        self._first_retry_seen = True

        # debounce the limit cut itself
        now = time.monotonic()
        if now < self._cooldown_until:
            return

        old = self.concurrency
        target = int(old * self.DECREASE_FACTOR)
        new = _floor_to_nice(target)
        new = max(new, self._config.min, 1)
        self._cooldown_until = now + self.COOLDOWN_SECONDS
        if new != old:
            self._set_limit(new, "rate_limit")

    def _set_limit(self, new: int, reason: str) -> None:
        old = self.concurrency
        self._limiter.total_tokens = new
        self.concurrency = new
        entry: LimitChangeRecord = (time.time(), self.name, old, new, reason)
        self._history.append(entry)
        if len(self._history) > self.HISTORY_LIMIT:
            self._history.pop(0)
        logger.log(
            HTTP,
            f"[connections] {self.name} {old} -> {new} ({reason})",
            extra={
                "model": self.name,
                "old_limit": old,
                "new_limit": new,
                "reason": reason,
            },
        )
        # notify observers (copy list to tolerate mutation during iteration)
        for obs in list(self._observers):
            obs(old, new)


def _ceil_to_nice(value: int) -> int:
    """Smallest 'nice' integer >= value: multiples of 5 above 10, integers below."""
    if value < 10:
        return max(1, value)
    return ((value + 4) // 5) * 5


def _floor_to_nice(value: int) -> int:
    """Largest 'nice' integer <= value: multiples of 5 above 10, integers below."""
    if value < 10:
        return max(1, value)
    return (value // 5) * 5


def adaptive_controllers() -> list[AdaptiveConcurrencyController]:
    """All currently-registered adaptive controllers (for eval log capture)."""
    return [
        c
        for c in _concurrency_registry.values()
        if isinstance(c, AdaptiveConcurrencyController)
    ]


class DynamicSampleLimiter:
    """Sample-concurrency limiter that tracks adaptive controllers' current limits.

    Wraps an `anyio.CapacityLimiter`. Subscribes to every adaptive controller
    eagerly — both ones existing at construction time and ones created later
    (via the module-level controller-creation hook). On each controller scale
    change, `total_tokens` is updated to `max(c.concurrency for c in ctrls) + BUFFER`,
    so sample concurrency tracks model API concurrency (plus a small slack).
    """

    BUFFER = 5

    def __init__(self, adaptive: AdaptiveConcurrency) -> None:
        self._adaptive = adaptive
        initial = min(adaptive.start, adaptive.max) + self.BUFFER
        self._limiter = anyio.CapacityLimiter(initial)
        # subscribe to existing controllers (e.g. when the registry is reused
        # across tasks within an eval set)
        existing = list(adaptive_controllers())
        for ctrl in existing:
            ctrl.add_observer(self._on_controller_change)
        # catch up to existing controllers' current limits — without this, a
        # limiter created after a controller has already scaled would sit at
        # `start + BUFFER` until the next scale change
        if existing:
            self._on_controller_change(0, 0)  # args ignored; recomputes from controllers
        # register for future controllers — fired by the registry on creation
        add_controller_created_observer(self._on_controller_created)

    def _on_controller_created(self, ctrl: AdaptiveConcurrencyController) -> None:
        ctrl.add_observer(self._on_controller_change)
        # catch up: recompute target including this fresh controller
        self._on_controller_change(0, ctrl.concurrency)

    def _on_controller_change(self, old: int, new: int) -> None:
        ctrls = list(adaptive_controllers())
        if not ctrls:
            return
        max_cc = max(c.concurrency for c in ctrls)
        target = min(max_cc + self.BUFFER, self._adaptive.max + self.BUFFER)
        if target != self._limiter.total_tokens:
            self._limiter.total_tokens = target

    @property
    def total_tokens(self) -> int:
        """Current capacity (for tests / introspection)."""
        return int(self._limiter.total_tokens)

    async def __aenter__(self) -> None:
        await self._limiter.__aenter__()

    async def __aexit__(self, *args: Any) -> Any:
        return await self._limiter.__aexit__(*args)
