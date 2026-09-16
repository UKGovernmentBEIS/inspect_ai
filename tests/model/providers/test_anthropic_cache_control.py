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
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, Literal, cast

import anyio
import pytest
from anthropic.types import MessageParam, TextBlockParam

import inspect_ai.model._providers.anthropic as anthropic_module
from inspect_ai._util.content import ContentText
from inspect_ai.model._chat_message import ChatMessageSystem, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput, ModelUsage
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


@pytest.fixture(autouse=True)
def reset_context_vars() -> Iterator[None]:
    """Keep the per-call context vars from leaking between tests."""
    billed = anthropic_module._cache_write_ttl.set(None)
    last_start = anthropic_module._last_request_start.set(None)
    internal = anthropic_module._anthropic_assistant_internal.set(
        anthropic_module._AssistantInternal()
    )
    yield
    anthropic_module._cache_write_ttl.reset(billed)
    anthropic_module._last_request_start.reset(last_start)
    anthropic_module._anthropic_assistant_internal.reset(internal)


def _sample(uuid: str) -> SimpleNamespace:
    return SimpleNamespace(sample_uuid=uuid)


class _Samples:
    """Activates samples, binding the per-sample assistant internal each owns.

    Escalation state lives on that struct, so switching between samples has to
    swap the binding the way the eval runner does.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._internals: dict[str, anthropic_module._AssistantInternal] = {}

    def activate(self, uuid: str | None) -> SimpleNamespace | None:
        active = SimpleNamespace(sample_uuid=uuid) if uuid is not None else None
        self._monkeypatch.setattr(anthropic_module, "sample_active", lambda: active)
        if uuid is not None:
            anthropic_module._anthropic_assistant_internal.set(
                self._internals.setdefault(uuid, anthropic_module._AssistantInternal())
            )
        return active

    def state(self, uuid: str) -> dict[str, Any]:
        """The escalation state recorded for a sample (empty if none)."""
        internal = self._internals.get(uuid)
        return dict(internal.cache_ttl) if internal is not None else {}


@pytest.fixture
def samples(monkeypatch: pytest.MonkeyPatch) -> _Samples:
    return _Samples(monkeypatch)


def _auto_api(**kwargs: Any) -> AnthropicAPI:
    return AnthropicAPI(model_name="claude-sonnet-4-6", api_key="test-key", **kwargs)


# usage of a response that wrote the prompt cache vs. one the server declined
# to cache (a prefix below the model's minimum cacheable length reports zero
# cache tokens rather than erroring)
_CACHED_USAGE = ModelUsage(
    input_tokens=100, output_tokens=10, input_tokens_cache_write=2000
)
_UNCACHED_USAGE = ModelUsage(input_tokens=100, output_tokens=10)


def _capture_requests(
    api: AnthropicAPI,
    monkeypatch: pytest.MonkeyPatch,
    usage: ModelUsage | None = None,
) -> list[dict[str, Any]]:
    """Record the requests `generate()` issues, short-circuiting the API call."""
    requests: list[dict[str, Any]] = []

    async def fake_perform(
        request: dict[str, Any],
        streaming: bool,
        tools: list[Any],
        config: GenerateConfig,
        pending_tool_uses: Any = None,
        pending_mcp_tool_uses: Any = None,
        span_recorder: Any = None,
    ) -> tuple[dict[str, Any], ModelOutput]:
        requests.append(dict(request))
        output = ModelOutput.from_content(model=api.service_model_name(), content="ok")
        if usage is not None:
            output.usage = usage
        return {}, output

    monkeypatch.setattr(api, "_perform_request_and_continuations", fake_perform)
    return requests


def _resolve(
    api: AnthropicAPI,
    config: GenerateConfig | None = None,
    succeed: bool = True,
    usage: ModelUsage | None = _CACHED_USAGE,
) -> Literal["5m", "1h"] | None:
    """Resolve the TTL as generate() does, recording the refresh on success."""
    resolved = api._resolve_cache_ttl(config or GenerateConfig())
    if succeed:
        api._record_cache_ttl_refresh(resolved, usage)
    return resolved.ttl


def test_resolve_cache_ttl_no_active_sample(clock: _Clock, samples: _Samples) -> None:
    api = _auto_api()
    samples.activate(None)
    assert _resolve(api) is None


def test_resolve_cache_ttl_escalates_after_gap_and_sticks(
    clock: _Clock, samples: _Samples
) -> None:
    api = _auto_api()
    samples.activate("s1")
    assert _resolve(api) is None
    clock.advance(299)
    assert _resolve(api) is None
    clock.advance(301)
    assert _resolve(api) == "1h"
    clock.advance(1)
    assert _resolve(api) == "1h"


def test_resolve_cache_ttl_failed_attempts_do_not_reset_gap(
    clock: _Clock, samples: _Samples
) -> None:
    # a failed attempt (rate limit, connection error) neither writes nor
    # refreshes the server-side cache, so it must not advance the gap baseline
    api = _auto_api()
    samples.activate("s1")
    assert _resolve(api) is None
    clock.advance(250)
    assert _resolve(api, succeed=False) is None  # 250s gap, attempt fails
    clock.advance(250)
    assert _resolve(api) == "1h"  # 500s since the last *successful* request


def test_resolve_cache_ttl_first_attempt_failure_does_not_escalate(
    clock: _Clock, samples: _Samples
) -> None:
    # a sample whose very first attempt fails has nothing cached, so a retry
    # backoff longer than the TTL must not escalate it — that first successful
    # request writes the full prefix either way, and 1h would bill it at 2x
    api = _auto_api()
    samples.activate("s1")
    assert _resolve(api, succeed=False) is None
    clock.advance(400)
    assert _resolve(api) is None
    assert api.cache_write_ttl() is None
    # the successful request established the baseline, so expiry after it does
    clock.advance(301)
    assert _resolve(api) == "1h"


def test_resolve_cache_ttl_uncached_responses_do_not_establish_baseline(
    clock: _Clock, samples: _Samples
) -> None:
    # a prefix below the model's minimum cacheable length is silently not
    # cached (zero cache tokens, no error), so it cannot start a TTL clock
    api = _auto_api()
    samples.activate("s1")
    assert _resolve(api, usage=_UNCACHED_USAGE) is None
    assert samples.state("s1") == {}
    clock.advance(400)
    assert _resolve(api) is None  # first request that actually caches
    clock.advance(301)
    assert _resolve(api) == "1h"


def test_resolve_cache_ttl_samples_escalate_independently(
    clock: _Clock, samples: _Samples
) -> None:
    api = _auto_api()
    samples.activate("s1")
    _resolve(api)
    samples.activate("s2")
    _resolve(api)
    clock.advance(301)
    samples.activate("s1")
    assert _resolve(api) == "1h"
    samples.activate("s2")
    clock.advance(1)
    assert _resolve(api) == "1h"  # 302s gap for s2
    samples.activate("s3")
    assert _resolve(api) is None


def test_resolve_cache_ttl_models_escalate_independently(
    clock: _Clock, samples: _Samples
) -> None:
    # two anthropic models in one sample have separate prompt caches, so one
    # model's gap must not escalate the other's requests
    sonnet = _auto_api()
    opus = AnthropicAPI(model_name="claude-opus-4-8", api_key="test-key")
    samples.activate("s1")
    assert _resolve(sonnet) is None
    clock.advance(301)
    assert _resolve(opus) is None  # opus has no baseline of its own yet
    assert _resolve(sonnet) == "1h"


def test_resolve_cache_ttl_state_is_scoped_to_the_sample(
    clock: _Clock, samples: _Samples
) -> None:
    # state lives on the sample's assistant internal, so it goes away with the
    # sample rather than needing a prune or a cap
    api = _auto_api()
    samples.activate("s1")
    _resolve(api)
    assert set(samples.state("s1")) == {api.service_model_name()}
    assert samples.state("s2") == {}


@pytest.mark.parametrize("ttl", ["5m", "1h"])
def test_resolve_cache_ttl_pinned_disables_escalation(
    ttl: Literal["5m", "1h"], clock: _Clock, samples: _Samples
) -> None:
    api = _auto_api(cache_ttl=ttl)
    samples.activate("s1")
    assert _resolve(api) == ttl
    clock.advance(10_000)
    assert _resolve(api) == ttl
    assert samples.state("s1") == {}


@pytest.mark.parametrize(
    "model_name",
    [
        "bedrock/us.anthropic.claude-sonnet-4-6",
        "vertex/claude-sonnet-4-6@20250929",
        "azure/claude-sonnet-4-6",
    ],
)
def test_resolve_cache_ttl_auto_skips_non_first_party(
    model_name: str, clock: _Clock, samples: _Samples
) -> None:
    from test_helpers.utils import setenv_if_unset

    setenv_if_unset("AWS_REGION", "us-east-1")
    setenv_if_unset("AWS_ACCESS_KEY_ID", "fake")
    setenv_if_unset("AWS_SECRET_ACCESS_KEY", "fake")
    setenv_if_unset("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    setenv_if_unset("ANTHROPIC_VERTEX_REGION", "us-east5")
    setenv_if_unset("AZUREAI_ANTHROPIC_BASE_URL", "https://fake-azure.example.com")

    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    samples.activate("s1")
    assert _resolve(api) is None
    clock.advance(10_000)
    assert _resolve(api) is None
    assert samples.state("s1") == {}


def test_resolve_cache_ttl_auto_skips_batch(clock: _Clock, samples: _Samples) -> None:
    api = _auto_api()
    samples.activate("s1")
    assert _resolve(api, GenerateConfig(batch=True)) is None
    assert samples.state("s1") == {}


def test_resolve_cache_ttl_auto_skips_disabled_cache_prompt(
    clock: _Clock, samples: _Samples
) -> None:
    api = _auto_api()
    samples.activate("s1")
    assert _resolve(api, GenerateConfig(cache_prompt=False)) is None
    assert samples.state("s1") == {}


def test_resolve_cache_ttl_baseline_tracks_last_continuation(
    clock: _Clock, samples: _Samples
) -> None:
    # pause_turn/server-tool continuations re-send the same cache_control, so
    # each refreshes the entry at its own prefill. Measuring the next gap from
    # the start of generate() instead would escalate against a warm cache.
    api = _auto_api()
    samples.activate("s1")
    resolved = api._resolve_cache_ttl(GenerateConfig())
    clock.advance(280)  # a continuation chain running past the 5m mark
    anthropic_module._last_request_start.set(clock.now)
    clock.advance(40)
    api._record_cache_ttl_refresh(resolved, _CACHED_USAGE)
    # 40s since the last continuation prefilled, not 320s since generate() began
    assert _resolve(api) is None


def test_resolve_cache_ttl_logs_escalation_once(
    clock: _Clock,
    samples: _Samples,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _auto_api()
    samples.activate("s1")
    with caplog.at_level(logging.INFO, logger=anthropic_module.logger.name):
        _resolve(api)
        clock.advance(301)
        _resolve(api)
        clock.advance(301)
        _resolve(api)
    escalations = [r for r in caplog.records if "1h cache TTL" in r.message]
    assert len(escalations) == 1


def test_cache_write_ttl_pinned(samples: _Samples) -> None:
    samples.activate("s1")
    assert _auto_api(cache_ttl="5m").cache_write_ttl() == "5m"
    assert _auto_api(cache_ttl="1h").cache_write_ttl() == "1h"


def test_cache_write_ttl_auto(clock: _Clock, samples: _Samples) -> None:
    api = _auto_api()
    samples.activate(None)
    assert api.cache_write_ttl() is None
    samples.activate("s1")
    _resolve(api)
    assert api.cache_write_ttl() is None
    clock.advance(301)
    _resolve(api)
    assert api.cache_write_ttl() == "1h"


def test_cache_write_ttl_batch_call_in_escalated_sample(
    clock: _Clock, samples: _Samples
) -> None:
    # a batched request never escalates, so it is sent at 5m and must be billed
    # at 5m even though the sample around it has escalated
    api = _auto_api()
    samples.activate("s1")
    _resolve(api)
    clock.advance(301)
    assert _resolve(api) == "1h"
    assert api.cache_write_ttl() == "1h"
    assert _resolve(api, GenerateConfig(batch=True)) is None
    assert api.cache_write_ttl() is None


async def test_cache_write_ttl_unaffected_by_concurrent_escalation(
    clock: _Clock, samples: _Samples
) -> None:
    """A request in flight when a sibling escalates is still billed at 5m."""
    api = _auto_api()
    samples.activate("s1")
    _resolve(api)  # establish the baseline

    in_flight_resolved = anyio.Event()
    sibling_escalated = anyio.Event()
    billed: dict[str, str | None] = {}

    async def in_flight() -> None:
        # resolved before the sibling escalates the sample
        assert api._resolve_cache_ttl(GenerateConfig()) is not None
        in_flight_resolved.set()
        await sibling_escalated.wait()
        billed["in_flight"] = api.cache_write_ttl()

    async def sibling() -> None:
        await in_flight_resolved.wait()
        clock.advance(301)
        assert api._resolve_cache_ttl(GenerateConfig()).ttl == "1h"
        billed["sibling"] = api.cache_write_ttl()
        sibling_escalated.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(in_flight)
        tg.start_soon(sibling)

    assert billed["sibling"] == "1h"
    assert billed["in_flight"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("escalated", [False, True])
async def test_auto_cache_ttl_threads_into_request(
    escalated: bool, clock: _Clock, samples: _Samples, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto cache TTL threads the resolved ttl through the request.

    An escalated sample's requests carry ttl "1h" on the top-level
    cache_control and every breakpoint, while a non-escalated sample's requests
    omit the ttl key entirely (byte-identical to the pre-auto wire format).
    """
    api = _auto_api()
    samples.activate("s1")
    requests = _capture_requests(api, monkeypatch)
    if escalated:
        _resolve(api)
        clock.advance(301)

    await api.generate(
        input=[
            ChatMessageSystem(content="be helpful"),
            ChatMessageUser(
                content=[
                    ContentText(text="context block"),
                    ContentText(text="question block"),
                ]
            ),
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(cache_prompt=True),
    )

    request = requests[0]
    controls = [request["cache_control"], request["system"][-1]["cache_control"]]
    for message in request["messages"]:
        if isinstance(message["content"], list):
            controls.extend(
                block["cache_control"]
                for block in message["content"]
                if isinstance(block, dict) and "cache_control" in block
            )
    assert len(controls) >= 3  # top-level, system, lookback message block
    expected = (
        {"type": "ephemeral", "ttl": "1h"} if escalated else {"type": "ephemeral"}
    )
    assert all(c == expected for c in controls)


@pytest.mark.anyio
async def test_auto_cache_ttl_escalates_via_generate(
    clock: _Clock, samples: _Samples, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A >5m gap between a sample's generate() calls escalates to the 1h TTL."""
    api = _auto_api()
    samples.activate("s1")
    requests = _capture_requests(api, monkeypatch, usage=_CACHED_USAGE)

    async def call() -> None:
        await api.generate(
            input=[ChatMessageUser(content="hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(cache_prompt=True),
        )

    await call()
    clock.advance(250)
    await call()
    clock.advance(301)
    await call()

    assert requests[0]["cache_control"] == {"type": "ephemeral"}
    assert requests[1]["cache_control"] == {"type": "ephemeral"}
    assert requests[2]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_model_api_cache_write_ttl_default() -> None:
    from inspect_ai.model import get_model

    # providers that do not bill cache writes by TTL report None
    assert get_model("mockllm/cache-write-ttl-default").api.cache_write_ttl() is None


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
