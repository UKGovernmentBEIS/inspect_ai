from typing import TYPE_CHECKING, Awaitable, Callable

from tenacity import (
    RetryCallState,
    retry_if_exception,
    wait_exponential_jitter,
)
from tenacity.retry import RetryBaseT
from tenacity.stop import StopBaseT
from tenacity.wait import WaitBaseT
from typing_extensions import TypedDict

from inspect_ai.model._generate_overrides import generate_config_override

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

    # The stop condition reads the live `inspect ctl config` overrides on
    # every post-attempt check (not just at decoration time) so a mid-flight
    # retune of max_retries/timeout reaches generate calls already inside
    # their retry loop — the provider-incident case — while an in-flight
    # attempt always drains first. max_retries counts retries, as documented:
    # N retries allow N+1 total attempts (0 = fail after the first attempt).
    # Timeout semantics match tenacity's stop_after_delay.
    def stop(retry_state: RetryCallState) -> bool:
        effective_max_retries = generate_config_override("max_retries", max_retries)
        effective_timeout = generate_config_override("timeout", timeout)
        if (
            effective_max_retries is not None
            and retry_state.attempt_number > effective_max_retries
        ):
            return True
        if (
            effective_timeout is not None
            and retry_state.seconds_since_start is not None
            and retry_state.seconds_since_start >= effective_timeout
        ):
            return True
        return False

    return {
        "wait": wait,
        "retry": retry_if_exception(_retry_predicate),
        "before_sleep": on_before_sleep,
        "stop": stop,
    }
