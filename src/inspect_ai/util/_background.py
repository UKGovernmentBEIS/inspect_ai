import sys
from logging import getLogger
from typing import Any, Awaitable, Callable

if sys.version_info >= (3, 11):
    from typing import TypeVarTuple
else:
    from typing_extensions import TypeVarTuple


from typing_extensions import Unpack

logger = getLogger(__name__)


PosArgsT = TypeVarTuple("PosArgsT")


def background(
    func: Callable[[Unpack[PosArgsT]], Awaitable[Any]],
    *args: Unpack[PosArgsT],
) -> None:
    """Run an async function in the background of the current sample.

    Background functions must be run from an executing sample.
    The function will run as long as the current sample is running.

    When the sample terminates, an anyio cancelled error will be
    raised in the background function. To catch this error and
    cleanup:

    ```python
    import anyio

    async def run():
        try:
            # background code
        except anyio.get_cancelled_exc_class():
            ...
    ```

    Args:
       func: Async function to run
       *args: Optional function arguments.
    """
    from inspect_ai.log._samples import sample_active

    # get the active sample
    sample = sample_active()
    if sample is None:
        raise RuntimeError(
            "background() function must be called from a running sample."
        )

    # handle and log background exceptions
    async def run() -> None:
        try:
            await func(*args)
        except Exception as ex:
            logger.error(f"Background worker error: {ex}")
            raise

    # kick it off
    sample.tg.start_soon(run)
