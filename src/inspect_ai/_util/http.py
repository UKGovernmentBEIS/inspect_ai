import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


# see https://cloud.google.com/storage/docs/retry-strategy
def is_retryable_http_status(status_code: int) -> bool:
    return status_code in [408, 429] or (500 <= status_code < 600)


def status_code_of(ex: BaseException) -> int | None:
    """Best-effort HTTP status code extraction from a provider/model exception.

    Checks the attribute names used across provider SDKs and Inspect's own
    wrappers: `status_code` (Anthropic/OpenAI SDKs, `ModelGenerateError`) and
    `code` (google-genai `APIError`). Returns None when no integer status is
    found.

    A 2xx response status does not describe a failure (the Anthropic SDK raises
    `APIStatusError` with the 200 stream's status for an SSE `error` event).
    Recover a status from a structured error body when possible; otherwise
    return None.
    """
    for attr in ("status_code", "code"):
        value = getattr(ex, attr, None)
        if isinstance(value, int):
            if 200 <= value < 300:
                return _status_from_error_body(getattr(ex, "body", None))
            return value
    return None


# Anthropic error `type` -> HTTP status (https://docs.anthropic.com/en/api/errors).
_ANTHROPIC_ERROR_TYPE_STATUS = {
    "invalid_request_error": 400,
    "authentication_error": 401,
    "billing_error": 402,
    "permission_error": 403,
    "not_found_error": 404,
    "conflict_error": 409,
    "request_too_large": 413,
    "rate_limit_error": 429,
    "api_error": 500,
    "timeout_error": 504,
    "overloaded_error": 529,
}


def _status_from_error_body(body: object) -> int | None:
    """Status implied by a provider error body, for errors delivered on a 2xx response."""
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if not isinstance(error, dict):
        return None
    # Google bodies carry a symbolic `status` ("UNAVAILABLE") beside a numeric `code`;
    # take the first usable integer rather than whichever key happens to be present.
    for key in ("status", "code"):
        value = error.get(key)
        if isinstance(value, int) and not (200 <= value < 300):
            return value
    error_type = error.get("type")
    if isinstance(error_type, str):
        return _ANTHROPIC_ERROR_TYPE_STATUS.get(error_type)
    return None


# Provider-specific reset-window headers (used as fallback when Retry-After is absent).
# OpenAI / Groq / Azure OpenAI use the `x-ratelimit-reset-*` family; Anthropic
# uses an `anthropic-ratelimit-*` family of its own (per
# https://docs.anthropic.com/en/api/rate-limits).
_RATELIMIT_RESET_HEADERS = (
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "anthropic-ratelimit-requests-reset",
    "anthropic-ratelimit-tokens-reset",
    "anthropic-ratelimit-input-tokens-reset",
    "anthropic-ratelimit-output-tokens-reset",
)

# OpenAI-style duration shorthand, e.g. "1m30s", "500ms", "1.5s". Units are summed.
_DURATION_UNITS = {
    "ms": 0.001,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)")


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Extract a recommended wait time (seconds) from response headers.

    Resolution order:
      1. `Retry-After` (RFC 9110): delta-seconds or HTTP-date.
      2. Fallback: provider-specific reset-window headers (`x-ratelimit-reset-*`
         from OpenAI/Groq/Azure, `anthropic-ratelimit-*-reset` from Anthropic).
         Each value may be delta-seconds, an OpenAI-style duration string
         (`"1m30s"`, `"500ms"`), or an ISO 8601 timestamp.

    When several reset-window headers are present (e.g. requests and tokens
    both reported), the *largest* is used: a 429 may have been triggered by
    any one dimension, but without parsing the response body we don't know
    which, so the longest reported reset is the conservative choice.

    Returns None when no header is present or values are unparseable, non-finite,
    or negative.
    """
    # case-insensitive lookup
    lower = {k.lower(): v for k, v in headers.items()}

    retry_after = lower.get("retry-after")
    if retry_after is not None:
        seconds = _parse_retry_after_value(retry_after)
        if seconds is not None:
            return seconds

    reset_values = [
        s
        for h in _RATELIMIT_RESET_HEADERS
        if (raw := lower.get(h)) is not None
        and (s := _parse_retry_after_value(raw)) is not None
    ]
    if reset_values:
        return max(reset_values)

    return None


def parse_retry_after_from_exception(ex: BaseException) -> float | None:
    """Best-effort Retry-After / x-ratelimit-reset-* extraction from an exception.

    Walks `ex.response.headers` if present and delegates to `parse_retry_after`.
    Returns None on any failure (missing attributes, parse error). Used by
    every provider's `should_retry` → `RetryDecision.rate_limit` path.
    """
    headers = getattr(getattr(ex, "response", None), "headers", None)
    if headers is None:
        return None
    try:
        return parse_retry_after(headers)
    except Exception:
        return None


def _positive_seconds(seconds: float) -> float | None:
    # `inf > 0` is True, so `Retry-After: inf` — or a value that overflows to
    # inf, like `1e400` — passes a bare positivity check and then poisons any
    # arithmetic it feeds.
    return seconds if seconds > 0 and math.isfinite(seconds) else None


def _parse_retry_after_value(value: str) -> float | None:
    """Parse a single header value into seconds-from-now.

    Accepts delta-seconds, OpenAI-style duration strings (`"1m30s"`),
    HTTP-date (RFC 9110), and ISO 8601 timestamps. Returns None for
    unparseable input or non-finite/non-positive durations.
    """
    value = value.strip()
    if not value:
        return None

    # delta-seconds (most common)
    try:
        seconds = float(value)
        return _positive_seconds(seconds)
    except ValueError:
        pass

    # duration shorthand like "1m30s" / "500ms" / "1.5s" — chain of units
    compact = value.replace(" ", "")
    matches = _DURATION_RE.findall(compact)
    if matches and "".join(a + u for a, u in matches) == compact:
        total = sum(float(a) * _DURATION_UNITS[u] for a, u in matches)
        return _positive_seconds(total)

    # HTTP-date (RFC 9110, e.g. "Wed, 21 Oct 2026 07:28:00 GMT").
    # parsedate_to_datetime can return a *naive* datetime for malformed dates
    # (e.g. ones missing the GMT offset). Coerce to UTC so we can subtract —
    # RFC 9110 mandates HTTP-dates are GMT, and a wrong assumption here just
    # gives us a less-accurate delay rather than a TypeError.
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        dt = None
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = (dt - datetime.now(timezone.utc)).total_seconds()
        return _positive_seconds(seconds)

    # ISO 8601 / RFC 3339 timestamp
    try:
        # fromisoformat in 3.10 doesn't accept trailing 'Z'; normalize
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = (dt - datetime.now(timezone.utc)).total_seconds()
        return _positive_seconds(seconds)
    except ValueError:
        pass

    return None
