import itertools
import sys

import anyio

from inspect_ai._util._async import current_async_backend

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


def inner_exception(exc: Exception) -> Exception:
    return _flatten_exception(exc, set())[0]


def _flatten_exception(exc: Exception, seen: set[int] | None = None) -> list[Exception]:
    """Recursively flatten an exception to get all related (__context__) and contained (ExceptionGroup) exceptions."""
    if seen is None:
        seen = set()

    # Prevent infinite recursion by tracking seen exceptions by their id
    exc_id = id(exc)
    if exc_id in seen:
        return []
    seen.add(exc_id)

    context_to_follow = (
        [exc.__context__]
        # conceptually, if __cause__ is present, it means that this exception
        # wraps the cause - rather than cause being a separate error. We'll
        # follow __context__ only if __cause__ is None
        if exc.__cause__ is None and isinstance(exc.__context__, Exception)
        else []
    )

    (maybe_this_exception, children_to_follow) = (
        ([], exc.exceptions)
        # if it's a group, follow the children discarding the group
        if isinstance(exc, ExceptionGroup)
        else ([exc], [])
    )

    # We have to use a set since the same exception is likely to be included in
    # both __context__ and .exceptions
    other_exceptions = [
        flattened_e
        for e in set(itertools.chain(context_to_follow, children_to_follow))
        for flattened_e in _flatten_exception(e, seen)
    ]

    return maybe_this_exception + other_exceptions


def safe_current_task_id() -> int | None:
    if current_async_backend() is not None:
        return anyio.get_current_task().id
    else:
        return None
