"""Recognize `reasoning_effort` rejections from a LiteLLM proxy.

LiteLLM checks `reasoning_effort` against its own model map before calling the
upstream provider, and answers 400 when the model does not take the parameter
or the value. Values it forwards can still be rejected by the upstream
provider (e.g. OpenAI for `max` on gpt-5). Both kinds of message name what was
rejected, so the provider can lower the value (or drop it) and retry rather
than replicating LiteLLM's per-model rules, which change between versions.
The same applies to the `thinking` parameter the provider sends to Claude.
"""

import re
from typing import Literal, NamedTuple

EFFORT_LADDER = ("minimal", "low", "medium", "high", "xhigh", "max")
"""Reasoning effort values from weakest to strongest (`none` is not on it)."""

_PARAMETER_REJECTED = (
    # chat completions
    re.compile(r"does not support parameters: \[[^\]]*'reasoning_effort'"),
    # Responses, for models LiteLLM's map does not mark as reasoning models
    re.compile(r"doesn't support `reasoning(?:\.effort|_effort)`"),
)
_VALUE_REJECTED = (
    # LiteLLM, OpenAI and Azure models
    re.compile(r"reasoning_effort=(\w+) is not supported"),
    # LiteLLM, Gemini models
    re.compile(r"Invalid `reasoning_effort`: '(\w+)'"),
    # LiteLLM, Anthropic models
    re.compile(r"effort='(\w+)' is not supported"),
    # OpenAI, for values LiteLLM forwards: chat completions
    re.compile(r"Unsupported value: 'reasoning_effort' does not support '(\w+)'"),
    # OpenAI, Responses (the parameter is named only in the error's `param`)
    re.compile(
        r"Unsupported value: '(\w+)' is not supported with the .*"
        r"\"param\": \"reasoning\.effort\"",
        re.DOTALL,
    ),
)


class EffortRejection(NamedTuple):
    kind: Literal["parameter", "value"]
    """Whether the model takes no `reasoning_effort` or not this value."""


def rejected_effort(message: str, sent: str) -> EffortRejection | None:
    """Classify an error message as a rejection of the effort `sent`, if it is one.

    A value rejection counts only when the value it names is the one sent.
    """
    if any(pattern.search(message) for pattern in _PARAMETER_REJECTED):
        return EffortRejection(kind="parameter")
    for pattern in _VALUE_REJECTED:
        match = pattern.search(message)
        if match and match.group(1) == sent:
            return EffortRejection(kind="value")
    return None


_THINKING_REJECTED = (
    # LiteLLM, for models its map gives no thinking support
    re.compile(r"does not support parameters: \[[^\]]*'thinking'"),
    # Anthropic, for a model without adaptive thinking
    re.compile(r"adaptive thinking is not supported"),
    # Anthropic, for a `display` it does not take (e.g. "thinking.adaptive.display:
    # Input should be ...")
    re.compile(r"thinking\.(?:\w+\.)?display\b"),
)


def rejected_thinking(message: str) -> bool:
    """Whether an error message rejects the adaptive `thinking` the provider sent."""
    return any(pattern.search(message) for pattern in _THINKING_REJECTED)


def next_effort(requested: str, rejected: set[str]) -> str | None:
    """The effort to send instead of `requested`, or None to send none.

    The strongest accepted value at or below the requested one, otherwise the
    weakest above it. An unsupported `none` (or an unknown value) is dropped,
    leaving the model's default.
    """
    if requested not in EFFORT_LADDER:
        return None
    rank = EFFORT_LADDER.index(requested)
    candidates = [e for e in EFFORT_LADDER if e not in rejected]
    below = [e for e in candidates if EFFORT_LADDER.index(e) <= rank]
    if below:
        return below[-1]
    return candidates[0] if candidates else None
