import asyncio
import inspect
from functools import wraps
from typing import (
    Any,
    Callable,
    Protocol,
    TypeVar,
    cast,
    overload,
    runtime_checkable,
)

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.content import Content
from inspect_ai.util._store import Store, dict_jsonable, init_subtask_store

SubtaskResult = str | int | float | bool | list[Content]

RT = TypeVar("RT", SubtaskResult, Any)


@runtime_checkable
class Subtask(Protocol):
    """Subtask with distinct `Store` and `Transcript`.

    Args:
      *args (Any): Arguments for the subtask.
      **kwargs (Any): Keyword arguments for the subtask.

    Returns:
      Result of subtask.
    """

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...


@overload
def subtask(
    name: str,
    store: Store | None = None,
    type: str | None = None,
    input: dict[str, Any] | None = None,
) -> Callable[..., Subtask]: ...


@overload
def subtask(
    name: Subtask,
    store: Store | None = None,
    type: str | None = None,
    input: dict[str, Any] | None = None,
) -> Subtask: ...


def subtask(
    name: str | Subtask,
    store: Store | None = None,
    type: str | None = None,
    input: dict[str, Any] | None = None,
) -> Callable[..., Subtask] | Subtask:
    r"""Decorator for subtasks.

    Args:
        func (Subtask): Subtask implementation.
        name (str | None): Name for subtask (defaults to function name)
        store (store | None): Store to use for subtask
        type (str | None): Type to use for subtask
        input (dict[str, Any] | None): Input to log for subtask

    Returns:
        Function which runs the Subtask, providing an isolated
        `Store` and `Transcript`, and recording a `SubtaskEvent`
        when it is complete.
    """

    def create_subtask_wrapper(func: Subtask, name: str | None = None) -> Subtask:
        from inspect_ai.log._transcript import (
            SubtaskEvent,
            track_store_changes,
            transcript,
        )

        @wraps(func)
        async def run_subtask(*args: Any, **kwargs: Any) -> RT:
            # resolve name
            subtask_name = (
                name
                if name is not None
                else cast(str, getattr(func, "__name__", "subtask"))
            )

            # verify async
            if not is_callable_coroutine(func):
                raise TypeError(
                    f"'{subtask_name}' is not declared as an async callable."
                )

            # capture input for logging if required
            if input is not None:
                log_input = dict_jsonable(input)
            else:
                log_input = {}
                if len(args) > 0:
                    params = list(inspect.signature(func).parameters.keys())
                    for i, arg in enumerate(args):
                        log_input[params[i]] = arg
                log_input = dict_jsonable(log_input | kwargs)

            # create coroutine so we can provision a subtask contextvars
            async def run() -> tuple[RT, SubtaskEvent]:
                # initialise subtask (provisions store and transcript)
                init_subtask(subtask_name, store if store else Store())

                # run the subtask
                with track_store_changes():  # type: ignore
                    result = await func(*args, **kwargs)

                # create a subtask event
                event = SubtaskEvent(
                    name=subtask_name,
                    input=log_input,
                    result=result,
                    events=transcript().events,
                    type=type,
                )

                # return result and event
                return result, event

            # create and run the task as a coroutine
            asyncio_task = asyncio.create_task(run())
            result, event = await asyncio_task

            # fire event
            transcript()._event(event)

            # return result
            return result

        return run_subtask

    if isinstance(name, str):

        def wrapper(func: Subtask) -> Subtask:
            return create_subtask_wrapper(func, name)

        return wrapper
    else:
        return create_subtask_wrapper(name)


def init_subtask(name: str, store: Store) -> None:
    from inspect_ai.log._transcript import (
        Transcript,
        init_transcript,
    )

    init_subtask_store(store)
    init_transcript(Transcript(name=name))
