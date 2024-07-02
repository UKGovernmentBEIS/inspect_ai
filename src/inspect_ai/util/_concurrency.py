import asyncio
from contextvars import ContextVar
from dataclasses import dataclass


def concurrency(
    name: str,
    concurrency: int,
    key: str | None = None,
) -> asyncio.Semaphore:
    """Obtain a concurrency context.

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
      name (str): Name for concurrency context. This serves as the
         display name for the context, and also the unique context
         key (if the `key` parameter is omitted)
      concurrency (int): Maximum number of coroutines that can
         enter the context.
      key (str | None): Unique context key for this context. Optional.
         Used if the unique key isn't human readable -- e.g. includes
         api tokens or account ids so that the more readable `name`
         can be presented to users e.g in console UI>

    Returns:
       Asyncio Semaphore for concurrency context.
    """
    # sort out key
    key = key if key else name

    # do we have an existing semaphore? if not create one and store it
    semaphore = _concurrency_semaphores.get().get(key, None)
    if semaphore is None:
        semaphore = ConcurencySempahore(
            name, concurrency, asyncio.Semaphore(concurrency)
        )
        _concurrency_semaphores.get()[key] = semaphore

    # return the semaphore
    return semaphore.semaphore


def concurrency_status() -> dict[str, tuple[int, int]]:
    status: dict[str, tuple[int, int]] = {}
    for c in _concurrency_semaphores.get().values():
        status[c.name] = (c.concurrency - c.semaphore._value, c.concurrency)
    return status


def init_concurrency() -> None:
    _concurrency_semaphores.set({})


@dataclass
class ConcurencySempahore:
    name: str
    concurrency: int
    semaphore: asyncio.Semaphore


_concurrency_semaphores: ContextVar[dict[str, ConcurencySempahore]] = ContextVar(
    "concurrency_semaphores", default={}
)
