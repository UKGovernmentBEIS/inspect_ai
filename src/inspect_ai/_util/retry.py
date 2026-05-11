from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from tenacity import RetryCallState

_http_retries_count: int = 0


def report_http_retry(
    kind: Literal["rate_limit", "transient"] = "transient",
    retry_after: float | None = None,
) -> None:
    """Report an HTTP retry event.

    `kind="rate_limit"` (HTTP 429 or provider-specific equivalents) signals
    the adaptive controller to scale down. `kind="transient"` (default —
    5xx, timeouts, network errors) only marks the request as retried,
    pausing scale-up but not triggering a cut.
    """
    from inspect_ai.log._samples import report_active_sample_retry
    from inspect_ai.util._concurrency import _active_controller, _request_had_retry

    # bump global counter
    global _http_retries_count
    _http_retries_count = _http_retries_count + 1

    # report sample retry
    report_active_sample_retry()

    # mark request as retried so the eventual success won't count as scale-up
    _request_had_retry.set(True)

    # only rate-limit retries scale the controller down
    if kind == "rate_limit":
        controller = _active_controller.get()
        if controller is not None:
            controller.notify_retry(retry_after=retry_after)


def http_retries_count() -> int:
    return _http_retries_count


def sample_context_prefix() -> str:
    """Build a compact prefix like "[Abc12xY mmlu/42/1 openai/gpt-4o] " from the active sample, or ""."""
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is None:
        return ""
    return (
        f"[{active.id} {active.task}/{active.sample.id}/{active.epoch} {active.model}] "
    )


def retry_error_summary(retry_state: RetryCallState) -> str:
    """Build a compact suffix like " [RateLimitError 429]" from a retry state, or ""."""
    if retry_state.outcome is None:
        return ""
    ex = retry_state.outcome.exception()
    if ex is None:
        return ""

    parts = [type(ex).__name__]
    status: int | None = getattr(ex, "status_code", None)
    if status is None:
        status = getattr(getattr(ex, "response", None), "status_code", None)
    if status is not None:
        parts.append(str(status))
    code = getattr(ex, "code", None)
    if code is not None:
        parts.append(str(code))
    return f" [{' '.join(parts)}]"
