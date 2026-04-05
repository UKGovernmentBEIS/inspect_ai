import time
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import anyio

from inspect_ai._util._async import current_async_backend
from inspect_ai._util.background import background_task_group, run_in_background

P = ParamSpec("P")
R = TypeVar("R")


def throttle(seconds: float) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Throttle a function with trailing-edge semantics.

    When calls arrive faster than the throttle window:
    - The first call fires immediately (no previous window to trail from).
    - Subsequent calls within the window are saved, not fired.
    - When the window expires, the most recently saved call fires.
    - The call that triggers the window expiry does NOT fire immediately;
      instead it becomes the new pending call for the next window while
      the previously pending call fires.

    After an idle period (no calls for >= window), the next call fires
    immediately since there is no pending call to trail.

    The return value is always the result of the most recent actual invocation.
    When a call is throttled (not fired), the previous invocation's result is
    returned.

    Behavior depends on whether an async context is active:

    With async context: a background task fires the trailing event after the
    window expires, so pending events are never lost.

    Without async context: pending args are saved but only fire on the next call
    that arrives after the window expires. If no further call is made, the final
    trailing event is lost.

    Args:
       seconds: Throttle window in seconds.

    Returns:
       Decorator that applies trailing-edge throttle.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        last_called: float | None = None
        last_result: R = None  # type: ignore[assignment]
        pending: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        deferred_scheduled: bool = False

        async def _deferred_fire() -> None:
            nonlocal last_called, last_result, pending, deferred_scheduled
            remaining = seconds - (time.time() - (last_called or 0))
            if remaining > 0:
                await anyio.sleep(remaining)
            # Re-check: a synchronous call may have fired and reset state
            # while we slept
            if pending is not None and time.time() - (last_called or 0) >= seconds:
                last_result = func(*pending[0], **pending[1])
                last_called = time.time()
                pending = None
            deferred_scheduled = False

        @wraps(func)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            nonlocal last_called, last_result, pending, deferred_scheduled
            current_time = time.time()

            if last_called is None or current_time - last_called >= seconds:
                # Window expired or first call
                if pending is not None:
                    # Fire trailing from previous window
                    last_result = func(*pending[0], **pending[1])
                    pending = (args, kwargs)
                else:
                    # No pending — fire immediately (idle or first call)
                    last_result = func(*args, **kwargs)
                last_called = current_time
            else:
                # Within window — save as pending
                pending = (args, kwargs)
                if not deferred_scheduled and (
                    background_task_group() is not None
                    or current_async_backend() == "asyncio"
                ):
                    deferred_scheduled = True
                    run_in_background(_deferred_fire)

            return last_result

        return wrapped

    return decorator
