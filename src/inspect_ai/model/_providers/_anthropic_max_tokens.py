"""max_tokens defaults for Claude models.

Anthropic requires `max_tokens`, so providers that reach Claude choose one
when the user doesn't: a base, raised by the reasoning effort so thinking
doesn't crowd out the reply.
"""

ANTHROPIC_MAX_TOKENS = 32000
"""Default max_tokens for Claude models (other than Claude 3 and 3.5)."""

ANTHROPIC_EFFORT_MAX_TOKENS = {
    "low": 4096,
    "medium": 10000,
    "high": 16000,
    "xhigh": 32000,
    "max": 32000,
}
"""Tokens added to the default for each reasoning effort."""

ANTHROPIC_HIGH_EFFORT_MAX_TOKENS = 64000
"""Minimum max_tokens at xhigh/max effort (Anthropic's migration guide)."""
