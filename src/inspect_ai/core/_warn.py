from logging import Logger


def warn_once(logger: Logger, message: str) -> None:
    """Log `message` as a warning the first time it is seen in this process.

    A copy of `inspect_ai._util.logger.warn_once` with its own record of sent
    messages, so `inspect_ai.core` doesn't import `_util.logger` (which loads
    rich, anyio and the trace machinery). Messages sent through either function
    are deduplicated separately.
    """
    if message not in _warned:
        logger.warning(message)
        _warned.add(message)


_warned: set[str] = set()
