import logging
from typing import Callable

from httpx import ConnectError, ConnectTimeout, HTTPStatusError, ReadTimeout
from tenacity import RetryCallState

from inspect_ai._util.constants import HTTP

logger = logging.getLogger(__name__)


def httpx_should_retry(ex: BaseException) -> bool:
    """Check whether an exception raised from httpx should be retried.

    Implements the strategy described here: https://cloud.google.com/storage/docs/retry-strategy

    Args:
      ex (BaseException): Exception to examine for retry behavior

    Returns:
      True if a retry should occur
    """
    # httpx status exception
    if isinstance(ex, HTTPStatusError):
        # request timeout
        if ex.response.status_code == 408:
            return True
        # lock timeout
        elif ex.response.status_code == 409:
            return True
        # rate limit
        elif ex.response.status_code == 429:
            return True
        # internal errors
        elif ex.response.status_code >= 500:
            return True
        else:
            return False

    # connection error
    elif is_httpx_connection_error(ex):
        return True

    # don't retry
    else:
        return False


def log_rate_limit_retry(context: str, retry_state: RetryCallState) -> None:
    logger.log(
        HTTP,
        f"{context} rate limit retry {retry_state.attempt_number} after waiting for {retry_state.idle_for}",
    )


def log_retry_attempt(context: str) -> Callable[[RetryCallState], None]:
    def log_attempt(retry_state: RetryCallState) -> None:
        logger.log(
            HTTP,
            f"{context} connection retry {retry_state.attempt_number} after waiting for {retry_state.idle_for}",
        )

    return log_attempt


def is_httpx_connection_error(ex: BaseException) -> bool:
    return isinstance(ex, ConnectTimeout | ConnectError | ConnectionError | ReadTimeout)
