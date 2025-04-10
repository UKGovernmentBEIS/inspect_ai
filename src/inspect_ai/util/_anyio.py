import sys

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


def inner_exception(exc: Exception) -> Exception:
    flattended = flatten_exception_group(exc)
    return flattended[0]


def flatten_exception_group(exc: Exception) -> list[Exception]:
    """Recursively flatten an ExceptionGroup to get all contained exceptions."""
    if (
        hasattr(exc, "__context__")
        and exc.__context__ is not None
        and isinstance(exc.__context__, Exception)
    ):
        return flatten_exception_group(exc.__context__) + [exc]

    if isinstance(exc, ExceptionGroup):
        flattened = []
        for nested_exc in exc.exceptions:
            flattened.extend(flatten_exception_group(nested_exc))
        return flattened

    return [exc]
