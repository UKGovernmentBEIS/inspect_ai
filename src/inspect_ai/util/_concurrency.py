import contextlib
import time
from dataclasses import dataclass
from typing import AsyncIterator

import anyio

from inspect_ai._util.working import report_sample_waiting_time


@contextlib.asynccontextmanager
async def concurrency(
    name: str,
    concurrency: int,
    key: str | None = None,
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
    """
    # sort out key
    key = key if key else name

    # do we have an existing semaphore? if not create one and store it
    semaphore = _concurrency_semaphores.get(key, None)
    if semaphore is None:
        semaphore = ConcurencySempahore(name, concurrency, anyio.Semaphore(concurrency))
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
        status[name] = (c.concurrency - c.semaphore.value, c.concurrency)

    return status


def init_concurrency() -> None:
    _concurrency_semaphores.clear()


@dataclass
class ConcurencySempahore:
    name: str
    concurrency: int
    semaphore: anyio.Semaphore


_concurrency_semaphores: dict[str, ConcurencySempahore] = {}
