import logging
import sys
from typing import TYPE_CHECKING, Callable

import httpcore
import httpx
from httpx import HTTPStatusError
from tenacity import RetryCallState

from inspect_ai._util.constants import HTTP
from inspect_ai._util.http import is_retryable_http_status, parse_retry_after

if TYPE_CHECKING:
    from inspect_ai.model._model import RetryDecision

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


def httpx_classify_retry(ex: BaseException) -> "RetryDecision | None":
    """Classify an httpx-based exception as rate_limit / transient / not retryable.

    Returns None when the exception isn't retryable (mirrors `httpx_should_retry == False`).
    Reads `Retry-After` and `x-ratelimit-reset-*` from the response headers when available.
    """
    from inspect_ai.model._model import RetryDecision

    if isinstance(ex, HTTPStatusError):
        status = ex.response.status_code
        retry_after = parse_retry_after(ex.response.headers)
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
    return isinstance(ex, _retryable_no_status_errors())


# transport-level errors (from httpx, or raised directly by httpcore, the
# lower-level library it uses) that should be retried despite carrying no
# HTTP status code
_RETRYABLE_NO_STATUS_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpcore.NetworkError,
    httpcore.TimeoutException,
    httpcore.ProtocolError,
)
_httpx2_errors_added = False


def _retryable_no_status_errors() -> tuple[type[BaseException], ...]:
    """Exception types (without an HTTP status code) that warrant a retry.

    httpx2/httpcore2 are not direct dependencies of inspect_ai — they arrive
    transitively with openai >= 3 and anthropic >= 1, whose SDKs are built on
    them and can surface their exception types; classify those exactly like
    their legacy httpx/httpcore counterparts. Resolved lazily (an httpx2
    exception can only exist if httpx2 is already imported) so that importing
    inspect_ai doesn't pay for importing httpx2. No lock needed: inspect runs
    on a single event loop thread, and re-running the extension is harmless.
    """
    global _RETRYABLE_NO_STATUS_ERRORS, _httpx2_errors_added
    if not _httpx2_errors_added and "httpx2" in sys.modules:
        import httpx2

        additions: tuple[type[BaseException], ...] = (httpx2.TransportError,)
        try:
            import httpcore2

            additions = additions + (
                httpcore2.NetworkError,
                httpcore2.TimeoutException,
                httpcore2.ProtocolError,
            )
        except ImportError:
            # httpx2's httpcore2 dependency is platform-conditional
            pass
        _RETRYABLE_NO_STATUS_ERRORS = _RETRYABLE_NO_STATUS_ERRORS + additions
        _httpx2_errors_added = True
    return _RETRYABLE_NO_STATUS_ERRORS
