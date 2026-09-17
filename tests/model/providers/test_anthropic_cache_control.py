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
from uuid import uuid4

import anyio
import pytest
from anthropic.types import MessageParam, TextBlockParam
from test_helpers.utils import skip_if_no_anthropic

import inspect_ai.model._providers.anthropic as anthropic_module
from inspect_ai._util.content import Content, ContentText
from inspect_ai.model import get_model
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
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
from inspect_ai.tool import ToolCall, ToolInfo
from inspect_ai.tool._tool_params import ToolParam, ToolParams

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


# ---------------------------------------------------------------------------
# (h) explicit breakpoints (ContentText.cache_breakpoint)
# ---------------------------------------------------------------------------


async def _generate_request(
    api: AnthropicAPI,
    input: list[ChatMessage],
    config: GenerateConfig,
    monkeypatch: pytest.MonkeyPatch,
    tools: list[ToolInfo] | None = None,
) -> dict[str, Any]:
    """The single request `generate()` issues for `input` under `config`."""
    requests = _capture_requests(api, monkeypatch)
    await api.generate(
        input=input, tools=tools or [], tool_choice="auto", config=config
    )
    assert len(requests) == 1
    return requests[0]


def _rubric_then_items(*, breakpoint: bool, items: int = 1) -> list[ChatMessage]:
    """A judge-shaped user turn: a fixed rubric block, then varying item blocks."""
    content: list[Content] = [ContentText(text="rubric", cache_breakpoint=breakpoint)]
    content.extend(ContentText(text=f"item-{i}") for i in range(items))
    return [ChatMessageUser(content=content)]


@pytest.mark.anyio
async def test_default_caching_tags_lookback_and_auto_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _generate_request(
        _auto_api(),
        [ChatMessageSystem(content="system")] + _rubric_then_items(breakpoint=False),
        GenerateConfig(),
        monkeypatch,
    )
    assert request["cache_control"] == CACHE
    assert request["system"][-1]["cache_control"] == CACHE
    assert tagged(request["messages"]) == [(0, 0)]


@pytest.mark.anyio
async def test_cache_breakpoint_replaces_lookback_and_auto_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # three blocks: lookback alone would tag the middle (varying) block
    request = await _generate_request(
        _auto_api(),
        _rubric_then_items(breakpoint=True, items=2),
        GenerateConfig(),
        monkeypatch,
    )
    assert "cache_control" not in request
    assert tagged(request["messages"]) == [(0, 0)]
    assert request["messages"][0]["content"][0]["cache_control"] == CACHE


@pytest.mark.anyio
async def test_cache_breakpoint_keeps_system_breakpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _generate_request(
        _auto_api(),
        [ChatMessageSystem(content="system")] + _rubric_then_items(breakpoint=True),
        GenerateConfig(),
        monkeypatch,
    )
    assert "cache_control" not in request
    assert request["system"][-1]["cache_control"] == CACHE
    assert tagged(request["messages"]) == [(0, 0)]


@pytest.mark.anyio
async def test_cache_breakpoint_carries_request_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _generate_request(
        _auto_api(cache_ttl="1h"),
        _rubric_then_items(breakpoint=True),
        GenerateConfig(),
        monkeypatch,
    )
    assert request["messages"][0]["content"][0]["cache_control"] == {
        "type": "ephemeral",
        "ttl": "1h",
    }


@pytest.mark.anyio
async def test_cache_breakpoint_stripped_when_cache_prompt_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _generate_request(
        _auto_api(),
        _rubric_then_items(breakpoint=True),
        GenerateConfig(cache_prompt=False),
        monkeypatch,
    )
    assert "cache_control" not in request
    assert tagged(request["messages"]) == []


@pytest.mark.anyio
async def test_cache_breakpoint_keeps_tools_breakpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _auto_api()
    requests = _capture_requests(api, monkeypatch)
    await api.generate(
        input=[ChatMessageSystem(content="system")]
        + _rubric_then_items(breakpoint=True),
        tools=[ToolInfo(name="f", description="a tool")],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    request = requests[0]
    assert "cache_control" not in request
    assert request["system"][-1]["cache_control"] == CACHE
    assert request["tools"][-1]["cache_control"] == CACHE
    assert tagged(request["messages"]) == [(0, 0)]


@pytest.mark.anyio
async def test_system_only_mark_suppresses_message_lookback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller mark on the system block alone must suppress the automatic message-lookback marker.

    A lookback point on the variable tool result would write past the
    caller's chosen boundary.
    """
    input: list[ChatMessage] = [
        ChatMessageSystem(content=[ContentText(text="stable", cache_breakpoint=True)]),
        ChatMessageUser(content="task"),
        ChatMessageAssistant(
            content="", tool_calls=[ToolCall(id="t1", function="f", arguments={})]
        ),
        ChatMessageTool(content="variable result", tool_call_id="t1", function="f"),
    ]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    assert request["system"][-1]["cache_control"] == CACHE
    assert tagged(request["messages"]) == []


@pytest.mark.anyio
async def test_four_system_marks_suppress_message_lookback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four explicit system marks plus a two-block user message must total exactly 4 real markers.

    Not 5 (four system marks plus a lookback point on the user content the
    budget calculation didn't count).
    """
    system_blocks: list[Content] = [
        ContentText(text=f"system-{i}", cache_breakpoint=True) for i in range(4)
    ]
    input: list[ChatMessage] = [
        ChatMessageSystem(content=system_blocks),
        ChatMessageUser(content=[ContentText(text="a"), ContentText(text="b")]),
    ]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    assert len(request["system"]) == 4
    assert all(block["cache_control"] == CACHE for block in request["system"])
    assert tagged(request["messages"]) == []


@pytest.mark.anyio
async def test_marked_mid_conversation_reminder_forces_whole_layout_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mark flattened into a `<system-reminder>` must not be silently dropped.

    Models without mid-conversation support convert a mid-conversation
    system message into a `<system-reminder>` user turn. If that message
    carried an explicit mark, it must not be silently dropped while a
    surviving user mark is still honored — the whole layout falls back to
    normal automatic caching instead of a partial explicit layout.
    """
    input: list[ChatMessage] = [
        ChatMessageUser(content=[ContentText(text="rubric", cache_breakpoint=True)]),
        ChatMessageAssistant(content="ok"),
        ChatMessageSystem(
            content=[ContentText(text="mid-system", cache_breakpoint=True)]
        ),
        ChatMessageUser(content="question"),
    ]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    # whole-request fallback: the user's own mark is discarded too, and
    # normal automatic (top-level) caching takes over instead
    assert request["cache_control"] == CACHE
    assert "cache_control" not in request["messages"][0]["content"][0]


def _input_with_marks(marked: int) -> list[ChatMessage]:
    content: list[Content] = [
        ContentText(text=f"doc-{i}", cache_breakpoint=True) for i in range(marked)
    ]
    content.append(ContentText(text="item"))
    return [ChatMessageSystem(content="system"), ChatMessageUser(content=content)]


@pytest.mark.anyio
async def test_cache_breakpoints_over_budget_falls_back_to_automatic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # system + tools + 2 explicit markers is the ceiling
    api = _auto_api()
    requests = _capture_requests(api, monkeypatch)
    tools = [ToolInfo(name="f", description="a tool")]

    await api.generate(
        input=_input_with_marks(2),
        tools=tools,
        tool_choice="auto",
        config=GenerateConfig(),
    )
    # 5 explicit marks alone exceed the budget even with every automatic
    # marker dropped. Anthropic rejects a request over the budget, so this
    # must fall back to normal automatic caching for the whole request
    # rather than raising or sending a truncated explicit layout.
    await api.generate(
        input=_input_with_marks(5),
        tools=tools,
        tool_choice="auto",
        config=GenerateConfig(),
    )
    request = requests[-1]
    # normal automatic caching: lookback marks the second-to-last cacheable
    # block (doc-4, index 4 of 6), not any of the caller's discarded marks
    assert tagged(request["messages"]) == [(0, 4)]
    assert request["system"][-1]["cache_control"] == CACHE
    assert request["tools"][-1]["cache_control"] == CACHE


@pytest.mark.anyio
async def test_explicit_breakpoints_take_priority_over_automatic_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 3 explicit marks + system + tools = 5, one over budget. The caller's
    # explicit marks are kept; the automatic tools marker is dropped instead
    # of rejecting the request.
    tools = [ToolInfo(name="f", description="a tool")]
    api = _auto_api()
    requests = _capture_requests(api, monkeypatch)
    await api.generate(
        input=_input_with_marks(3),
        tools=tools,
        tool_choice="auto",
        config=GenerateConfig(),
    )
    request = requests[0]
    assert "cache_control" not in request["tools"][-1]
    assert request["system"][-1]["cache_control"] == CACHE
    assert tagged(request["messages"]) == [(0, 0), (0, 1), (0, 2)]


def _tool_result_input() -> list[ChatMessage]:
    """A tool loop whose result carries a breakpoint, then a follow-up question."""
    return [
        ChatMessageUser(content="task"),
        ChatMessageAssistant(
            content="",
            tool_calls=[ToolCall(id="t1", function="f", arguments={})],
        ),
        ChatMessageTool(
            content=[ContentText(text="big document", cache_breakpoint=True)],
            tool_call_id="t1",
            function="f",
        ),
        ChatMessageUser(content="question"),
    ]


def _tool_result_positions(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [
        (mi, bi)
        for mi, message in enumerate(messages)
        if isinstance(message["content"], list)
        for bi, block in enumerate(message["content"])
        if block.get("type") == "tool_result"
    ]


@pytest.mark.anyio
async def test_cache_breakpoint_in_tool_result_falls_back_to_automatic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a marked tool result is not supported (conservative fallback, not
    # every placement): the whole request falls back to normal automatic
    # caching rather than moving the mark to the enclosing tool_result block.
    input = _tool_result_input()
    marked_request = await _generate_request(
        _auto_api(), input, GenerateConfig(), monkeypatch
    )
    unmarked_request = await _generate_request(
        _auto_api(), _strip_marks(input), GenerateConfig(), monkeypatch
    )
    _assert_matches_hints_removed_baseline(marked_request, unmarked_request)
    # the mark itself was discarded: the tool_result's inner content block
    # never carries cache_control (not widened there). Whether the outer
    # tool_result block is tagged is up to normal automatic-caching lookback
    # (already asserted identical to the unmarked baseline above).
    messages = marked_request["messages"]
    tool_result = messages[_tool_result_positions(messages)[0][0]]["content"][
        _tool_result_positions(messages)[0][1]
    ]
    assert all("cache_control" not in block for block in tool_result["content"])


@pytest.mark.anyio
async def test_cache_prompt_false_strips_hoisted_tool_result_breakpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _generate_request(
        _auto_api(),
        _tool_result_input(),
        GenerateConfig(cache_prompt=False),
        monkeypatch,
    )
    assert "cache_control" not in request
    messages = request["messages"]
    assert tagged(messages) == []
    (position,) = _tool_result_positions(messages)
    tool_result = messages[position[0]]["content"][position[1]]
    assert all("cache_control" not in block for block in tool_result["content"])


def test_content_text_cache_breakpoint_round_trips() -> None:
    block = ContentText(text="rubric", cache_breakpoint=True)
    assert ContentText.model_validate_json(block.model_dump_json()) == block
    # logs written before the field existed load with it unset
    legacy = ContentText.model_validate({"type": "text", "text": "rubric"})
    assert legacy.cache_breakpoint is None


def _non_final_tool_result_input(*, breakpoint: bool) -> list[ChatMessage]:
    return [
        ChatMessageUser(content="task"),
        ChatMessageAssistant(
            content="",
            tool_calls=[ToolCall(id="t1", function="f", arguments={})],
        ),
        ChatMessageTool(
            content=[
                ContentText(text="stable prefix", cache_breakpoint=breakpoint),
                ContentText(text="varying suffix"),
            ],
            tool_call_id="t1",
            function="f",
        ),
        ChatMessageUser(content="question"),
    ]


@pytest.mark.anyio
async def test_cache_breakpoint_in_non_final_tool_result_block_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a mark on a non-final block of a multi-block tool result can't be
    # honored at its requested position (Anthropic can only mark the whole
    # result); the whole request must fall back to normal automatic caching
    # rather than silently widening the mark past the unmarked suffix
    marked_request = await _generate_request(
        _auto_api(),
        _non_final_tool_result_input(breakpoint=True),
        GenerateConfig(),
        monkeypatch,
    )
    unmarked_request = await _generate_request(
        _auto_api(),
        _non_final_tool_result_input(breakpoint=False),
        GenerateConfig(),
        monkeypatch,
    )
    # the inner content blocks never carry cache_control (not widened there),
    # and the overall request is indistinguishable from the unmarked case —
    # the unsupported mark was discarded, not relocated
    messages = marked_request["messages"]
    tool_pos = _tool_result_positions(messages)[0]
    tool_result = messages[tool_pos[0]]["content"][tool_pos[1]]
    assert all("cache_control" not in block for block in tool_result["content"])
    ignore = {"extra_headers"}
    assert {k: v for k, v in marked_request.items() if k not in ignore} == {
        k: v for k, v in unmarked_request.items() if k not in ignore
    }


# ---------------------------------------------------------------------------
# (i) system content boundaries (ContentText.cache_breakpoint in system content)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_system_cache_breakpoint_preserves_stable_varying_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a marked stable system block followed by a varying one must not be
    # flattened into a single string and cached through the varying part
    request = await _generate_request(
        _auto_api(),
        [
            ChatMessageSystem(
                content=[
                    ContentText(text="stable rubric", cache_breakpoint=True),
                    ContentText(text="varying instructions"),
                ]
            ),
            ChatMessageUser(content="item"),
        ],
        GenerateConfig(),
        monkeypatch,
    )
    system = request["system"]
    assert [b["text"] for b in system] == ["stable rubric", "varying instructions"]
    assert system[0]["cache_control"] == CACHE
    # the varying tail is not auto-marked (that would cache-write it every call)
    assert "cache_control" not in system[1]
    # no other automatic breakpoints appear since messages are unmarked and
    # cache_prompt has no explicit message marks, so lookback still applies
    assert tagged(request["messages"]) == []


@pytest.mark.anyio
async def test_system_without_explicit_mark_keeps_automatic_last_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _generate_request(
        _auto_api(),
        [
            ChatMessageSystem(
                content=[
                    ContentText(text="block a"),
                    ContentText(text="block b"),
                ]
            ),
            ChatMessageUser(content="item"),
        ],
        GenerateConfig(),
        monkeypatch,
    )
    system = request["system"]
    # unmarked system content keeps its prior flattened representation (a
    # single joined block), not one block per ContentText part
    assert [b["text"] for b in system] == ["block a\nblock b"]
    assert system[0]["cache_control"] == CACHE


# ---------------------------------------------------------------------------
# (j) disabled/fallback payloads must match the same request with hints
# removed — not a hint-stripped version of an already-marked conversion.
# ---------------------------------------------------------------------------


def _strip_marks(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Test-local copy of `messages` with every `cache_breakpoint` cleared."""
    result: list[ChatMessage] = []
    for m in messages:
        if isinstance(m.content, list):
            m = m.model_copy(
                update={
                    "content": [
                        b.model_copy(update={"cache_breakpoint": None})
                        if isinstance(b, ContentText)
                        else b
                        for b in m.content
                    ]
                }
            )
        result.append(m)
    return result


def _assert_matches_hints_removed_baseline(
    request: dict[str, Any], baseline: dict[str, Any]
) -> None:
    ignore = {"extra_headers"}
    assert {k: v for k, v in request.items() if k not in ignore} == {
        k: v for k, v in baseline.items() if k not in ignore
    }


@pytest.mark.anyio
async def test_cache_prompt_false_matches_hints_removed_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # cache_prompt=False must produce exactly the same request as the same
    # messages with every cache_breakpoint hint removed — not the marked
    # conversion (multiple system blocks) with only `cache_control` fields
    # stripped back out.
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="stable", cache_breakpoint=True),
                ContentText(text="varying"),
            ]
        ),
        ChatMessageUser(content="q"),
    ]
    before = [m.model_dump() for m in input]
    request = await _generate_request(
        _auto_api(), input, GenerateConfig(cache_prompt=False), monkeypatch
    )
    assert [m.model_dump() for m in input] == before  # no caller mutation

    baseline = await _generate_request(
        _auto_api(),
        _strip_marks(input),
        GenerateConfig(cache_prompt=False),
        monkeypatch,
    )
    _assert_matches_hints_removed_baseline(request, baseline)
    assert request["system"] == [{"type": "text", "text": "stable\nvarying"}]


@pytest.mark.anyio
async def test_legacy_model_matches_hints_removed_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a model that predates cache_control (e.g. claude-3-sonnet) must also
    # get the hints-removed payload, not a stripped marked conversion.
    api = AnthropicAPI(model_name="claude-3-sonnet-20240229", api_key="test-key")
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="stable", cache_breakpoint=True),
                ContentText(text="varying"),
            ]
        ),
        ChatMessageUser(content="q"),
    ]
    request = await _generate_request(api, input, GenerateConfig(), monkeypatch)
    baseline = await _generate_request(
        api, _strip_marks(input), GenerateConfig(), monkeypatch
    )
    _assert_matches_hints_removed_baseline(request, baseline)
    assert request["system"] == [{"type": "text", "text": "stable\nvarying"}]
    assert "cache_control" not in request


@pytest.mark.anyio
async def test_empty_marked_system_block_matches_hints_removed_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # an empty marked block can't itself carry cache_control, so the whole
    # layout falls back; the fallback must be the same automatic-caching
    # payload as the unmarked baseline (one joined block), not the marked
    # conversion's per-mark segmentation with cache_control stripped.
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="a", cache_breakpoint=True),
                ContentText(text="", cache_breakpoint=True),
                ContentText(text="b"),
            ]
        ),
        ChatMessageUser(content="q"),
    ]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    baseline = await _generate_request(
        _auto_api(), _strip_marks(input), GenerateConfig(), monkeypatch
    )
    _assert_matches_hints_removed_baseline(request, baseline)
    assert request["system"] == [
        {"type": "text", "text": "a\n\nb", "cache_control": CACHE}
    ]


@pytest.mark.anyio
async def test_trailing_empty_marked_system_block_matches_hints_removed_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a marked block followed by exactly one empty unmarked block: that
    # trailing run's text ("") can't be sent as its own text block, so
    # emitting it would silently drop the separator it contributes to the
    # unmarked text ("a\n"). The whole layout must fall back instead of
    # losing it.
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="a", cache_breakpoint=True),
                ContentText(text=""),
            ]
        ),
        ChatMessageUser(content="q"),
    ]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    baseline = await _generate_request(
        _auto_api(), _strip_marks(input), GenerateConfig(), monkeypatch
    )
    _assert_matches_hints_removed_baseline(request, baseline)
    assert request["system"] == [
        {"type": "text", "text": "a\n", "cache_control": CACHE}
    ]


@pytest.mark.anyio
async def test_trailing_empty_marked_system_block_with_user_mark_matches_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the same trailing-empty-block layout, alongside an otherwise-valid
    # user mark: the whole request falls back, not just the system field.
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[
                ContentText(text="a", cache_breakpoint=True),
                ContentText(text=""),
            ]
        ),
        ChatMessageUser(content=[ContentText(text="rubric", cache_breakpoint=True)]),
    ]
    before = [m.model_dump() for m in input]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    assert [m.model_dump() for m in input] == before  # no caller mutation

    baseline = await _generate_request(
        _auto_api(), _strip_marks(input), GenerateConfig(), monkeypatch
    )
    _assert_matches_hints_removed_baseline(request, baseline)
    assert request["system"] == [
        {"type": "text", "text": "a\n", "cache_control": CACHE}
    ]
    assert "cache_control" not in request["messages"][0]["content"][0]


@pytest.mark.anyio
async def test_five_system_marks_over_budget_matches_hints_removed_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # more than Anthropic's 4-breakpoint budget: the fallback payload must
    # be a single joined block with automatic caching, matching the
    # hints-removed baseline, not five separately marked blocks with
    # cache_control removed.
    input: list[ChatMessage] = [
        ChatMessageSystem(
            content=[ContentText(text=str(i), cache_breakpoint=True) for i in range(5)]
        ),
        ChatMessageUser(content="q"),
    ]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    baseline = await _generate_request(
        _auto_api(), _strip_marks(input), GenerateConfig(), monkeypatch
    )
    _assert_matches_hints_removed_baseline(request, baseline)
    assert request["system"] == [
        {"type": "text", "text": "0\n1\n2\n3\n4", "cache_control": CACHE}
    ]


@pytest.mark.anyio
async def test_orphan_tool_mark_loss_forces_whole_layout_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a mark on an orphaned tool result (its tool_use_id has no match, e.g.
    # native compaction summarized the tool_use away) can't survive
    # conversion to plain text. That loss must force the whole layout back
    # to normal automatic caching — even though another mark (the user
    # rubric) would otherwise be honorable on its own — rather than retain
    # a partial explicit layout that only honors the surviving mark.
    input: list[ChatMessage] = [
        ChatMessageUser(content=[ContentText(text="rubric", cache_breakpoint=True)]),
        ChatMessageTool(
            content=[ContentText(text="result", cache_breakpoint=True)],
            tool_call_id="missing",
        ),
    ]
    before = [m.model_dump() for m in input]
    request = await _generate_request(_auto_api(), input, GenerateConfig(), monkeypatch)
    assert [m.model_dump() for m in input] == before  # no caller mutation

    baseline = await _generate_request(
        _auto_api(), _strip_marks(input), GenerateConfig(), monkeypatch
    )
    _assert_matches_hints_removed_baseline(request, baseline)
    # the rubric's own mark was not retained in a partial explicit layout:
    # the request matches plain automatic caching (a lookback marker, not an
    # explicit cache_control from the discarded mark) exactly like the
    # hints-removed baseline above.
    assert request["cache_control"] == CACHE


# ---------------------------------------------------------------------------
# (j) ordinary-path full-request regression: the complete wire shape for an
# unmarked system + tool-definition + tool-use + matched tool-result +
# continuation conversation, pinned against the literal payload commit
# 64358f1be463d actually produced (before explicit breakpoints existed).
# Captured by hand from that commit's code, not regenerated by the current
# implementation, so a shared-helper regression can't slip past both.
# ---------------------------------------------------------------------------

_ORDINARY_TOOLS = [
    ToolInfo(
        name="get_weather",
        description="Look up the current weather for a city.",
        parameters=ToolParams(
            properties={"city": ToolParam(type="string", description="City name")},
            required=["city"],
        ),
    )
]


def _ordinary_input() -> list[ChatMessage]:
    """System + tool definition + assistant tool-use + matched tool-result + user continuation, unmarked."""
    return [
        ChatMessageSystem(content="You are a weather assistant."),
        ChatMessageUser(content="What's the weather in Boston?"),
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id="t1", function="get_weather", arguments={"city": "Boston"})
            ],
        ),
        ChatMessageTool(
            content="72F and sunny.", tool_call_id="t1", function="get_weather"
        ),
        ChatMessageUser(content="Thanks -- reply with just the temperature."),
    ]


def _ordinary_expected_request(cache_control: dict[str, Any] | None) -> dict[str, Any]:
    """The literal request commit 64358f1be463d produced for `_ordinary_input()`.

    `cache_control` is the ephemeral object applied at the top level, on the
    system block, on the tool definition, and on the lookback-tagged
    tool-result block -- or `None` for the disabled case, where no block or
    top-level key carries `cache_control` at all.
    """
    tool_result_block: dict[str, Any] = {
        "tool_use_id": "t1",
        "type": "tool_result",
        "content": [{"type": "text", "text": "72F and sunny."}],
        "is_error": False,
    }
    system_block: dict[str, Any] = {
        "type": "text",
        "text": "You are a weather assistant.",
    }
    tool_def: dict[str, Any] = {
        "name": "get_weather",
        "description": "Look up the current weather for a city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    }
    if cache_control is not None:
        tool_result_block["cache_control"] = cache_control
        system_block["cache_control"] = cache_control
        tool_def["cache_control"] = cache_control

    request: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "What's the weather in Boston?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "(no content)"},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "get_weather",
                        "input": {"city": "Boston"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    tool_result_block,
                    {
                        "type": "text",
                        "text": "Thanks -- reply with just the temperature.",
                    },
                ],
            },
        ],
        "system": [system_block],
        "tools": [tool_def],
        "tool_choice": {"type": "auto"},
        "model": "claude-sonnet-4-6",
        "max_tokens": None,
    }
    if cache_control is not None:
        request["cache_control"] = cache_control
    return request


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("api_kwargs", "config", "cache_control"),
    [
        pytest.param({}, GenerateConfig(), {"type": "ephemeral"}, id="default"),
        pytest.param(
            {},
            GenerateConfig(cache_prompt=True),
            {"type": "ephemeral"},
            id="enabled",
        ),
        pytest.param({}, GenerateConfig(cache_prompt=False), None, id="disabled"),
        pytest.param(
            {"cache_ttl": "5m"},
            GenerateConfig(),
            {"type": "ephemeral", "ttl": "5m"},
            id="ttl-5m",
        ),
        pytest.param(
            {"cache_ttl": "1h"},
            GenerateConfig(),
            {"type": "ephemeral", "ttl": "1h"},
            id="ttl-1h",
        ),
    ],
)
async def test_ordinary_unmarked_request_matches_original_wire_shape(
    api_kwargs: dict[str, Any],
    config: GenerateConfig,
    cache_control: dict[str, Any] | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _generate_request(
        _auto_api(**api_kwargs),
        _ordinary_input(),
        config,
        monkeypatch,
        tools=_ORDINARY_TOOLS,
    )
    request.pop("extra_headers", None)
    assert request == _ordinary_expected_request(cache_control)


def test_ordinary_unmarked_request_disabled_carries_no_cache_control() -> None:
    request = _ordinary_expected_request(None)
    assert "cache_control" not in request
    assert "cache_control" not in request["system"][0]
    assert "cache_control" not in request["tools"][0]
    for message in request["messages"]:
        if isinstance(message["content"], list):
            for block in message["content"]:
                assert "cache_control" not in block


# ---------------------------------------------------------------------------
# Live test (--runapi, needs ANTHROPIC_API_KEY): the system-content-boundary
# fix, against the real API rather than a captured request.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_live_system_cache_breakpoint_reuses_marked_prefix() -> None:
    """A marked stable system block is read from cache; the varying tail changes the answer.

    Regression test for the system-content flattening bug: before the fix,
    `ChatMessageSystem.text` joined the stable and varying blocks into one
    string before the mark could apply, so the second call re-wrote the
    whole system prompt instead of reading the stable part from cache.
    """
    model = get_model(
        "anthropic/claude-haiku-4-5",
        config=GenerateConfig(max_tokens=5, temperature=0.0),
    )
    # unique per test run (a literal string would be cached from a prior run,
    # another worker, or the unmarked baseline test) and well over haiku's
    # minimum cacheable prefix (2048 tokens)
    salt = uuid4().hex
    instruction = (
        "This message ends with a line 'TAIL: <n>'. Reply with only the "
        "digit n and nothing else — no words, no punctuation."
    )
    rubric = f"{instruction}\n\nunique-marker-{salt}: " + (
        "The quick brown fox jumps over the lazy dog. " * 400
    )

    async def call(tail_digit: str) -> ModelOutput:
        system = ChatMessageSystem(
            content=[
                ContentText(text=rubric, cache_breakpoint=True),
                ContentText(text=f"TAIL: {tail_digit}"),
            ]
        )
        return await model.generate(
            input=[system, ChatMessageUser(content="Reply now.")]
        )

    out1 = await call("4")
    out2 = await call("5")

    assert out1.usage is not None and out2.usage is not None
    assert (out1.usage.input_tokens_cache_write or 0) > 0
    assert (out2.usage.input_tokens_cache_read or 0) > 0
    # the varying tail was not written into the cached prefix, so the cached
    # amount doesn't grow between the two calls
    assert out2.usage.input_tokens_cache_read == out1.usage.input_tokens_cache_write
    # the varying tail deterministically changed the answer content
    assert "4" in out1.completion
    assert "5" in out2.completion


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_live_ordinary_unmarked_caching_with_tools_and_tool_result() -> None:
    """Ordinary (unmarked) multi-turn caching still works with a tool and a tool-result continuation.

    Regression test for the isolated explicit-cache-breakpoint path: this
    conversation carries no `ContentText.cache_breakpoint` mark anywhere, so
    the whole thing must run through the untouched original conversion and
    automatic-caching path in `resolve_chat_input`, exactly as before
    explicit breakpoints existed. Exercises a tool definition, a real assistant
    tool-use turn, and a tool-result continuation together with a long
    stable system prefix -- the shape most likely to regress if the entry
    dispatch or a shared conversion helper leaked explicit-path behavior
    onto the unmarked path.
    """
    salt = uuid4().hex
    model = get_model(
        "anthropic/claude-haiku-4-5",
        config=GenerateConfig(max_tokens=60, temperature=0.0, cache_prompt=True),
    )

    tools = [
        ToolInfo(
            name="get_weather",
            description="Look up the current weather for a city.",
            parameters=ToolParams(
                properties={"city": ToolParam(type="string", description="City name")},
                required=["city"],
            ),
        )
    ]

    # long stable system prefix, well over haiku's minimum cacheable prefix
    # (2048 tokens); unique per test run so it can't be a cache hit left
    # over from a prior run, another worker, or another test in this file
    paragraph = "The quick brown fox jumps over the lazy dog. " * 400
    system = ChatMessageSystem(
        content=f"You are a weather assistant. unique-marker-{salt}\n{paragraph}"
    )
    turn1: list[ChatMessage] = [
        system,
        ChatMessageUser(
            content="What's the weather in Boston? Use the get_weather tool."
        ),
    ]
    response1 = await model.generate(input=turn1, tools=tools)
    assert response1.usage is not None

    tool_call = next(
        (
            tc
            for tc in (response1.message.tool_calls or [])
            if tc.function == "get_weather"
        ),
        None,
    )
    assert tool_call is not None, "expected the model to call get_weather"

    tool_result = ChatMessageTool(
        content="72F and sunny.",
        tool_call_id=tool_call.id,
        function="get_weather",
    )
    turn2: list[ChatMessage] = [
        *turn1,
        response1.message,
        tool_result,
        ChatMessageUser(content="Thanks -- reply with just the temperature."),
    ]
    response2 = await model.generate(input=turn2, tools=tools)

    assert response2.usage is not None
    assert (response1.usage.input_tokens_cache_write or 0) > 0
    assert (response2.usage.input_tokens_cache_read or 0) > 0
    assert "72" in response2.completion
