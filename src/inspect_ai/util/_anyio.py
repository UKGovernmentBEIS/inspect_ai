import itertools
import sys

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


def inner_exception(exc: Exception) -> Exception:
    flattended = _flatten_exception(exc)
    return flattended[0]


def _flatten_exception(exc: Exception) -> list[Exception]:
    """Recursively flatten an to get all related (__context__) and contained (ExceptionGroup) exceptions."""
    # TODO: I need to commit the tests.

    context_to_follow = (
        [exc.__context__]
        # conceptually, if cause is present, it means that this exception wraps
        # the cause - rather than cause being a separate error.
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
        for flattened_e in _flatten_exception(e)
    ]

    return maybe_this_exception + other_exceptions
