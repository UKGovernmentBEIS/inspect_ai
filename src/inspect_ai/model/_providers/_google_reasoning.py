"""Gemini thinking capabilities, read from the model name.

Shared by the native `google` provider and the `litellm-proxy` provider (for
Google upstreams), so neither needs the other's dependencies. Names that
match no known family (e.g. predeployment codenames) count as the current
frontier.
"""

import re
from collections import Counter
from typing import Literal

from pydantic import JsonValue

from inspect_ai._util.content import Content, ContentReasoning
from inspect_ai.model._call_tools import repeated_call_ids
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._providers._google_computer_use_name import (
    GEMINI_COMPUTER_ACTIONS,
)
from inspect_ai.tool._tool_call import ToolCall

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


def _model_segment(family: str) -> str:
    return family.rsplit("/", 1)[-1]


def gemini_version(family: str) -> tuple[int, ...] | None:
    """Numeric version parsed from a gemini-N[.N] model name (None if absent).

    Only the final path segment is inspected so a vertex resource path
    takes its version from the model, not the project id.
    """
    name = _model_segment(family)
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
    """Whether thinking cannot be disabled (Pro models, Gemini 2.5 and later).

    Pro names newer than those verified (e.g. a future gemini-4-pro) count as
    thinking-only, so disabling thinking warns rather than risking a 400.
    Only the final path segment is checked, so a vertex project id such as
    my-project does not make a model thinking-only.
    """
    pro = "-pro" in _model_segment(family)
    return gemini_has_thinking_config(family, latest) and pro


def gemini_supports_minimal_thinking(family: str) -> bool:
    """Whether the model accepts thinking_level=MINIMAL.

    True only for releases documented to accept it: Flash 3.0-3.6 and
    Flash-Lite 3.1-3.5. Gemini 3 Pro never has, 3.7 Flash and later reject
    it with a 400, and anything unverified (newer versions, codenames,
    rolling aliases such as gemini-flash-lite-latest) is downgraded to LOW
    rather than risk a 400. https://ai.google.dev/gemini-api/docs/thinking
    """
    version = gemini_version(family)
    name = _model_segment(family)
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
    return min(budget, 32768 if "-pro" in _model_segment(family) else 24576)


GEMINI_FUNCTION_CALL_ID_KEY = "gemini_function_call_id"
"""The `ContentReasoning.internal` key naming the call a reasoning anchor is for."""

GEMINI_COMPUTER_ACTION_KEY = "gemini_computer_action"
"""The `ContentReasoning.internal` key naming the Gemini computer action its call was sent as."""

GEMINI_FUNCTION_KEY = "gemini_function"
"""The `ContentReasoning.internal` key naming the function a reasoning anchor's call was parsed as."""


def gemini_anchor_fits(anchor: ContentReasoning, call: ToolCall) -> bool:
    """Whether the reasoning anchor naming `call`'s id is for a call to its function.

    An anchor's signature and position are its call's. A call to another
    function under the id (a filter changed the function and kept the id)
    replays without them, as does a call named by an anchor without a function
    (`gemini_anchors_with_functions` derives the function of one logged before
    it was recorded).
    """
    function = (
        anchor.internal.get(GEMINI_FUNCTION_KEY)
        if isinstance(anchor.internal, dict)
        else None
    )
    return (
        call.type == "function"
        and isinstance(function, str)
        and function == call.function
    )


def gemini_anchors_with_functions(
    message: ChatMessageAssistant,
) -> list[Content] | None:
    """The message's content with the function of each anchor logged without one.

    An anchor parsed before its function was recorded (in a log, cache entry
    or checkpoint written by an earlier version) is for the call it names in
    the message holding it: the k-th anchor naming an id is for the k-th call
    under the id. Derived from an output as generated, before a filter can
    change its calls (`derive_recorded_functions`), and from a logged message,
    which holds its own calls.

    Those versions gave a computer call an id of its own, naming the action
    (`click_at_<uuid>`), and its anchor the provider's id. Anchors naming no
    call are for the computer calls of that form no anchor names, in order,
    when there are as many of each; the anchor then names its call, as one
    parsed now does. An anchor with no call to derive from keeps no function,
    so it fits no call. None when every anchor has its function.
    """
    if isinstance(message.content, str) or not any(
        _anchor_call_id(part) is not None
        and GEMINI_FUNCTION_KEY not in _anchor_internal(part)
        for part in message.content
    ):
        return None
    calls: dict[str, list[ToolCall]] = {}
    for call in message.tool_calls or []:
        calls.setdefault(call.id, []).append(call)
    named: Counter[str] = Counter()
    orphans: list[int] = []
    content = list(message.content)
    for i, part in enumerate(content):
        call_id = _anchor_call_id(part)
        if call_id is None:
            continue
        nth = named[call_id]
        named[call_id] += 1
        internal = _anchor_internal(part)
        if GEMINI_FUNCTION_KEY in internal:
            continue
        under_id = calls.get(call_id, [])
        if nth < len(under_id):
            content[i] = part.model_copy(
                update={
                    "internal": {
                        **internal,
                        GEMINI_FUNCTION_KEY: under_id[nth].function,
                    }
                }
            )
        elif not under_id:
            orphans.append(i)
    computer_calls = [
        call
        for call in message.tool_calls or []
        if call.function == "computer"
        and call.type == "function"
        and call.id not in named
        and _legacy_computer_action(call.id) is not None
    ]
    if orphans and len(orphans) == len(computer_calls):
        for i, call in zip(orphans, computer_calls):
            anchor = content[i]
            assert isinstance(anchor, ContentReasoning)
            content[i] = anchor.model_copy(
                update={
                    "internal": {
                        **_anchor_internal(anchor),
                        GEMINI_FUNCTION_CALL_ID_KEY: call.id,
                        GEMINI_FUNCTION_KEY: "computer",
                        GEMINI_COMPUTER_ACTION_KEY: _legacy_computer_action(call.id),
                    }
                }
            )
    return content


def _legacy_computer_action(call_id: str) -> str | None:
    """The action a computer call's id names (`click_at_<uuid>`), if any."""
    action = call_id.rsplit("_", 1)[0]
    return action if action in GEMINI_COMPUTER_ACTIONS else None


def _anchor_call_id(part: Content) -> str | None:
    """The call a reasoning anchor names, or None for other content."""
    if isinstance(part, ContentReasoning) and isinstance(part.internal, dict):
        call_id = part.internal.get(GEMINI_FUNCTION_CALL_ID_KEY)
        if isinstance(call_id, str):
            return call_id
    return None


def _anchor_internal(anchor: Content) -> dict[str, JsonValue]:
    assert isinstance(anchor, ContentReasoning) and isinstance(anchor.internal, dict)
    return anchor.internal


def gemini_computer_actions(message: ChatMessageAssistant) -> dict[str, str]:
    """The Gemini computer action each of the message's calls was sent as, by call id.

    From the calls' reasoning anchors, so it follows a call whose id changes
    with its anchors. None for an id several calls or anchors share.
    """
    if isinstance(message.content, str):
        return {}
    shared = gemini_shared_call_ids(message)
    actions: dict[str, str] = {}
    for part in message.content:
        if isinstance(part, ContentReasoning) and isinstance(part.internal, dict):
            call_id = part.internal.get(GEMINI_FUNCTION_CALL_ID_KEY)
            action = part.internal.get(GEMINI_COMPUTER_ACTION_KEY)
            if (
                isinstance(call_id, str)
                and isinstance(action, str)
                and call_id not in shared
            ):
                actions[call_id] = action
    return actions


def gemini_shared_call_ids(message: ChatMessageAssistant) -> set[str]:
    """The ids several of the message's calls, or several of its reasoning anchors, name.

    A thought signature anchored to such an id can't be told apart by call (a
    response filter may have kept one of the calls), so it goes on none.
    """
    anchored: Counter[str] = Counter()
    if not isinstance(message.content, str):
        for part in message.content:
            if isinstance(part, ContentReasoning) and isinstance(part.internal, dict):
                call_id = part.internal.get(GEMINI_FUNCTION_CALL_ID_KEY)
                if isinstance(call_id, str):
                    anchored[call_id] += 1
    return repeated_call_ids(message.tool_calls or []) | {
        call_id for call_id, count in anchored.items() if count > 1
    }
