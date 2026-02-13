from __future__ import annotations

import logging
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
    raw_code = getattr(ex, "code", None)
    code: str | None = str(raw_code) if raw_code is not None else None

    parts = [type_name]
    if status is not None:
        parts.append(str(status))
    if code is not None:
        parts.append(code)
    return f" [{' '.join(parts)}]"


class SampleContextFilter(logging.Filter):
    """Logging filter that enriches log records with active sample context.

    Prepends a compact prefix to record.msg for plain text formatters and
    sets structured attributes on the record for JSON/structured formatters.
    Passes records through unchanged when no active sample exists.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from inspect_ai.log._samples import sample_active

        active = sample_active()
        if active is not None:
            prefix = (
                f"[{active.id} {active.task}/{active.sample.id}/{active.epoch} "
                f"{active.model}] "
            )
            record.msg = f"{prefix}{record.getMessage()}"
            record.args = None
            record.sample_uuid = active.id  # type: ignore[attr-defined]
            record.sample_task = active.task  # type: ignore[attr-defined]
            record.sample_id = active.sample.id  # type: ignore[attr-defined]
            record.sample_epoch = active.epoch  # type: ignore[attr-defined]
            record.sample_model = active.model  # type: ignore[attr-defined]
        return True


_sample_context_logging_installed = False


_SDK_LOGGERS = ("openai._base_client",)


def install_sample_context_logging() -> None:
    """Install SampleContextFilter on SDK loggers.

    Attaches the filter to the actual emitting loggers (not parent loggers)
    so that retry messages from the OpenAI SDK are enriched with active
    sample context. Safe to call multiple times — installs at most once.
    """
    global _sample_context_logging_installed
    if _sample_context_logging_installed:
        return
    _sample_context_logging_installed = True

    sample_filter = SampleContextFilter()
    for name in _SDK_LOGGERS:
        logging.getLogger(name).addFilter(sample_filter)
