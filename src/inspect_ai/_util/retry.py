from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tenacity import RetryCallState

_http_retries_count: int = 0


def report_http_retry() -> None:
    from inspect_ai.log._samples import report_active_sample_retry
    from inspect_ai.util._concurrency import _active_controller, _request_had_retry

    # bump global counter
    global _http_retries_count
    _http_retries_count = _http_retries_count + 1

    # report sample retry
    report_active_sample_retry()

    # signal adaptive controller (if any) and mark request as retried
    _request_had_retry.set(True)
    controller = _active_controller.get()
    if controller is not None:
        controller.notify_retry()


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
