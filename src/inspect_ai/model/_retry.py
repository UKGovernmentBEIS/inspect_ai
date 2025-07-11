import functools
from typing import Awaitable, Callable, TypedDict

from tenacity import (
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    stop_never,
    wait_exponential_jitter,
)
from tenacity.retry import RetryBaseT
from tenacity.stop import StopBaseT
from tenacity.wait import WaitBaseT


class ModelRetryConfig(TypedDict):
    wait: WaitBaseT
    retry: RetryBaseT
    before_sleep: Callable[[RetryCallState], (Awaitable[None] | None)]
    stop: StopBaseT


def model_retry_config(
    model_name: str,
    max_retries: int | None,
    timeout: int | None,
    should_retry: Callable[[BaseException], bool],
    log_model_retry: Callable[[str, RetryCallState], Awaitable[None] | None],
) -> ModelRetryConfig:
    # retry for transient http errors:
    # - use config.max_retries and config.timeout if specified, otherwise retry forever
    # - exponential backoff starting at 3 seconds (will wait 25 minutes
    #   on the 10th retry,then will wait no longer than 30 minutes on
    #   subsequent retries)
    return {
        "wait": wait_exponential_jitter(initial=3, max=(30 * 60), jitter=3),
        "retry": retry_if_exception(should_retry),
        "before_sleep": functools.partial(log_model_retry, model_name),
        "stop": (
            stop_after_attempt(max_retries) | stop_after_delay(timeout)
            if max_retries is not None and timeout is not None
            else stop_after_attempt(max_retries)
            if max_retries is not None
            else stop_after_delay(timeout)
            if timeout is not None
            else stop_never
        ),
    }
