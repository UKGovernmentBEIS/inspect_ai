"""Unit tests for lookback cache_control placement in the Anthropic provider.

These exercise `add_lookback_cache_control` directly with hand-built
`MessageParam` dicts — no API calls. The function must place
`cache_control: {type: "ephemeral"}` on the second-to-last *cacheable*
content block, skipping `thinking` / `redacted_thinking` blocks (which the
API rejects with `'thinking.cache_control: Extra inputs are not permitted'`).
"""

from __future__ import annotations

from typing import Any, Literal, cast

import pytest
from anthropic.types import MessageParam, TextBlockParam

from inspect_ai.model._providers.anthropic import (
    AnthropicAPI,
    add_cache_control,
    cache_control_param,
)
from inspect_ai.model._providers.anthropic import (
    add_lookback_cache_control as _add_lookback_cache_control,
)

CACHE = {"type": "ephemeral"}


def add_lookback_cache_control(
    msgs: list[dict[str, Any]], ttl: Literal["5m", "1h"] | None = None
) -> None:
    _add_lookback_cache_control(cast(list[MessageParam], msgs), ttl)


def text(s: str) -> dict[str, Any]:
    return {"type": "text", "text": s}


def thinking(s: str = "hmm") -> dict[str, Any]:
    return {"type": "thinking", "thinking": s, "signature": "sig"}


def redacted() -> dict[str, Any]:
    return {"type": "redacted_thinking", "data": "xxx"}


def tool_use(tid: str = "t1") -> dict[str, Any]:
    return {"type": "tool_use", "id": tid, "name": "f", "input": {}}


def tool_result(tid: str = "t1") -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tid, "content": "ok"}


def tagged(msgs: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Return (msg_idx, block_idx) for every block carrying cache_control."""
    out: list[tuple[int, int]] = []
    for mi, m in enumerate(msgs):
        if isinstance(m["content"], list):
            for bi, b in enumerate(m["content"]):
                if isinstance(b, dict) and "cache_control" in b:
                    out.append((mi, bi))
    return out


# ---------------------------------------------------------------------------
# (a) no-thinking cases: must behave identically to the original logic
#     original: last[-2] if last is list len>=2, else prev[-1] if prev is list
# ---------------------------------------------------------------------------


def test_no_thinking_last_message_two_blocks_tags_second_to_last() -> None:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": [text("a"), text("b")]}]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == [(0, 0)]
    assert msgs[0]["content"][0]["cache_control"] == CACHE


def test_no_thinking_last_message_three_blocks_tags_index_minus_two() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": [text("a"), text("b"), text("c")]}
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == [(0, 1)]


def test_no_thinking_last_single_block_falls_back_to_prev_last() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [text("x"), tool_use()]},
        {"role": "user", "content": [tool_result()]},
    ]
    add_lookback_cache_control(msgs)
    # original: last has len 1 → prev[-1]
    assert tagged(msgs) == [(0, 1)]


def test_no_thinking_last_string_content_tags_prev_last() -> None:
    # plain-string user content is produced by message_param() for str input
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [text("x"), text("y")]},
        {"role": "user", "content": "hello"},
    ]
    add_lookback_cache_control(msgs)
    # original: last not a list → prev[-1]
    assert tagged(msgs) == [(0, 1)]


# ---------------------------------------------------------------------------
# (b)/(c)/(d) thinking blocks present: must skip them
# ---------------------------------------------------------------------------


def test_thinking_at_minus_two_skipped() -> None:
    # the motivating bug: last[-2] is a thinking block
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [text("a"), thinking(), text("b")]},
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == [(0, 0)]
    assert "cache_control" not in msgs[0]["content"][1]


def test_redacted_thinking_at_minus_two_skipped() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [text("a"), redacted(), text("b")]},
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == [(0, 0)]


def test_thinking_at_prev_minus_one_skipped() -> None:
    # last has 1 block → fall back to prev; prev[-1] is thinking → skip to prev[-2]
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [text("x"), thinking()]},
        {"role": "user", "content": [text("q")]},
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == [(0, 0)]


def test_all_thinking_last_message_falls_back_to_earlier_message() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": [text("u1"), text("u2")]},
        {"role": "assistant", "content": [thinking(), redacted()]},
    ]
    add_lookback_cache_control(msgs)
    # last msg contributes 0 cacheable blocks → 2nd-to-last cacheable is u1
    assert tagged(msgs) == [(0, 0)]


def test_thinking_then_tool_use_tags_prev_tool_result() -> None:
    # realistic interleaved-thinking agent loop
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": [text("task")]},
        {"role": "assistant", "content": [thinking(), tool_use("t1")]},
        {"role": "user", "content": [tool_result("t1")]},
        {"role": "assistant", "content": [thinking(), tool_use("t2")]},
    ]
    add_lookback_cache_control(msgs)
    # last cacheable = tool_use t2; second-to-last cacheable = tool_result t1
    assert tagged(msgs) == [(2, 0)]


# ---------------------------------------------------------------------------
# (e) edge cases
# ---------------------------------------------------------------------------


def test_single_cacheable_block_no_tag() -> None:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": [text("only")]}]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == []


def test_single_string_message_no_tag() -> None:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "only"}]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == []


def test_second_cacheable_is_string_no_tag() -> None:
    # last has 1 block, prev is bare string → can't tag a string, stop
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": "sys-ish"},
        {"role": "user", "content": [text("q")]},
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == []


def test_empty_messages_noop() -> None:
    msgs: list[dict[str, Any]] = []
    add_lookback_cache_control(msgs)
    assert msgs == []


def test_only_thinking_blocks_no_tag() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [thinking(), redacted(), thinking()]},
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == []


# ---------------------------------------------------------------------------
# (f) cache ttl
# ---------------------------------------------------------------------------


def test_cache_control_param_default_omits_ttl() -> None:
    assert cache_control_param(None) == {"type": "ephemeral"}


@pytest.mark.parametrize("ttl", ["5m", "1h"])
def test_cache_control_param_includes_ttl(ttl: Literal["5m", "1h"]) -> None:
    assert cache_control_param(ttl) == {"type": "ephemeral", "ttl": ttl}


def test_add_cache_control_default_omits_ttl() -> None:
    block = TextBlockParam(type="text", text="hello")
    add_cache_control(block)
    assert block["cache_control"] == {"type": "ephemeral"}


def test_add_cache_control_with_ttl() -> None:
    block = TextBlockParam(type="text", text="hello")
    add_cache_control(block, "1h")
    assert block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_lookback_threads_ttl() -> None:
    msgs: list[dict[str, Any]] = [{"role": "user", "content": [text("a"), text("b")]}]
    add_lookback_cache_control(msgs, "1h")
    assert msgs[0]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


@pytest.mark.parametrize("ttl", ["5m", "1h"])
def test_anthropic_api_accepts_valid_cache_ttl(ttl: Literal["5m", "1h"]) -> None:
    api = AnthropicAPI(
        model_name="claude-sonnet-4-6", api_key="test-key", cache_ttl=ttl
    )
    assert api.cache_ttl == ttl


def test_anthropic_api_rejects_invalid_cache_ttl() -> None:
    with pytest.raises(ValueError, match="cache_ttl"):
        AnthropicAPI(
            model_name="claude-sonnet-4-6",
            api_key="test-key",
            cache_ttl=cast(Any, "2h"),
        )


@pytest.mark.parametrize("block_type", ["thinking", "redacted_thinking"])
def test_never_tags_thinking_block(block_type: str) -> None:
    blk = thinking() if block_type == "thinking" else redacted()
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": [text("a")]},
        {"role": "assistant", "content": [blk, blk, text("b"), blk]},
    ]
    add_lookback_cache_control(msgs)
    for m in msgs:
        for b in m["content"]:
            if isinstance(b, dict) and b.get("type") in (
                "thinking",
                "redacted_thinking",
            ):
                assert "cache_control" not in b
