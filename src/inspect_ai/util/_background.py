from contextvars import ContextVar
from logging import getLogger
from typing import Any, Awaitable, Callable, Coroutine, Protocol, TypeVarTuple

from typing_extensions import Unpack

logger = getLogger(__name__)


PosArgsT = TypeVarTuple("PosArgsT")


class BackgroundTarget(Protocol):
    """Where ``background()`` starts work instead of the sample's task group.

    A target must propagate the ``LimitExceededError``,
    ``TerminateSampleError`` and ``ModelRefusalError`` that the work
    re-raises, so the sample enforces them.
    """

    def start_soon(
        self,
        func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, Any]],
        *args: Unpack[PosArgsT],
    ) -> None: ...


# Where background() starts work, when set. Unset, it starts in the sample's
# task group. Private: whoever sets it owns the work started there.
background_target: ContextVar[BackgroundTarget | None] = ContextVar(
    "background_target", default=None
)


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

    # handle and log background exceptions
    async def run() -> None:
        try:
            await func(*args)
        except Exception as ex:
            # LimitExceededError, TerminateSampleError and ModelRefusalError
            # are intentional control flow (sample-level limits, operator
            # termination, fail_on_refusal) that propagate through background
            # workers to be handled by the sample runner — they are not worker
            # failures, so don't log them as errors. They still re-raise so
            # the sample enforces them; a background target must propagate
            # them for that.
            from inspect_ai._util.exception import TerminateSampleError
            from inspect_ai.model._model import ModelRefusalError
            from inspect_ai.util._limit import LimitExceededError

            if not isinstance(
                ex, (LimitExceededError, TerminateSampleError, ModelRefusalError)
            ):
                logger.error(f"Background worker error: {ex}")
            raise

    # a set target owns the work, so no running sample is needed
    target = background_target.get()
    if target is not None:
        target.start_soon(run)
        return

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

    # kick it off
    sample.tg.start_soon(run)
