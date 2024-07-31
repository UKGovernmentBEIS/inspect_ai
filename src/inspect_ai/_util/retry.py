import logging
import math
import random
from typing import Callable

from httpx import ConnectError, ConnectTimeout, HTTPStatusError, ReadTimeout
from tenacity import RetryCallState
from tenacity.wait import wait_base

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


class wait_sigmoid(wait_base):
    """Wait strategy that uses a sigmoid distribution."""

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: float = 1.0,
        steepness: float = 0.5,
        midpoint: int = 5,
    ) -> None:
        """Wait strategy that uses a sigmoid distribution.

        Args:
          initial_delay (int): Length of the first delay
          max_delay (int): Maximum delay in seconds
          jitter (float): Jitter wait times by random internal
          steepness (float): Controls how quickly the function rises
          midpoint (int): Attempt number at which the delay is half of max delay.

        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.steepness = steepness
        self.midpoint = midpoint

    def __call__(self, retry_state: "RetryCallState") -> float:
        if retry_state.attempt_number == 1:
            delay = self.initial_delay
        else:
            normalized_attempt = (
                retry_state.attempt_number - self.midpoint
            ) * self.steepness
            delay = self.max_delay * sigmoid(normalized_attempt)
        delay = delay + random.uniform(0, self.jitter)
        return delay


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))
