"""Unit tests for lookback cache_control placement in the Anthropic provider.

These exercise `add_lookback_cache_control` directly with hand-built
`MessageParam` dicts — no API calls. The function must place
`cache_control: {type: "ephemeral"}` on the second-to-last *cacheable*
content block, skipping `thinking` / `redacted_thinking` blocks and
server-side `fallback` blocks (which the API rejects with
`'<type>.cache_control: Extra inputs are not permitted'`).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from anthropic.types import MessageParam, TextBlockParam

import inspect_ai.model._providers.anthropic as anthropic_module
from inspect_ai.model._generate_config import GenerateConfig
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


def fallback() -> dict[str, Any]:
    # the server-side fallback beta records a refused turn served by another
    # model as a content block; it carries no text and cannot be cached
    return {
        "type": "fallback",
        "from": {"model": "claude-opus-5"},
        "to": {"model": "claude-opus-4-8"},
    }


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
# server-side fallback blocks: must be skipped like thinking blocks
# ---------------------------------------------------------------------------


def test_fallback_at_minus_two_skipped() -> None:
    # a mid-output decline served by the fallback model leaves the assistant
    # message as [text, fallback, text]; the fallback sits exactly where the
    # lookback tag lands and the API rejects cache_control on it
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [text("a"), fallback(), text("b")]},
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == [(0, 0)]
    assert "cache_control" not in msgs[0]["content"][1]


def test_fallback_at_prev_minus_one_skipped() -> None:
    # the fallback block closes the assistant message and the tool result
    # that follows is the only later cacheable block
    msgs: list[dict[str, Any]] = [
        {"role": "assistant", "content": [text("x"), tool_use(), fallback()]},
        {"role": "user", "content": [tool_result()]},
    ]
    add_lookback_cache_control(msgs)
    assert tagged(msgs) == [(0, 1)]
    assert "cache_control" not in msgs[0]["content"][2]


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


@pytest.mark.parametrize("ttl", ["5m", "1h", "auto"])
def test_anthropic_api_accepts_valid_cache_ttl(
    ttl: Literal["5m", "1h", "auto"],
) -> None:
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


# ---------------------------------------------------------------------------
# (g) auto cache ttl: per-sample gap-based escalation to the 1h TTL
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(anthropic_module, "time", clock)
    return clock


def _sample(uuid: str) -> SimpleNamespace:
    return SimpleNamespace(sample_uuid=uuid)


def _set_samples(
    monkeypatch: pytest.MonkeyPatch,
    active: SimpleNamespace | None,
    registry: list[SimpleNamespace] | None = None,
) -> None:
    monkeypatch.setattr(anthropic_module, "sample_active", lambda: active)
    monkeypatch.setattr(
        anthropic_module,
        "active_samples",
        lambda: registry if registry is not None else ([active] if active else []),
    )


def _auto_api(**kwargs: Any) -> AnthropicAPI:
    return AnthropicAPI(model_name="claude-sonnet-4-6", api_key="test-key", **kwargs)


def test_resolve_cache_ttl_no_active_sample(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _auto_api()
    _set_samples(monkeypatch, None)
    assert api._resolve_cache_ttl(GenerateConfig()) is None
    assert api._cache_ttl_state == {}


def test_resolve_cache_ttl_escalates_after_gap_and_sticks(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _auto_api()
    _set_samples(monkeypatch, _sample("s1"))
    assert api._resolve_cache_ttl(GenerateConfig()) is None
    clock.advance(299)
    assert api._resolve_cache_ttl(GenerateConfig()) is None
    clock.advance(301)
    assert api._resolve_cache_ttl(GenerateConfig()) == "1h"
    clock.advance(1)
    assert api._resolve_cache_ttl(GenerateConfig()) == "1h"


def test_resolve_cache_ttl_samples_escalate_independently(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _auto_api()
    s1, s2 = _sample("s1"), _sample("s2")
    _set_samples(monkeypatch, s1, [s1, s2])
    api._resolve_cache_ttl(GenerateConfig())
    _set_samples(monkeypatch, s2, [s1, s2])
    api._resolve_cache_ttl(GenerateConfig())
    clock.advance(301)
    _set_samples(monkeypatch, s1, [s1, s2])
    assert api._resolve_cache_ttl(GenerateConfig()) == "1h"
    _set_samples(monkeypatch, s2, [s1, s2])
    clock.advance(1)
    assert api._resolve_cache_ttl(GenerateConfig()) == "1h"  # 302s gap for s2
    _set_samples(monkeypatch, _sample("s3"), [s1, s2, _sample("s3")])
    assert api._resolve_cache_ttl(GenerateConfig()) is None


@pytest.mark.parametrize("ttl", ["5m", "1h"])
def test_resolve_cache_ttl_pinned_disables_escalation(
    ttl: Literal["5m", "1h"], clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _auto_api(cache_ttl=ttl)
    _set_samples(monkeypatch, _sample("s1"))
    assert api._resolve_cache_ttl(GenerateConfig()) == ttl
    clock.advance(10_000)
    assert api._resolve_cache_ttl(GenerateConfig()) == ttl
    assert api._cache_ttl_state == {}


@pytest.mark.parametrize(
    "model_name",
    ["bedrock/us.anthropic.claude-sonnet-4-6", "vertex/claude-sonnet-4-6@20250929"],
)
def test_resolve_cache_ttl_auto_skips_bedrock_vertex(
    model_name: str, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_helpers.utils import setenv_if_unset

    setenv_if_unset("AWS_REGION", "us-east-1")
    setenv_if_unset("AWS_ACCESS_KEY_ID", "fake")
    setenv_if_unset("AWS_SECRET_ACCESS_KEY", "fake")
    setenv_if_unset("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    setenv_if_unset("ANTHROPIC_VERTEX_REGION", "us-east5")

    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    _set_samples(monkeypatch, _sample("s1"))
    assert api._resolve_cache_ttl(GenerateConfig()) is None
    clock.advance(10_000)
    assert api._resolve_cache_ttl(GenerateConfig()) is None
    assert api._cache_ttl_state == {}


def test_resolve_cache_ttl_auto_skips_batch(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _auto_api()
    _set_samples(monkeypatch, _sample("s1"))
    assert api._resolve_cache_ttl(GenerateConfig(batch=True)) is None
    assert api._cache_ttl_state == {}


def test_resolve_cache_ttl_prunes_completed_samples(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _auto_api()
    s1, s2, s3 = _sample("s1"), _sample("s2"), _sample("s3")
    _set_samples(monkeypatch, s1, [s1, s2])
    api._resolve_cache_ttl(GenerateConfig())
    _set_samples(monkeypatch, s2, [s1, s2])
    api._resolve_cache_ttl(GenerateConfig())
    assert set(api._cache_ttl_state) == {"s1", "s2"}
    # s1 completes; a new sample's first request prunes it
    _set_samples(monkeypatch, s3, [s2, s3])
    api._resolve_cache_ttl(GenerateConfig())
    assert set(api._cache_ttl_state) == {"s2", "s3"}


def test_resolve_cache_ttl_backstop_evicts_oldest(
    clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(anthropic_module, "_CACHE_TTL_STATE_MAX_SAMPLES", 3)
    api = _auto_api()
    samples = [_sample(f"s{i}") for i in range(4)]
    for sample in samples:
        # registry reports all samples live, so the prune keeps them and only
        # the backstop cap bounds the dict
        _set_samples(monkeypatch, sample, samples)
        api._resolve_cache_ttl(GenerateConfig())
    assert set(api._cache_ttl_state) == {"s1", "s2", "s3"}


def test_resolve_cache_ttl_logs_escalation_once(
    clock: _Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _auto_api()
    _set_samples(monkeypatch, _sample("s1"))
    with caplog.at_level(logging.INFO, logger=anthropic_module.logger.name):
        api._resolve_cache_ttl(GenerateConfig())
        clock.advance(301)
        api._resolve_cache_ttl(GenerateConfig())
        clock.advance(301)
        api._resolve_cache_ttl(GenerateConfig())
    escalations = [r for r in caplog.records if "1h cache TTL" in r.message]
    assert len(escalations) == 1


def test_cache_write_ttl_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_samples(monkeypatch, _sample("s1"))
    assert _auto_api(cache_ttl="5m").cache_write_ttl() == "5m"
    assert _auto_api(cache_ttl="1h").cache_write_ttl() == "1h"


def test_cache_write_ttl_auto(clock: _Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _auto_api()
    _set_samples(monkeypatch, None)
    assert api.cache_write_ttl() is None
    _set_samples(monkeypatch, _sample("s1"))
    api._resolve_cache_ttl(GenerateConfig())
    assert api.cache_write_ttl() is None
    clock.advance(301)
    api._resolve_cache_ttl(GenerateConfig())
    assert api.cache_write_ttl() == "1h"


def test_model_api_cache_write_ttl_default() -> None:
    from inspect_ai.model import get_model

    # base ModelAPI falls back to a static cache_ttl attribute (absent → None)
    assert get_model("mockllm/model").api.cache_write_ttl() is None


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
