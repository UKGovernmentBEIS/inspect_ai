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
    if sample.tg is None:
        raise RuntimeError(
            "background() function must be called after sample has been started."
        )

    # handle and log background exceptions
    async def run() -> None:
        try:
            await func(*args)
        except Exception as ex:
            # LimitExceededError and TerminateSampleError are intentional
            # control flow (sample-level limits, operator termination) that
            # propagate through background workers to be handled by the sample
            # runner — they are not worker failures, so don't log them as
            # errors. They still re-raise so the sample enforces them.
            from inspect_ai._util.exception import TerminateSampleError
            from inspect_ai.util._limit import LimitExceededError

            if not isinstance(ex, (LimitExceededError, TerminateSampleError)):
                logger.error(f"Background worker error: {ex}")
            raise

    # kick it off
    sample.tg.start_soon(run)
