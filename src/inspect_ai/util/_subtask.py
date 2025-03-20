import inspect
from datetime import datetime
from functools import wraps
from logging import getLogger
from typing import (
    Any,
    Callable,
    Protocol,
    TypeVar,
    cast,
    overload,
    runtime_checkable,
)

from inspect_ai._util._async import is_callable_coroutine, tg_collect
from inspect_ai._util.content import Content
from inspect_ai._util.trace import trace_action
from inspect_ai._util.working import sample_waiting_time
from inspect_ai.util._store import Store, dict_jsonable, init_subtask_store

SubtaskResult = str | int | float | bool | list[Content]

RT = TypeVar("RT", SubtaskResult, Any)


logger = getLogger(__name__)


@runtime_checkable
class Subtask(Protocol):
    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Subtask with distinct `Store` and `Transcript`.

        Args:
            *args (Any): Arguments for the subtask.
            **kwargs (Any): Keyword arguments for the subtask.

        Returns:
            Result of subtask.
        """
        ...


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
        name: Name for subtask (defaults to function name)
        store: Store to use for subtask
        type: Type to use for subtask
        input: Input to log for subtask

    Returns:
        Function which runs the Subtask, providing an isolated
        `Store` and `Transcript`, and recording a `SubtaskEvent`
        when it is complete.
    """

    def create_subtask_wrapper(func: Subtask, name: str | None = None) -> Subtask:
        from inspect_ai.log._transcript import (
            Event,
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
            async def run() -> tuple[RT, list[Event]]:
                # initialise subtask (provisions store and transcript)
                init_subtask(subtask_name, store if store else Store())

                # run the subtask
                with trace_action(logger, "Subtask", subtask_name):
                    with track_store_changes():  # type: ignore
                        result = await func(*args, **kwargs)

                # return result and event
                return result, list(transcript().events)

            # create subtask event
            waiting_time_start = sample_waiting_time()
            event = SubtaskEvent(
                name=subtask_name, input=log_input, type=type, pending=True
            )
            transcript()._event(event)

            # create and run the task as a coroutine
            result, events = (await tg_collect([run]))[0]

            # time accounting
            completed = datetime.now()
            waiting_time_end = sample_waiting_time()
            event.completed = completed
            event.working_time = (completed - event.timestamp).total_seconds() - (
                waiting_time_end - waiting_time_start
            )

            # update event
            event.result = result
            event.events = events
            event.pending = None
            transcript()._event_updated(event)

            # return result
            return result

        return run_subtask

    if isinstance(name, str):

        def wrapper(func: Subtask) -> Subtask:
            return create_subtask_wrapper(func, name)

        return wrapper
    else:
        return create_subtask_wrapper(name)


def init_subtask(name: str, store: Store) -> Any:
    from inspect_ai.log._transcript import (
        Transcript,
        init_transcript,
    )

    init_subtask_store(store)
    transcript = Transcript(name=name)
    init_transcript(transcript)
    return transcript
