from logging import getLogger

from tenacity import RetryCallState

from inspect_ai._util.constants import HTTP

logger = getLogger(__name__)


_http_retries = 0


def report_http_retry(ex: Exception | None = None) -> None:
    pass


def log_rate_limit_retry(context: str, retry_state: RetryCallState) -> None:
    logger.log(
        HTTP,
        f"{context} rate limit retry {retry_state.attempt_number} after waiting for {retry_state.idle_for}",
    )
