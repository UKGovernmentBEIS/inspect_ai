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


_DEFAULT_MIN = 10
_DEFAULT_START = 20
_DEFAULT_MAX = 100


class AdaptiveConcurrency(BaseModel):
    """Bounds and tuning for an adaptive concurrency controller.

    Basic fields (`min`, `start`, `max`) bound the range the controller will
    scale within. Advanced fields (`cooldown_seconds`, `decrease_factor`,
    `scale_up_percent`) tune the response curve and have sensible defaults
    for typical evaluation workloads — see the parallelism docs for guidance.
    Accepts a string shorthand ("min-max" or "min-start-max") for use in CLI
    flags and config files; advanced fields are Python-only.
    """

    min: int = Field(default=_DEFAULT_MIN)
    """Minimum concurrency (must be >= 1)."""

    max: int = Field(default=_DEFAULT_MAX)
    """Maximum concurrency."""

    start: int = Field(default=_DEFAULT_START)
    """Starting concurrency (must be within [min, max])."""

    cooldown_seconds: float = Field(default=15.0)
    """Minimum seconds between scale-down cuts. The server's `Retry-After` header (or the `x-ratelimit-reset-*` family as a fallback) extends this when larger."""

    decrease_factor: float = Field(default=0.8)
    """Multiplicative cut applied on each rate-limit episode (must be in (0, 1))."""

    scale_up_percent: float = Field(default=0.05)
    """Steady-state additive growth per clean round, as a fraction of current limit (must be in (0, 1])."""

    @model_validator(mode="before")
    @classmethod
    def parse_shorthand(cls, data: Any) -> Any:
        # Accept "min-max" or "min-start-max" string shorthand, and clamp the
        # implicit start (= field default) into [min, max] when start is not
        # explicitly provided. Without clamping, AdaptiveConcurrency(min=1, max=15)
        # would fail bounds validation because the default start exceeds max.
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
                    "start": max(min_val, min(_DEFAULT_START, max_val)),
                }
            elif len(ints) == 3:
                return {"min": ints[0], "start": ints[1], "max": ints[2]}
            else:
                raise ValueError(
                    f"Invalid AdaptiveConcurrency shorthand {data!r}: "
                    "expected 'min-max' or 'min-start-max'"
                )

        # struct form: clamp implicit min/start when max is provided but they
        # are not, so AdaptiveConcurrency(max=8) and AdaptiveConcurrency(min=1,
        # max=15) just work without bounds-validation errors from the defaults
        if isinstance(data, dict):
            max_val = data.get("max", _DEFAULT_MAX)
            if (
                "min" not in data
                and isinstance(max_val, int)
                and max_val < _DEFAULT_MIN
            ):
                data = dict(data)
                data["min"] = max_val
            if "start" not in data:
                min_val = data.get("min", _DEFAULT_MIN)
                if isinstance(min_val, int) and isinstance(max_val, int):
                    data = dict(data)
                    data["start"] = max(min_val, min(_DEFAULT_START, max_val))

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
        if self.cooldown_seconds < 0:
            raise ValueError(
                f"AdaptiveConcurrency cooldown_seconds must be >= 0 "
                f"(got {self.cooldown_seconds})"
            )
        if not (0 < self.decrease_factor < 1):
            raise ValueError(
                f"AdaptiveConcurrency decrease_factor must be in (0, 1) "
                f"(got {self.decrease_factor})"
            )
        if not (0 < self.scale_up_percent <= 1):
            raise ValueError(
                f"AdaptiveConcurrency scale_up_percent must be in (0, 1] "
                f"(got {self.scale_up_percent})"
            )
        return self


def adaptive_active(
    adaptive_connections: bool | int | AdaptiveConcurrency | None,
    max_connections: int | None,
    batch: Any,
) -> bool:
    """True if adaptive concurrency will be the resolved strategy.

    The same predicate is used by `Model._connection_concurrency`,
    `create_sample_semaphore`, and `eval_set`'s adaptive-active check.
    `False` is the explicit opt-out; `None`, `True`, an integer (max
    shorthand), and a full `AdaptiveConcurrency` all enable adaptive.
    Explicit `max_connections` and `batch=True` (or a `BatchConfig`)
    silently take precedence — see `Model._connection_concurrency` for
    the rationale.
    """
    return adaptive_connections is not False and max_connections is None and not batch


def resolve_adaptive(
    value: bool | int | AdaptiveConcurrency | None,
) -> AdaptiveConcurrency:
    """Resolve a config value to a concrete `AdaptiveConcurrency`.

    Caller must have first verified `adaptive_active(value, ...)` is True
    (i.e. `value is not False`). Note: `bool` is a subclass of `int` in
    Python, so the bool/None branch must precede the int branch.
    """
    if isinstance(value, AdaptiveConcurrency):
        return value
    if isinstance(value, bool) or value is None:  # True / None → defaults
        return AdaptiveConcurrency()
    if isinstance(value, int):
        return AdaptiveConcurrency(max=value)
    raise TypeError(f"unexpected adaptive_connections value: {value!r}")


class ResizableLimiter:
    """An async context-manager concurrency limiter whose limit can change live.

    Backed by ``anyio.CapacityLimiter`` (the same primitive the adaptive
    controller and ``DynamicSampleLimiter`` use), so the limit is settable
    mid-flight: lowering it below the current in-use count blocks new acquires
    until enough holders release — it never preempts an in-flight holder. This
    is the resizable counterpart to the static ``anyio.Semaphore`` path, used
    where a limit must be adjustable through the control channel (``max_samples``
    and ``max_sandboxes`` today — see ``design/control-channel.md`` phase 3).

    Used directly as an async context manager (``async with limiter:``), exactly
    as the static sample semaphore was, so it drops into the existing acquire
    sites unchanged.
    """

    def __init__(self, limit: int) -> None:
        self._limiter = anyio.CapacityLimiter(limit)

    @property
    def limit(self) -> int:
        """Current maximum number of concurrent holders."""
        return int(self._limiter.total_tokens)

    @limit.setter
    def limit(self, value: int) -> None:
        # CapacityLimiter requires total_tokens >= 1; callers validate, but
        # guard here too so a stray 0/negative can't wedge the limiter.
        if value < 1:
            raise ValueError(f"ResizableLimiter limit must be >= 1 (got {value})")
        self._limiter.total_tokens = value

    @property
    def in_use(self) -> int:
        """Holders currently inside the limiter (borrowed tokens)."""
        return int(self._limiter.borrowed_tokens)

    @property
    def available(self) -> int:
        """Free capacity (``limit - in_use``), clamped to >= 0.

        Clamped because :attr:`limit` may be lowered below the current in-use
        count (CapacityLimiter accepts this and blocks new acquires until
        in-flight drains); without the clamp this would go negative.
        """
        return max(0, self.limit - self.in_use)

    async def __aenter__(self) -> None:
        await self._limiter.__aenter__()

    async def __aexit__(self, *args: Any) -> Any:
        return await self._limiter.__aexit__(*args)


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
        resizable: bool = False,
    ) -> ConcurrencySemaphore:
        """Get existing semaphore or create a new one.

        Args:
            name: Display name for the semaphore
            concurrency: Maximum concurrent holders (ignored when adaptive is set)
            key: Unique key for storage (defaults to name if None)
            visible: Whether visible in status display
            adaptive: Adaptive bounds (when set, creates an
                AdaptiveConcurrencyController instead of a fixed Semaphore)
            resizable: When set (and ``adaptive`` is not), back the semaphore
                with a :class:`ResizableLimiter` whose limit can be changed
                mid-flight (via the control channel) instead of a fixed
                ``anyio.Semaphore``.

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
    resizable: bool = False,
) -> ConcurrencySemaphore:
    """Get or create a concurrency semaphore.

    Delegates to the global _concurrency_registry.
    """
    # Pass the extra kwargs only when they diverge from the default, so a custom
    # (pre-adaptive / pre-resizable) registry that implements the older, narrower
    # `get_or_create` signature keeps working for the common static path — the
    # same back-compat courtesy the `adaptive` argument already gets.
    if adaptive is not None:
        return await _concurrency_registry.get_or_create(
            name, concurrency, key, visible, adaptive
        )
    if resizable:
        return await _concurrency_registry.get_or_create(
            name, concurrency, key, visible, resizable=True
        )
    return await _concurrency_registry.get_or_create(name, concurrency, key, visible)


@contextlib.asynccontextmanager
async def concurrency(
    name: str,
    concurrency: int,
    key: str | None = None,
    visible: bool = True,
    adaptive: AdaptiveConcurrency | None = None,
    resizable: bool = False,
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
      resizable: When set (and `adaptive` is not), back the context with a
         `ResizableLimiter` whose limit can be changed mid-flight (via the
         control channel) rather than a fixed `anyio.Semaphore`.
    """
    # sort out key
    key = key if key else name

    # do we have an existing semaphore? if not create one and store it
    semaphore = await get_or_create_semaphore(
        name, concurrency, key, visible, adaptive, resizable=resizable
    )

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
    # drop any resizable sandbox limiters and per-task sample semaphores tracked
    # for the previous run so a long-lived (keep-alive) process doesn't surface
    # or reuse stale ones
    _sandbox_limiters.clear()
    _task_sample_semaphores.clear()


# ---------------------------------------------------------------------------
# Resizable sandbox limiters
# ---------------------------------------------------------------------------

# The live-resizable sandbox concurrency semaphores for the current run, keyed
# by sandbox type (e.g. "docker"). Populated by `register_sandbox_limiter` via
# `ensure_sandbox_limiter` (see `_eval/task/sandbox.py`) — eagerly at run-level
# sandbox startup, and again (idempotently) when a sample opens its
# `sandboxes/<type>` concurrency context — so the control channel's
# modify-limits directive can read and retune `max_sandboxes` from startup
# onward. Process-global (sandbox concurrency is shared across the process's
# evals, not per-eval) and reset per run by `init_concurrency`.
_sandbox_limiters: "dict[str, ResizableSemaphore]" = {}


def register_sandbox_limiter(
    sandbox_type: str, semaphore: ConcurrencySemaphore
) -> None:
    """Track a sandbox-type's resizable concurrency semaphore for the control channel.

    Idempotent per sandbox type — the first sample of each type registers it and
    later samples (which get the same registry instance) re-register the same
    object. A no-op for a non-resizable semaphore (nothing to retune).
    """
    if isinstance(semaphore, ResizableSemaphore):
        _sandbox_limiters[sandbox_type] = semaphore


def sandbox_limiters() -> "dict[str, ResizableSemaphore]":
    """The resizable sandbox concurrency semaphores for the current run, by type."""
    return dict(_sandbox_limiters)


# ---------------------------------------------------------------------------
# Task sample semaphores
# ---------------------------------------------------------------------------

# The sample-concurrency semaphores for the current run, keyed by task_id (the
# identity that is stable across retry attempts, unlike a per-attempt eval_id).
# Task-scoped so an in-process task retry reuses its predecessor's semaphore:
# a mid-flight `ctl limits --max-samples` retune survives the retry (the
# runtime setpoint wins over re-deriving from config — in-process retries share
# their config anyway), and a retune against a superseded attempt's eval_id
# still reaches the limiter the live attempt drains from. This mirrors how the
# other retunable limits already persist across retries (adaptive controllers
# are keyed by connection pool, sandbox limiters by type). Reset per run by
# `init_concurrency`.
_task_sample_semaphores: "dict[str, ResizableLimiter | DynamicSampleLimiter]" = {}


def task_sample_semaphore(
    task_id: str,
) -> "ResizableLimiter | DynamicSampleLimiter | None":
    """The task's sample semaphore from a prior attempt in this run, if any."""
    return _task_sample_semaphores.get(task_id)


def register_task_sample_semaphore(
    task_id: str, semaphore: "ResizableLimiter | DynamicSampleLimiter"
) -> None:
    """Track a task's sample semaphore for reuse by later retry attempts."""
    _task_sample_semaphores[task_id] = semaphore


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
        resizable: bool = False,
    ) -> ConcurrencySemaphore:
        # Adaptive and static modes get separate storage entries even when they
        # share the same caller-provided `key`. Otherwise: (a) a static call
        # followed by an adaptive call would return the existing Semaphore but
        # the caller's `assert isinstance(..., AdaptiveConcurrencyController)`
        # would fail, and (b) an adaptive call followed by a static call would
        # silently get the AdaptiveConcurrencyController, defeating the
        # "explicit max_connections wins" precedence rule. A resizable request
        # shares the `#static` slot — it's a static (non-adaptive) semaphore
        # whose limit merely happens to be settable — so a plain and a resizable
        # call for the same key coalesce onto the first-created instance.
        base = key if key else name
        k = f"{base}#adaptive" if adaptive is not None else f"{base}#static"
        if k in self._semaphores:
            return self._semaphores[k]

        sem: ConcurrencySemaphore
        if adaptive is not None:
            ctrl = AdaptiveConcurrencyController(name, adaptive, visible, key=base)
            self._semaphores[k] = ctrl
            _fire_controller_created(ctrl)
            return ctrl
        sem = (
            _create_resizable_semaphore(name, concurrency, visible)
            if resizable
            else _create_anyio_semaphore(name, concurrency, visible)
        )
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


class ResizableSemaphore(ConcurrencySemaphore):
    """A ``ConcurrencySemaphore`` whose limit can be changed live.

    Backs a registry entry (``max_sandboxes`` today) with a
    :class:`ResizableLimiter` instead of a fixed ``anyio.Semaphore``, so the
    control channel can retune it mid-eval. ``concurrency`` mirrors the
    limiter's current limit (kept in sync by :meth:`set_concurrency`) to satisfy
    the ``ConcurrencySemaphore`` protocol and the status display, which reads
    ``concurrency - value`` for the in-use count.
    """

    def __init__(self, name: str, concurrency: int, visible: bool) -> None:
        self.name = name
        self.visible = visible
        self._limiter = ResizableLimiter(concurrency)
        self.concurrency = concurrency
        self.semaphore: contextlib.AbstractAsyncContextManager[Any] = self._limiter

    @property
    def value(self) -> int:
        return self._limiter.available

    @property
    def in_use(self) -> int:
        """Exact borrowed count (holders currently inside the limiter).

        Prefer this over the status-display ``concurrency - value`` derivation:
        once the limit is lowered below the in-flight count, ``value`` clamps to
        0 and that derivation would report ``concurrency`` rather than the true
        (higher) borrowed count. This reads ``borrowed_tokens`` directly, so it
        stays exact through a shrink-below-in-use.
        """
        return self._limiter.in_use

    def set_concurrency(self, new: int) -> None:
        """Change the limit live. Lowering below in-use blocks new acquires."""
        self._limiter.limit = new
        self.concurrency = new


def _create_resizable_semaphore(
    name: str, concurrency: int, visible: bool
) -> ConcurrencySemaphore:
    """Create a live-resizable ConcurrencySemaphore (see :class:`ResizableSemaphore`)."""
    return ResizableSemaphore(name, concurrency, visible)


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


class _SaturationTrackingLimiter:
    """Wraps a CapacityLimiter to record peak in-flight count on each acquire.

    Recording on release would undercount: at success-completion time the
    just-borrowed slot has already been returned to the limiter, so
    `borrowed_tokens` reflects only OTHER in-flight requests. At low limits
    (e.g. limit=4 with full saturation), every sample would observe at most
    3 — below the 0.8 saturation threshold — and growth would never trigger.
    Recording on acquire, when the slot is still counted, captures the true
    high-water mark across the round.
    """

    def __init__(self, controller: "AdaptiveConcurrencyController") -> None:
        self._controller = controller

    async def __aenter__(self) -> None:
        c = self._controller
        await c._limiter.acquire()
        # Skip the saturation update during a post-cut cooldown. notify_retry
        # already reset the mark to 0; in-flight acquires arriving while the
        # cooldown is active are pre-cut traffic at the new (lower) limit, so
        # they're not relevant evidence for the next round's growth decision.
        # Without this gate, the first post-cooldown round can pass the 0.8
        # saturation threshold from peaks observed during cooldown alone.
        if time.monotonic() >= c._cooldown_until:
            borrowed = int(c._limiter.borrowed_tokens)
            if borrowed > c._max_borrowed_this_round:
                c._max_borrowed_this_round = borrowed

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._controller._limiter.release()


class AdaptiveConcurrencyController:
    """Adaptive concurrency controller using anyio.CapacityLimiter.

    Implements slow-start + AIMD based on retry signals. Only rate-limit
    retries scale down — provider 5xx and network blips pause scale-up
    (the in-flight success won't count) but don't shrink the limit. See
    `ModelAPI.should_retry()` and the `RetryDecision` it returns for the
    per-provider classification.

    Behavioral tunables come from the `AdaptiveConcurrency` config
    (`cooldown_seconds`, `decrease_factor`, `scale_up_percent`).
    `ROUND_SIZE_FLOOR` and `HISTORY_LIMIT` are internal class constants.
    """

    ROUND_SIZE_FLOOR = 4
    HISTORY_LIMIT = 200
    # Minimum saturation (peak-borrowed / current-limit) within a round
    # required to scale up. Without this gate, the controller would treat any
    # round-sized batch of successes as proof the limit is binding, even when
    # peak in-flight was well below the limit (e.g. running 250 in flight at
    # a 500 cap because the work simply isn't there to fill it). Growing in
    # that case is incorrect: the next time work surges to the new higher
    # limit, we may exceed the provider's actual rate limit since we never
    # validated capacity beyond the peak we actually hit.
    SATURATION_THRESHOLD = 0.8

    def __init__(
        self,
        name: str,
        config: AdaptiveConcurrency,
        visible: bool,
        key: str | None = None,
    ) -> None:
        self.name = name
        # The registry key this controller was created under (the model's
        # connection-pool key) — the identity `DynamicSampleLimiter` uses to
        # follow its own model's controller. `name` is only the display string
        # and can collide across accounts serving the same model. Defaults to
        # `name` for direct construction (tests).
        self.key = key if key is not None else name
        # Private copy: set_max() mutates the bounds, and callers can pass the
        # same AdaptiveConcurrency instance to several controllers (one per
        # model) — sharing it would leak a --model-scoped retune of one
        # controller into the others' ceilings.
        self._config = config.model_copy()
        # The as-configured floor: set_max() clamps `_config.min` down when the
        # ceiling drops below it, and restores it from this snapshot when the
        # ceiling is raised again.
        self._configured_min = config.min
        self.visible = visible
        self._limiter = anyio.CapacityLimiter(config.start)
        # `concurrency` mirrors the limiter's `total_tokens` (kept in sync via
        # _set_limit). It's a plain attribute to satisfy the ConcurrencySemaphore
        # Protocol (which expects a settable int).
        self.concurrency: int = config.start
        self._success_count = 0
        # high-water mark of in-flight (borrowed) requests within the current
        # round; reset at end of round and on rate-limit cut. Updated on each
        # acquire via the wrapping context manager below — sampling on acquire
        # captures the just-borrowed slot, where sampling on release would
        # undercount by one (and at low limits like 4, every sample would
        # observe peak=3, blocking growth even under full saturation).
        self._max_borrowed_this_round = 0
        # Wrap the underlying limiter so each acquire records its borrowed
        # count toward the round's high-water mark.
        self.semaphore: contextlib.AbstractAsyncContextManager[Any] = (
            _SaturationTrackingLimiter(self)
        )
        self._first_retry_seen = False
        self._cooldown_until = 0.0
        self._history: list[LimitChangeRecord] = []
        # observers notified on each scale change (no args — observers read the
        # controller's live state; old/new values are in `history` if needed)
        self._observers: list[Callable[[], None]] = []

    def add_observer(self, callback: Callable[[], None]) -> None:
        """Register a callback fired on each scale change."""
        self._observers.append(callback)

    @property
    def value(self) -> int:
        """Tokens currently available (== limit - borrowed), clamped to >= 0.

        Status display computes `concurrency - value` to show borrowed count,
        matching the Semaphore-based path. Clamped because `notify_retry` may
        lower `total_tokens` below current `borrowed_tokens` (CapacityLimiter
        accepts this and blocks new acquires until in-flight drains); without
        the clamp, `value` would go negative and the status display would
        render in-flight as exceeding the cap.
        """
        return max(0, int(self._limiter.total_tokens - self._limiter.borrowed_tokens))

    @property
    def in_use(self) -> int:
        """Exact borrowed count (requests currently in flight under this limit).

        Reads `borrowed_tokens` directly rather than deriving `concurrency -
        value`: after a rate-limit cut lowers the limit below the in-flight
        count, `value` clamps to 0 and the derivation would under-report the
        true (higher) borrowed count. See :attr:`value`.
        """
        return int(self._limiter.borrowed_tokens)

    @property
    def min(self) -> int:
        """The controller's lower scaling bound (`AdaptiveConcurrency.min`)."""
        return self._config.min

    @property
    def max(self) -> int:
        """The controller's upper scaling bound (`AdaptiveConcurrency.max`)."""
        return self._config.max

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

        # `_max_borrowed_this_round` is updated on each acquire via the
        # _SaturationTrackingLimiter wrapper — no need to sample here.

        self._success_count += 1
        old = self.concurrency
        round_size = max(old, self.ROUND_SIZE_FLOOR)
        if self._success_count < round_size:
            return

        # End of round. Only scale up if we observed real saturation —
        # otherwise the current limit isn't binding, and growing it gives us
        # untested headroom that may exceed the provider's actual rate limit
        # the next time work surges enough to fill it.
        peak_borrowed = self._max_borrowed_this_round
        self._max_borrowed_this_round = 0
        self._success_count = 0
        if old > 0 and peak_borrowed < self.SATURATION_THRESHOLD * old:
            return

        if not self._first_retry_seen:
            new = min(old * 2, self._config.max)
            reason = "slow_start"
        else:
            increment = max(1, round(old * self._config.scale_up_percent))
            new = min(_ceil_to_nice(old + increment), self._config.max)
            reason = "steady_state_up"
        if new != old:
            self._set_limit(new, reason)

    def notify_retry(self, retry_after: float | None = None) -> None:
        """Record a rate-limit retry signal.

        Only called for retries the provider classifies as rate-limit
        (HTTP 429 or provider-specific equivalents like Bedrock
        `ThrottlingException` or Google `503 RESOURCE_EXHAUSTED`).
        Other retries don't reach this method.

        Cooldown debounces the *limit cut* — a single rate-limit episode
        produces multiple retries (Inspect-level + SDK-internal) and we
        cut at most once per episode. Success-counting is reset on every
        call regardless of cooldown, so a debounced retry still
        invalidates the in-progress clean window — without this, under
        high throughput the controller could climb to a scale-up
        immediately after a suppressed retry.

        If `retry_after` is provided (from the server's `Retry-After`
        header or the `x-ratelimit-reset-*` fallback), the cooldown is
        extended to honor it when larger than the configured floor.
        """
        # always reset success accounting on any retry signal (even debounced).
        # Also reset the saturation high-water mark — peak in-flight observed
        # before the cut is no longer relevant evidence at the new (lower) limit.
        self._success_count = 0
        self._max_borrowed_this_round = 0
        self._first_retry_seen = True

        now = time.monotonic()

        # already in cooldown from a previous cut?
        if now < self._cooldown_until:
            # don't cut again — but a longer server hint should still push
            # the cooldown horizon out so a subsequent 429 within the same
            # window can't trip a second cut, and so success-counting stays
            # suppressed for the full server-recommended wait.
            if retry_after is not None and retry_after > 0:
                extended = now + retry_after
                if extended > self._cooldown_until:
                    self._cooldown_until = extended
            return

        old = self.concurrency
        target = int(old * self._config.decrease_factor)
        new = _floor_to_nice(target)
        new = max(new, self._config.min, 1)
        cooldown = max(retry_after or 0.0, self._config.cooldown_seconds)
        self._cooldown_until = now + cooldown
        if new != old:
            self._set_limit(new, "rate_limit")

    def set_max(self, new_max: int) -> None:
        """Retune the controller's scaling ceiling (``max``) mid-flight.

        The control channel's modify-limits directive uses this to throttle (or
        lift the throttle on) adaptive connections without disabling adaptation.

        Lowering below the current limit clamps the live limit down to the new
        ceiling immediately — blocking new acquires until in-flight requests
        drain, never preempting one — and caps subsequent AIMD growth. Raising
        lifts the ceiling so later clean rounds can grow past the old ``max``;
        the current limit is left untouched (the controller climbs on its own).
        ``min`` follows as ``min(configured_min, new_max)``: pulled down when
        the ceiling drops below the configured floor (preserving ``min <= max``)
        and restored to that floor when the ceiling is raised again — a
        temporary throttle must not permanently weaken the floor that
        rate-limit cuts clamp to.

        Caller is responsible for ``new_max >= 1`` (the route/CLI validate it).
        """
        self._config.max = new_max
        self._config.min = min(self._configured_min, new_max)
        # Only the clamp-down changes the live limit; `_set_limit` records the
        # change and notifies observers (so `DynamicSampleLimiter` follows). On a
        # raise there's nothing to recompute yet — the sample limiter tracks the
        # controller's *current* limit, which hasn't moved.
        if self.concurrency > new_max:
            self._set_limit(new_max, "manual")

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
            obs()


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
    """Sample-concurrency limiter that tracks its model's adaptive controller.

    Wraps an `anyio.CapacityLimiter`. Subscribes to the adaptive controller
    created under ``key`` (the model's connection-pool key, see
    `model_concurrency_key`) — whether it exists at construction time (e.g.
    when the registry is reused across tasks within an eval set) or appears
    later via the module-level controller-creation hook (the controller is
    usually created on the model's first generate, after this limiter is
    built). On each scale change, `total_tokens` is updated to the matching
    controller's `concurrency + BUFFER`, so sample concurrency tracks the
    model's live API concurrency (plus a small slack) — including a mid-flight
    `set_max` retune of the ceiling.

    Controllers for *other* models in the process (graders, eval-set sibling
    tasks — or the same model on a different account) are deliberately
    ignored: their — possibly much higher — limits say nothing about this
    task's model, and following the busiest controller in the process would
    start far more samples than this model can serve. The registry coalesces
    on key, so at most one controller ever matches; a ``key`` that never
    matches (no such model in this process) leaves the limiter at its initial
    ``start + BUFFER``.
    """

    BUFFER = 5

    def __init__(self, adaptive: AdaptiveConcurrency, key: str) -> None:
        self._key = key
        self._ctrl: AdaptiveConcurrencyController | None = None
        initial = min(adaptive.start, adaptive.max) + self.BUFFER
        self._limiter = anyio.CapacityLimiter(initial)
        # adopt the controller if it already exists (e.g. registry reused
        # across tasks within an eval set)...
        existing = next((c for c in adaptive_controllers() if c.key == key), None)
        if existing is not None:
            self._adopt(existing)
        # ...or when the registry creates it later (usually on the model's
        # first generate, after this limiter is built)
        add_controller_created_observer(self._on_controller_created)

    def _adopt(self, ctrl: AdaptiveConcurrencyController) -> None:
        """Follow ``ctrl``: hold it, subscribe, and catch up to its limit.

        The registry coalesces on key, so at most one controller ever exists
        for ``self._key`` — held directly rather than looked up on each change.
        Catching up matters for the already-existing case: without it, a
        limiter created after the controller has scaled would sit at
        ``start + BUFFER`` until the next scale change.
        """
        self._ctrl = ctrl
        ctrl.add_observer(self._on_controller_change)
        self._on_controller_change()

    def _on_controller_created(self, ctrl: AdaptiveConcurrencyController) -> None:
        if ctrl.key == self._key:
            self._adopt(ctrl)

    def _on_controller_change(self) -> None:
        if self._ctrl is None:
            return
        # Track the controller's current limit plus a little slack. Reading the
        # live controller (rather than a snapshot of its config) means a
        # mid-flight `set_max` raise isn't silently clamped by a stale cap; the
        # key scoping keeps another model's higher ceiling from standing in
        # for this one's.
        target = self._ctrl.concurrency + self.BUFFER
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
