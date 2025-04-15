import sys

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


def inner_exception(exc: Exception) -> Exception:
    flattended = flatten_exception_group(exc)
    return flattended[0]


def flatten_exception_group(exc: Exception) -> list[Exception]:
    """Recursively flatten an ExceptionGroup to get all contained exceptions."""
    context = exc.__context__ if isinstance(exc.__context__, Exception) else None
    cause = exc.__cause__ if isinstance(exc.__cause__, Exception) else None

    # TODO: This works, but I need to tighten it up quite a bit. Plus, I need
    # to commit the tests.

    # conceptually, if cause is present, it means that this exception wraps
    # the cause - rather than cause being a separate error.

    exceptions_to_flatten = set[Exception]()
    unflattened_to_add: Exception | None = None
    if isinstance(exc, ExceptionGroup):
        exceptions_to_flatten.update(exc.exceptions)
    else:
        if context and cause is None:
            exceptions_to_flatten.add(exc)
        else:
            unflattened_to_add = exc

    if context and cause is None:
        exceptions_to_flatten.add(context)

    flattened = [
        flattened_e
        for e in exceptions_to_flatten
        for flattened_e in flatten_exception_group(e)
    ]

    return flattened + [unflattened_to_add] if unflattened_to_add else flattened
