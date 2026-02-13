from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tenacity import RetryCallState

_http_retries_count: int = 0


def report_http_retry() -> None:
    from inspect_ai.log._samples import report_active_sample_retry

    # bump global counter
    global _http_retries_count
    _http_retries_count = _http_retries_count + 1

    # report sample retry
    report_active_sample_retry()


def http_retries_count() -> int:
    return _http_retries_count


def sample_context_prefix() -> str:
    """Build a compact context prefix from the active sample.

    Returns a string like "[Abc12xY mmlu/42/1 openai/gpt-4o] " or "" if
    no sample is active.
    """
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is None:
        return ""
    return (
        f"[{active.id} {active.task}/{active.sample.id}/{active.epoch} {active.model}] "
    )


def retry_error_summary(retry_state: RetryCallState) -> str:
    """Build a compact error summary from a tenacity RetryCallState.

    Returns a string like " [RateLimitError 429 rate_limit_exceeded]" or ""
    if no exception is available. Never includes full error messages (could
    leak prompt content or API keys).
    """
    if retry_state.outcome is None:
        return ""
    ex = retry_state.outcome.exception()
    if ex is None:
        return ""

    type_name = type(ex).__name__

    # HTTP status code — on the exception itself or on ex.response
    status: int | None = getattr(ex, "status_code", None)
    if status is None:
        response = getattr(ex, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)

    # API error code (e.g. "rate_limit_exceeded", "server_error")
    code: str | None = getattr(ex, "code", None)

    parts = [type_name]
    if status is not None:
        parts.append(str(status))
    if code is not None:
        parts.append(code)
    return f" [{' '.join(parts)}]"
