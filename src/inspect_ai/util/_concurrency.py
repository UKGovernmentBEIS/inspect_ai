import contextlib
import time
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


class ConcurrencySemaphoreFactory(Protocol):
    """Protocol for creating ConcurrencySemaphore instances."""

    async def __call__(
        self, name: str, concurrency: int, visible: bool
    ) -> ConcurrencySemaphore: ...


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
    semaphore = _concurrency_semaphores.get(key, None)
    if semaphore is None:
        semaphore = await _semaphore_factory(name, concurrency, visible)
        _concurrency_semaphores[key] = semaphore

    # wait and yield to protected code
    start_wait = time.monotonic()
    async with semaphore.semaphore:
        report_sample_waiting_time(time.monotonic() - start_wait)
        yield


def concurrency_status_display() -> dict[str, tuple[int, int]]:
    status: dict[str, tuple[int, int]] = {}
    names = [c.name for c in _concurrency_semaphores.values()]
    for c in _concurrency_semaphores.values():
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
    semaphore_factory: ConcurrencySemaphoreFactory | None = None,
) -> None:
    _concurrency_semaphores.clear()
    global _semaphore_factory
    _semaphore_factory = (
        semaphore_factory if semaphore_factory else _anyio_semaphore_factory
    )


_concurrency_semaphores: dict[str, ConcurrencySemaphore] = {}


async def _anyio_semaphore_factory(
    name: str, concurrency: int, visible: bool
) -> ConcurrencySemaphore:
    """Default factory for creating ConcurrencySemaphore instances."""

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


_semaphore_factory: ConcurrencySemaphoreFactory = _anyio_semaphore_factory
