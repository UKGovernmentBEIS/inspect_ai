import logging
from typing import Callable

import httpcore
import httpx
from httpx import HTTPStatusError
from tenacity import RetryCallState

from inspect_ai._util.constants import HTTP
from inspect_ai._util.http import is_retryable_http_status

logger = logging.getLogger(__name__)


def httpx_should_retry(ex: BaseException) -> bool:
    """Check whether an exception raised from httpx should be retried.

    Implements the strategy described here: https://cloud.google.com/storage/docs/retry-strategy

    Args:
      ex (BaseException): Exception to examine for retry behavior

    Returns:
      True if a retry should occur
    """
    if isinstance(ex, HTTPStatusError):
        return is_retryable_http_status(ex.response.status_code)

    elif httpx_should_retry_no_status_code(ex):
        return True

    # don't retry
    else:
        return False


def log_httpx_retry_attempt(context: str) -> Callable[[RetryCallState], None]:
    def log_attempt(retry_state: RetryCallState) -> None:
        logger.log(
            HTTP,
            f"{context} connection retry {retry_state.attempt_number} (retrying in {retry_state.upcoming_sleep:,.0f} seconds)",
        )

    return log_attempt


def httpx_should_retry_no_status_code(ex: BaseException) -> bool:
    """
    Check whether an exception (without an HTTP status code) should be retried.

    To understand this function, it may be helpful to look at the exception hierarchies for
    httpx and httpcore, which are reproduced below.


    # HTTPX Exception Hierarchy
    Exception (Python built-in)
    |
    +-- HTTPError
    |   |
    |   +-- RequestError
    |   |   |
    |   |   +-- TransportError
    |   |   |   |
    |   |   |   +-- TimeoutException
    |   |   |   |   |
    |   |   |   |   +-- ConnectTimeout
    |   |   |   |   +-- ReadTimeout
    |   |   |   |   +-- WriteTimeout
    |   |   |   |   +-- PoolTimeout
    |   |   |   |
    |   |   |   +-- NetworkError
    |   |   |   |   |
    |   |   |   |   +-- ConnectError
    |   |   |   |   +-- ReadError
    |   |   |   |   +-- WriteError
    |   |   |   |   +-- CloseError
    |   |   |   |
    |   |   |   +-- ProtocolError
    |   |   |   |   |
    |   |   |   |   +-- LocalProtocolError
    |   |   |   |   +-- RemoteProtocolError
    |   |   |   |
    |   |   |   +-- ProxyError
    |   |   |   +-- UnsupportedProtocol
    |   |   |
    |   |   +-- DecodingError
    |   |   +-- TooManyRedirects
    |   |
    |   +-- HTTPStatusError
    |
    +-- InvalidURL
    +-- CookieConflict
    +-- RuntimeError (Python built-in)
        |
        +-- StreamError
            |
            +-- StreamConsumed
            +-- StreamClosed
            +-- ResponseNotRead
            +-- RequestNotRead


    # HTTPCore Exception Hierarchy
    Exception (Python built-in)
    |
    +-- ConnectionNotAvailable
    +-- ProxyError
    +-- UnsupportedProtocol
    +-- ProtocolError
    |   |
    |   +-- RemoteProtocolError
    |   +-- LocalProtocolError
    |
    +-- TimeoutException
    |   |
    |   +-- PoolTimeout
    |   +-- ConnectTimeout
    |   +-- ReadTimeout
    |   +-- WriteTimeout
    |
    +-- NetworkError
        |
        +-- ConnectError
        +-- ReadError
        +-- WriteError
    """
    # Base class for all exceptions that occur at the level of the Transport API.
    is_transport_error = isinstance(ex, httpx.TransportError)

    # Sometimes exceptions are raised directly by httpcore, the lower-level library that httpx uses
    is_httpcore_network_error = isinstance(ex, httpcore.NetworkError)
    is_httpcore_timeout_error = isinstance(ex, httpcore.TimeoutException)
    is_httpcore_protocol_error = isinstance(ex, httpcore.ProtocolError)

    # extensible in case we notice other cases
    return any(
        [
            is_transport_error,
            is_httpcore_network_error,
            is_httpcore_timeout_error,
            is_httpcore_protocol_error,
        ]
    )
