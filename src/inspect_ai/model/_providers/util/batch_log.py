"""Logging utilities for batch operations."""


def log_batch(message: str) -> None:
    """Log batch operation messages.

    For now, this simply calls print() but provides a centralized point
    for future custom logging implementation.

    Args:
        message: The message to log
    """
    print(message)
