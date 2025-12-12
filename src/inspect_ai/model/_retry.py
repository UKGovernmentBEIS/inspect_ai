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
    before_retry: Callable[[BaseException], (Awaitable[None] | None)],
    log_model_retry: Callable[[str, RetryCallState], Awaitable[None] | None],
    wait: WaitBaseT | None = None,
) -> ModelRetryConfig:
    # retry for transient http errors:
    # - use config.max_retries and config.timeout if specified, otherwise retry forever
    # - exponential backoff starting at 3 seconds (will wait 25 minutes
    #   on the 10th retry,then will wait no longer than 30 minutes on
    #   subsequent retries)

    async def on_before_sleep(rs: RetryCallState) -> None:
        res = log_model_retry(model_name, rs)
        if res is not None:
            await res
        if not rs.outcome:
            return
        ex = rs.outcome.exception()
        if ex is None:
            return
        res = before_retry(ex)
        if res is not None:
            await res

    # resolve wait
    wait = (
        wait
        if wait is not None
        else wait_exponential_jitter(initial=3, max=(30 * 60), jitter=3)
    )

    return {
        "wait": wait,
        "retry": retry_if_exception(should_retry),
        "before_sleep": on_before_sleep,
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
