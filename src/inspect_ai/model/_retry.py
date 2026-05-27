from typing import TYPE_CHECKING, Awaitable, Callable

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
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from inspect_ai.model._model import RetryDecision


class ModelRetryConfig(TypedDict):
    wait: WaitBaseT
    retry: RetryBaseT
    before_sleep: Callable[[RetryCallState], (Awaitable[None] | None)]
    stop: StopBaseT


def model_retry_config(
    model_name: str,
    max_retries: int | None,
    timeout: int | None,
    should_retry: "Callable[[BaseException], bool | RetryDecision]",
    before_retry: Callable[[BaseException], (Awaitable[None] | None)],
    log_model_retry: Callable[[str, RetryCallState], Awaitable[None] | None],
    report_waiting_time: Callable[[float], None] | None = None,
    wait: WaitBaseT | None = None,
) -> ModelRetryConfig:
    # retry for transient http errors:
    # - use config.max_retries and config.timeout if specified, otherwise retry forever
    # - exponential backoff starting at 3 seconds (will wait 25 minutes
    #   on the 10th retry,then will wait no longer than 30 minutes on
    #   subsequent retries)

    async def on_before_sleep(rs: RetryCallState) -> None:
        # report the upcoming sleep as waiting time (that way the working time can't
        # expire while we are waiting b/c we've already offset it)
        if report_waiting_time is not None:
            report_waiting_time(rs.upcoming_sleep)

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

    # tenacity's retry_if_exception expects a bool predicate; coerce
    # RetryDecision returns to bool here so providers can pass their classifier
    # directly without a wrapper at every callsite.
    #
    # When the predicate is a provider's `api.should_retry` (returning
    # RetryDecision), this wrapper is the only place the decision is observed —
    # provider-internal retry loops (batchers, etc.) bypass `Model.should_retry`,
    # so without firing report_http_retry here, rate-limit retries inside those
    # loops would never reach the adaptive controller.
    #
    # When the predicate is `Model.should_retry` (returning plain bool),
    # `Model.should_retry` already calls `report_http_retry` itself based on
    # the underlying RetryDecision — and returns bool, so this branch is a
    # pure pass-through that doesn't double-report.
    def _retry_predicate(ex: BaseException) -> bool:
        from inspect_ai._util.retry import report_http_retry
        from inspect_ai.model._model import RetryDecision

        result = should_retry(ex)
        if isinstance(result, RetryDecision):
            if result.retry:
                report_http_retry(kind=result.kind, retry_after=result.retry_after)
            return result.retry
        return bool(result)

    return {
        "wait": wait,
        "retry": retry_if_exception(_retry_predicate),
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
