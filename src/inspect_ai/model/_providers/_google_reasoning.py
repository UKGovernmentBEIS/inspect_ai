"""Gemini thinking capabilities, read from the model name.

Shared by the native `google` provider and the `litellm-proxy` provider (for
Google upstreams), so neither needs the other's dependencies. Names that
match no known family (e.g. predeployment codenames) count as the current
frontier.
"""

import re
from typing import Literal

from .._reasoning import (
    clamp_reasoning_effort_to_minimal_low_medium_high,
    effort_to_reasoning_tokens,
)

NON_GENERATIVE_TOKENS = (
    "embedding",
    "imagen",
    "veo",
    "gemma",
    "aqa",
    "learnlm",
    "tts",
)
"""Name tokens of non-generative / non-frontier models, never a codename."""


def gemini_is_latest(family: str) -> bool:
    """Whether a name is a codename (matching no known family) for the frontier.

    The caller decides whether names say anything about the model at all
    (e.g. not for vertex custom endpoints).
    """
    name = family.lower()
    if any(token in name for token in NON_GENERATIVE_TOKENS):
        return False
    # future gemini versions are covered by gemini_3_plus()
    return "gemini" not in name


def gemini_version(family: str) -> tuple[int, ...] | None:
    """Numeric version parsed from a gemini-N[.N] model name (None if absent).

    Only the final path segment is inspected so a vertex resource path
    takes its version from the model, not the project id.
    """
    name = family.rsplit("/", 1)[-1]
    match = re.search(r"gemini-(\d+(?:\.\d+)*)", name)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_gemini(family: str, latest: bool) -> bool:
    return "gemini-" in family or latest


def is_gemini_1_5(family: str) -> bool:
    return "gemini-1.5" in family


def is_gemini_2_0(family: str) -> bool:
    return "gemini-2.0" in family


def is_gemini_2_5(family: str) -> bool:
    return "gemini-2.5" in family


def is_gemini_3(family: str) -> bool:
    return "gemini-3" in family


def gemini_has_thinking_config(family: str, latest: bool) -> bool:
    """Whether the model takes a thinking config (Gemini 2.5 and later)."""
    return (
        is_gemini(family, latest)
        and not is_gemini_1_5(family)
        and not is_gemini_2_0(family)
    )


def gemini_3_plus(family: str, latest: bool) -> bool:
    """Gemini 3 or later, including codenames and unversioned names."""
    return gemini_has_thinking_config(family, latest) and not is_gemini_2_5(family)


def gemini_thinking_only(family: str, latest: bool) -> bool:
    """Whether thinking cannot be disabled (Pro models)."""
    return (is_gemini_2_5(family) or is_gemini_3(family) or latest) and "-pro" in family


def gemini_supports_minimal_thinking(family: str) -> bool:
    """Whether the model accepts thinking_level=MINIMAL.

    True only for releases documented to accept it: Flash 3.0-3.6 and
    Flash-Lite 3.1-3.5. Gemini 3 Pro never has, 3.7 Flash and later reject
    it with a 400, and anything unverified (newer versions, codenames,
    rolling aliases such as gemini-flash-lite-latest) is downgraded to LOW
    rather than risk a 400. https://ai.google.dev/gemini-api/docs/thinking
    """
    version = gemini_version(family)
    name = family.rsplit("/", 1)[-1]
    if version is None or "flash" not in name:
        return False
    low, high = ((3, 1), (3, 6)) if "flash-lite" in name else ((3,), (3, 7))
    return low <= version < high


def gemini_thinking_level(
    effort: str | None, family: str
) -> Literal["minimal", "low", "medium", "high"] | None:
    """The Gemini 3+ thinking level for a `reasoning_effort`.

    `xhigh`/`max` become `high`, and `minimal` becomes `low` for models that
    reject it. None for no effort or `none`.
    """
    level = clamp_reasoning_effort_to_minimal_low_medium_high(effort)
    if level == "minimal" and not gemini_supports_minimal_thinking(family):
        return "low"
    return level


def gemini_thinking_budget(effort: str | None, family: str) -> int | None:
    """The Gemini 2.5 thinking budget for a `reasoning_effort`.

    Inspect's budget for the effort, capped at the model's maximum (32768
    for Pro, 24576 for Flash and Flash-Lite). None for no effort or `none`.
    https://ai.google.dev/gemini-api/docs/thinking#set-budget
    """
    budget = effort_to_reasoning_tokens(effort)
    if budget is None:
        return None
    return min(budget, 32768 if "-pro" in family else 24576)
