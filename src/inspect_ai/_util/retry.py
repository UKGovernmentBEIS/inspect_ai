from logging import getLogger

from tenacity import RetryCallState

from .constants import HTTP

logger = getLogger(__name__)


_http_retries_count: int = 0


def trace_http_retry(count: int, ex: Exception | None = None) -> None:
    # bump counter
    global _http_retries_count
    _http_retries_count = _http_retries_count + 1


def http_retries_count() -> int:
    return _http_retries_count


def log_rate_limit_retry(context: str, retry_state: RetryCallState) -> None:
    logger.log(
        HTTP,
        f"{context} rate limit retry {retry_state.attempt_number} after waiting for {retry_state.idle_for}",
    )
