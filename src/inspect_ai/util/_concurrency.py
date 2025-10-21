import contextlib
import time
from collections.abc import Iterable
from typing import Any, AsyncIterator, Protocol

import anyio

from inspect_ai._util.working import report_sample_waiting_time


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
    ) -> ConcurrencySemaphore:
        """Get existing semaphore or create a new one.

        Args:
            name: Display name for the semaphore
            concurrency: Maximum concurrent holders
            key: Unique key for storage (defaults to name if None)
            visible: Whether visible in status display

        Returns:
            The semaphore instance
        """
        ...

    def values(self) -> Iterable[ConcurrencySemaphore]:
        """Return all registered semaphores for status display."""
        ...


async def get_or_create_semaphore(
    name: str, concurrency: int, key: str | None, visible: bool
) -> ConcurrencySemaphore:
    """Get or create a concurrency semaphore.

    Delegates to the global _concurrency_registry.
    """
    return await _concurrency_registry.get_or_create(name, concurrency, key, visible)


@contextlib.asynccontextmanager
async def concurrency(
    name: str, concurrency: int, key: str | None = None, visible: bool = True
) -> AsyncIterator[None]:
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
         enter the context.
      key: Unique context key for this context. Optional.
         Used if the unique key isn't human readable -- e.g. includes
         api tokens or account ids so that the more readable `name`
         can be presented to users e.g in console UI>
      visible: Should context utilization be visible in the status bar.
    """
    # sort out key
    key = key if key else name

    # do we have an existing semaphore? if not create one and store it
    semaphore = await get_or_create_semaphore(name, concurrency, key, visible)

    # wait and yield to protected code
    start_wait = time.monotonic()
    async with semaphore.semaphore:
        report_sample_waiting_time(time.monotonic() - start_wait)
        yield


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
    ) -> ConcurrencySemaphore:
        k = key if key else name
        if k in self._semaphores:
            return self._semaphores[k]

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
