from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple

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


class RetryErrorInfo(NamedTuple):
    exception_type: str | None
    status_code: int | None


def _retry_exception(retry_state: RetryCallState) -> BaseException | None:
    """Exception that triggered the retry, unwrapping a tenacity RetryError.

    chatapi retries httpx errors *below* the outer retry loop, so the outer loop
    sees a `RetryError` whose real cause (e.g. `httpx.HTTPStatusError`) lives in
    `__cause__` (see chatapi.classify_chat_api_error). Report that cause — the
    bare "RetryError" type name tells a hook nothing.
    """
    if retry_state.outcome is None:
        return None
    ex = retry_state.outcome.exception()
    if ex is None:
        return None
    from tenacity import RetryError

    if isinstance(ex, RetryError) and ex.__cause__ is not None:
        return ex.__cause__
    return ex


def _status_code(ex: BaseException) -> int | None:
    """HTTP status from a provider exception: status_code → response.status_code → code.

    `code` is accepted only when it's an int (google-genai `APIError.code`);
    OpenAI/Anthropic `code` is a string error slug (e.g. "rate_limit_exceeded")
    that must not leak into this int field.
    """
    for value in (
        getattr(ex, "status_code", None),
        getattr(getattr(ex, "response", None), "status_code", None),
        getattr(ex, "code", None),
    ):
        if isinstance(value, int):
            return value
    return None


def retry_error_type_status(retry_state: RetryCallState) -> RetryErrorInfo:
    """Extract the exception type name and HTTP status code from a retry state."""
    ex = _retry_exception(retry_state)
    if ex is None:
        return RetryErrorInfo(None, None)
    return RetryErrorInfo(type(ex).__name__, _status_code(ex))


def retry_error_summary(retry_state: RetryCallState) -> str:
    """Build a compact suffix like " [RateLimitError 429]" from a retry state, or ""."""
    ex = _retry_exception(retry_state)
    if ex is None:
        return ""

    parts = [type(ex).__name__]
    status = _status_code(ex)
    if status is not None:
        parts.append(str(status))
    # non-int `code` is a string error slug (e.g. "rate_limit_exceeded"); an int
    # `code` is already surfaced as the status above.
    code = getattr(ex, "code", None)
    if code is not None and not isinstance(code, int):
        parts.append(str(code))
    return f" [{' '.join(parts)}]"
