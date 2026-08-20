import logging
from typing import TYPE_CHECKING, Callable, TypeAlias, cast

import httpcore
import httpx
from tenacity import RetryCallState

from inspect_ai._util.constants import HTTP
from inspect_ai._util.http import is_retryable_http_status, parse_retry_after

if TYPE_CHECKING:
    import httpx2

    from inspect_ai.model._model import RetryDecision

    AnyStatusError: TypeAlias = httpx.HTTPStatusError | httpx2.HTTPStatusError

logger = logging.getLogger(__name__)

# openai >= 3 and anthropic >= 1 are built on `httpx2`, a separate distribution
# whose exception classes are unrelated to httpx's, so `isinstance` against one
# flavor misses the other. It matters here because errors raised while iterating
# a streamed response body escape those SDKs unwrapped, reaching this module in
# whichever flavor the SDK uses. httpx2 is not a core dependency of inspect_ai.
_STATUS_ERRORS: tuple[type[BaseException], ...] = (httpx.HTTPStatusError,)
_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (httpx.TransportError,)
try:
    import httpx2 as _httpx2

    _STATUS_ERRORS += (_httpx2.HTTPStatusError,)
    _TRANSPORT_ERRORS += (_httpx2.TransportError,)
except ImportError:
    pass


def _as_status_error(ex: BaseException) -> "AnyStatusError | None":
    """The exception as an `HTTPStatusError` of either httpx flavor, if it is one."""
    return cast("AnyStatusError", ex) if isinstance(ex, _STATUS_ERRORS) else None


def httpx_should_retry(ex: BaseException) -> bool:
    """Check whether an exception raised from httpx should be retried.

    Implements the strategy described here: https://cloud.google.com/storage/docs/retry-strategy

    Args:
      ex (BaseException): Exception to examine for retry behavior

    Returns:
      True if a retry should occur
    """
    status_error = _as_status_error(ex)
    if status_error is not None:
        return is_retryable_http_status(status_error.response.status_code)

    elif httpx_should_retry_no_status_code(ex):
        return True

    # don't retry
    else:
        return False


def httpx_classify_retry(ex: BaseException) -> "RetryDecision | None":
    """Classify an httpx-based exception as rate_limit / transient / not retryable.

    Returns None when the exception isn't retryable (mirrors `httpx_should_retry == False`).
    Reads `Retry-After` and `x-ratelimit-reset-*` from the response headers when available.
    """
    from inspect_ai.model._model import RetryDecision

    status_error = _as_status_error(ex)
    if status_error is not None:
        status = status_error.response.status_code
        retry_after = parse_retry_after(status_error.response.headers)
        if status == 429:
            return RetryDecision.rate_limit(retry_after=retry_after)
        if is_retryable_http_status(status):
            return RetryDecision.transient(retry_after=retry_after)
        return None
    if httpx_should_retry_no_status_code(ex):
        return RetryDecision.transient()
    return None


def log_httpx_retry_attempt(context: str) -> Callable[[RetryCallState], None]:
    def log_attempt(retry_state: RetryCallState) -> None:
        from inspect_ai._util.retry import sample_context_prefix

        prefix = sample_context_prefix()
        logger.log(
            HTTP,
            f"{prefix}{context} connection retry {retry_state.attempt_number} (retrying in {retry_state.upcoming_sleep:,.0f} seconds)",
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
    is_transport_error = isinstance(ex, _TRANSPORT_ERRORS)

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
