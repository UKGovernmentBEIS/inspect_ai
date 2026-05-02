import re
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


# see https://cloud.google.com/storage/docs/retry-strategy
def is_retryable_http_status(status_code: int) -> bool:
    return status_code in [408, 429] or (500 <= status_code < 600)


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
    which — so the conservative cooldown is the longest reset. As a cooldown
    floor this is safe (debounces the controller's next cut without affecting
    request scheduling).

    Returns None when no header is present or values are unparseable / negative.
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


def _parse_retry_after_value(value: str) -> float | None:
    """Parse a single header value into seconds-from-now.

    Accepts delta-seconds, OpenAI-style duration strings (`"1m30s"`),
    HTTP-date (RFC 9110), and ISO 8601 timestamps. Returns None for
    unparseable input or non-positive durations.
    """
    value = value.strip()
    if not value:
        return None

    # delta-seconds (most common)
    try:
        seconds = float(value)
        return seconds if seconds > 0 else None
    except ValueError:
        pass

    # duration shorthand like "1m30s" / "500ms" / "1.5s" — chain of units
    compact = value.replace(" ", "")
    matches = _DURATION_RE.findall(compact)
    if matches and "".join(a + u for a, u in matches) == compact:
        total = sum(float(a) * _DURATION_UNITS[u] for a, u in matches)
        return total if total > 0 else None

    # HTTP-date (RFC 9110, e.g. "Wed, 21 Oct 2026 07:28:00 GMT").
    # parsedate_to_datetime can return a *naive* datetime for malformed dates
    # (e.g. ones missing the GMT offset). Coerce to UTC so we can subtract —
    # RFC 9110 mandates HTTP-dates are GMT, and a wrong assumption here just
    # gives us a less-accurate cooldown rather than a TypeError.
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = (dt - datetime.now(timezone.utc)).total_seconds()
        return seconds if seconds > 0 else None

    # ISO 8601 / RFC 3339 timestamp
    try:
        # fromisoformat in 3.10 doesn't accept trailing 'Z'; normalize
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = (dt - datetime.now(timezone.utc)).total_seconds()
        return seconds if seconds > 0 else None
    except ValueError:
        pass

    return None
