"""Tests for Anthropic server-side refusal fallback (`fallback_models`).

Covers config plumbing, service/batch gating, response-side detection
(ContentData wrapping, serving-model resolution, metadata, usage), the
declined-attempt stripping rule, and replay/bridge round-tripping.
"""

from typing import Any, cast

import pytest
from anthropic._models import construct_type
from anthropic.types.message import Message
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentData, ContentReasoning, ContentText
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    GenerateConfig,
    ModelOutput,
    StopCategory,
    StopDetails,
    get_model,
)
from inspect_ai.model._providers.anthropic import (
    FALLBACK_BETA,
    AnthropicAPI,
    _warn_refusal_without_fallback,
    assistant_message_blocks,
    content_and_tool_calls_from_assistant_content_blocks,
    init_sample_anthropic_assistant_internal,
    message_param,
    model_output_from_message,
)

FALLBACK_MODEL = "claude-opus-4-8"
REQUESTED_MODEL = "claude-fable-5"


def _fallback_message(
    content: list[dict[str, Any]],
    *,
    model: str = FALLBACK_MODEL,
    iterations: list[dict[str, Any]] | None = None,
) -> Message:
    """Build a Message via the SDK's lenient parse (as the non-beta client does)."""
    usage: dict[str, Any] = {"input_tokens": 412, "output_tokens": 264}
    if iterations is not None:
        usage["iterations"] = iterations
    data = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": "end_turn",
        "usage": usage,
    }
    return cast(Message, construct_type(value=data, type_=Message))


def _fallback_block(
    from_model: str = REQUESTED_MODEL, to_model: str = FALLBACK_MODEL
) -> dict[str, Any]:
    return {
        "type": "fallback",
        "from": {"model": from_model},
        "to": {"model": to_model},
    }


# ---------------------------------------------------------------------------
# config plumbing + gating
# ---------------------------------------------------------------------------


def test_fallback_config_adds_param_and_beta() -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    config = GenerateConfig(max_tokens=64, fallback_models=[FALLBACK_MODEL])
    _params, extra_body, _headers, betas = api.completion_config(config)
    assert extra_body["fallbacks"] == [{"model": FALLBACK_MODEL}]
    assert FALLBACK_BETA in betas


def test_fallback_config_absent_when_unset() -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    _params, extra_body, _headers, betas = api.completion_config(
        GenerateConfig(max_tokens=64)
    )
    assert "fallbacks" not in extra_body
    assert FALLBACK_BETA not in betas


@pytest.mark.parametrize(
    "model_name",
    [
        "bedrock/us.anthropic.claude-sonnet-4-6",
        "vertex/claude-sonnet-4-6@20250929",
    ],
)
def test_fallback_ignored_on_bedrock_vertex(
    model_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "fake")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_REGION", "us-east5")

    from inspect_ai._util import logger as logger_mod
    from inspect_ai.model._providers import anthropic as anthropic_mod

    warnings: list[str] = []
    logger_mod._warned.clear()
    monkeypatch.setattr(
        anthropic_mod.logger, "warning", lambda msg: warnings.append(msg)
    )

    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    config = GenerateConfig(max_tokens=64, fallback_models=[FALLBACK_MODEL])
    _params, extra_body, _headers, betas = api.completion_config(config)
    assert "fallbacks" not in extra_body
    assert FALLBACK_BETA not in betas
    assert any("fallback_models" in w for w in warnings)


def test_fallback_ignored_in_batch_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from inspect_ai._util import logger as logger_mod
    from inspect_ai.model._providers import anthropic as anthropic_mod

    warnings: list[str] = []
    logger_mod._warned.clear()
    monkeypatch.setattr(
        anthropic_mod.logger, "warning", lambda msg: warnings.append(msg)
    )

    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    config = GenerateConfig(max_tokens=64, fallback_models=[FALLBACK_MODEL], batch=True)
    _params, extra_body, _headers, betas = api.completion_config(config)
    assert "fallbacks" not in extra_body
    assert FALLBACK_BETA not in betas
    assert any("Batches" in w for w in warnings)


# ---------------------------------------------------------------------------
# response side: detection, serving model, metadata, usage
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fallback_refusal_before_output() -> None:
    init_sample_anthropic_assistant_internal()
    message = _fallback_message(
        [_fallback_block(), {"type": "text", "text": "Hi! How can I help?"}],
        iterations=[
            {
                "type": "message",
                "model": REQUESTED_MODEL,
                "input_tokens": 535,
                "output_tokens": 0,
            },
            {
                "type": "fallback_message",
                "model": FALLBACK_MODEL,
                "input_tokens": 412,
                "output_tokens": 264,
            },
        ],
    )
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])

    # serving model reported
    assert output.model == FALLBACK_MODEL
    # usage is the serving attempt's top-level usage, NOT summed over iterations
    assert output.usage is not None
    assert output.usage.input_tokens == 412
    assert output.usage.output_tokens == 264
    # typed fallback field
    assert output.fallback is not None
    assert output.fallback.model == REQUESTED_MODEL
    assert output.fallback.fallback_model == FALLBACK_MODEL
    assert output.fallback.count == 1
    assert output.fallback.metadata is not None
    assert output.fallback.metadata["handoffs"] == [
        {"from": REQUESTED_MODEL, "to": FALLBACK_MODEL}
    ]
    assert isinstance(output.fallback.metadata["iterations"], list)
    # fallback block wrapped as ContentData (in position), text preserved
    content = output.message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentData)
    meta = cast(dict[str, Any], content[0].data["fallback_metadata"])
    assert meta["to"] == {"model": FALLBACK_MODEL}
    assert isinstance(content[1], ContentText)


@pytest.mark.anyio
async def test_fallback_mid_output_strips_declined_thinking() -> None:
    """Thinking before the boundary is dropped; text before/after is kept."""
    init_sample_anthropic_assistant_internal()
    message = _fallback_message(
        [
            {"type": "thinking", "thinking": "declined reasoning", "signature": "sig1"},
            {"type": "text", "text": "partial declined text"},
            _fallback_block(),
            {"type": "text", "text": "served answer"},
        ],
        model=REQUESTED_MODEL,  # message_start named requested model (streaming)
    )
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])

    # serving model resolved from the final fallback block's `to`
    assert output.model == FALLBACK_MODEL
    content = output.message.content
    assert isinstance(content, list)
    # no ContentReasoning survives (declined-attempt thinking dropped)
    assert not any(isinstance(c, ContentReasoning) for c in content)
    texts = [c.text for c in content if isinstance(c, ContentText)]
    assert texts == ["partial declined text", "served answer"]


@pytest.mark.anyio
async def test_fallback_strips_declined_tool_use() -> None:
    """A client tool_use before the boundary must not become a ToolCall."""
    init_sample_anthropic_assistant_internal()
    message = _fallback_message(
        [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "bash",
                "input": {"cmd": "ls"},
            },
            _fallback_block(),
            {"type": "text", "text": "served answer"},
        ],
        model=REQUESTED_MODEL,
    )
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])
    assert not output.message.tool_calls


@pytest.mark.anyio
async def test_no_fallback_metadata_when_absent() -> None:
    init_sample_anthropic_assistant_internal()
    message = _fallback_message([{"type": "text", "text": "normal answer"}])
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])
    assert output.model == FALLBACK_MODEL
    assert output.fallback is None


@pytest.mark.anyio
async def test_compaction_iterations_still_summed() -> None:
    """Compaction iterations (no fallback_message entry) are still aggregated."""
    init_sample_anthropic_assistant_internal()
    message = _fallback_message(
        [{"type": "text", "text": "compacted"}],
        iterations=[
            {"type": "message", "input_tokens": 100, "output_tokens": 10},
            {"type": "message", "input_tokens": 200, "output_tokens": 20},
        ],
    )
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])
    assert output.usage is not None
    assert output.usage.input_tokens == 300
    assert output.usage.output_tokens == 30


# ---------------------------------------------------------------------------
# token counting (replayed fallback blocks need the beta header)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_count_tokens_adds_fallback_beta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """count_tokens on a fallen-back history sends the fallback beta header."""
    init_sample_anthropic_assistant_internal()
    message = _fallback_message(
        [_fallback_block(), {"type": "text", "text": "served answer"}]
    )
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])

    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")

    captured: dict[str, Any] = {}

    async def fake_count_tokens(**kwargs: Any) -> Any:
        captured.update(kwargs)

        class _Response:
            input_tokens = 42

        return _Response()

    monkeypatch.setattr(api.client.messages, "count_tokens", fake_count_tokens)

    count = await api.count_tokens([output.message])
    assert count == 42
    assert captured["extra_headers"]["anthropic-beta"] == FALLBACK_BETA
    # the fallback block survives conversion (it's what requires the beta)
    assert any(b.get("type") == "fallback" for b in captured["messages"][0]["content"])


@pytest.mark.anyio
async def test_count_tokens_no_beta_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")

    captured: dict[str, Any] = {}

    async def fake_count_tokens(**kwargs: Any) -> Any:
        captured.update(kwargs)

        class _Response:
            input_tokens = 7

        return _Response()

    monkeypatch.setattr(api.client.messages, "count_tokens", fake_count_tokens)

    await api.count_tokens("Hello")
    assert "extra_headers" not in captured


# ---------------------------------------------------------------------------
# refusal hint (suggest fallback_models when a rescuable refusal occurs)
# ---------------------------------------------------------------------------


@pytest.fixture
def hint_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from inspect_ai._util import logger as logger_mod
    from inspect_ai.model._providers import anthropic as anthropic_mod

    warnings: list[str] = []
    logger_mod._warned.clear()
    monkeypatch.setattr(
        anthropic_mod.logger, "warning", lambda msg: warnings.append(msg)
    )
    return warnings


def _refusal_details() -> StopDetails:
    return StopDetails(
        type="refusal",
        category="cyber",
        explanation="This request was declined because it could enable cyber harm.",
        categories=[StopCategory(category="cyber")],
    )


def _refusal_output(
    details: StopDetails | None,
    stop_reason: str = "content_filter",
    model: str = REQUESTED_MODEL,
) -> ModelOutput:
    return ModelOutput(
        model=model,
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=""),
                stop_reason=cast(Any, stop_reason),
                stop_details=details,
            )
        ],
    )


def test_refusal_hint_emitted(hint_warnings: list[str]) -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    _warn_refusal_without_fallback(
        api, GenerateConfig(), _refusal_output(_refusal_details())
    )
    assert len(hint_warnings) == 1
    assert "fallback_models" in hint_warnings[0]
    assert "https://inspect.aisi.org.uk/fallbacks.html" in hint_warnings[0]
    assert "cyber" in hint_warnings[0]


def test_refusal_hint_suppressed_when_fallback_configured(
    hint_warnings: list[str],
) -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    _warn_refusal_without_fallback(
        api,
        GenerateConfig(fallback_models=[FALLBACK_MODEL]),
        _refusal_output(_refusal_details()),
    )
    assert hint_warnings == []


@pytest.mark.parametrize(
    "model_name",
    [
        "bedrock/us.anthropic.claude-fable-5",
        "vertex/claude-fable-5@20260609",
    ],
)
def test_refusal_hint_suppressed_on_bedrock_vertex(
    model_name: str, hint_warnings: list[str]
) -> None:
    import os

    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "fake")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_PROJECT_ID", "fake")
    os.environ.setdefault("ANTHROPIC_VERTEX_REGION", "us-east5")

    api = AnthropicAPI(model_name=model_name, api_key="test-key")
    _warn_refusal_without_fallback(
        api, GenerateConfig(), _refusal_output(_refusal_details())
    )
    assert hint_warnings == []


def test_refusal_hint_suppressed_in_batch_mode(hint_warnings: list[str]) -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    _warn_refusal_without_fallback(
        api, GenerateConfig(batch=True), _refusal_output(_refusal_details())
    )
    assert hint_warnings == []


def test_refusal_hint_suppressed_on_non_claude_5(hint_warnings: list[str]) -> None:
    # Opus 4.7/4.8 emit the same refusal stop_details but the fallbacks
    # param is not accepted for them
    api = AnthropicAPI(model_name=FALLBACK_MODEL, api_key="test-key")
    _warn_refusal_without_fallback(
        api, GenerateConfig(), _refusal_output(_refusal_details())
    )
    assert hint_warnings == []


def test_refusal_hint_requires_refusal_details(hint_warnings: list[str]) -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    # content_filter without stop_details (e.g. mid-stream HTTP error
    # conversion) is not a classifier refusal
    _warn_refusal_without_fallback(api, GenerateConfig(), _refusal_output(None))
    # nor is a non-refusal details type
    _warn_refusal_without_fallback(
        api,
        GenerateConfig(),
        _refusal_output(StopDetails(type="other", explanation="something")),
    )
    assert hint_warnings == []


def test_refusal_hint_not_on_normal_stop(hint_warnings: list[str]) -> None:
    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    _warn_refusal_without_fallback(
        api, GenerateConfig(), _refusal_output(None, stop_reason="stop")
    )
    assert hint_warnings == []


@pytest.mark.anyio
async def test_refusal_hint_via_message_flow(hint_warnings: list[str]) -> None:
    """stop_details flow from the wire message through to the hint."""
    init_sample_anthropic_assistant_internal()
    data = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": REQUESTED_MODEL,
        "content": [],
        "stop_reason": "refusal",
        "stop_details": {
            "type": "refusal",
            "category": "cyber",
            "explanation": "This request was declined.",
        },
        "usage": {"input_tokens": 412, "output_tokens": 0},
    }
    message = cast(Message, construct_type(value=data, type_=Message))
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])
    assert output.choices[0].stop_reason == "content_filter"
    assert output.choices[0].stop_details is not None
    assert output.choices[0].stop_details.type == "refusal"

    api = AnthropicAPI(model_name=REQUESTED_MODEL, api_key="test-key")
    _warn_refusal_without_fallback(api, GenerateConfig(), output)
    assert len(hint_warnings) == 1
    assert "fallback_models" in hint_warnings[0]


# ---------------------------------------------------------------------------
# replay + bridge round-trip
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fallback_replay_round_trip() -> None:
    """Assistant ContentData → fallback param in its original position."""
    init_sample_anthropic_assistant_internal()
    message = _fallback_message(
        [_fallback_block(), {"type": "text", "text": "served answer"}]
    )
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])

    param = await message_param(output.message)
    blocks = param["content"]
    assert isinstance(blocks, list)
    assert blocks[0]["type"] == "fallback"
    assert blocks[0]["to"] == {"model": FALLBACK_MODEL}
    assert blocks[0]["from"] == {"model": REQUESTED_MODEL}
    assert blocks[1]["type"] == "text"


@pytest.mark.anyio
async def test_fallback_bridge_round_trip() -> None:
    """Echoed scaffold history (dicts) → ChatMessage → wire params."""
    init_sample_anthropic_assistant_internal()
    # scaffold echoes the assistant turn as dicts (incl. the fallback block)
    echoed: list[Any] = [_fallback_block(), {"type": "text", "text": "served answer"}]
    content, tool_calls = content_and_tool_calls_from_assistant_content_blocks(
        echoed, []
    )
    assert isinstance(content[0], ContentData)
    meta = cast(dict[str, Any], content[0].data["fallback_metadata"])
    assert meta["from"] == {"model": REQUESTED_MODEL}

    msg = ChatMessageAssistant(content=content, tool_calls=tool_calls)
    blocks = await assistant_message_blocks(msg, beta=True)
    types = [getattr(b, "type", None) for b in blocks]
    assert "fallback" in types


@pytest.mark.anyio
async def test_fallback_bridge_tolerates_from_alias() -> None:
    """The sandbox bridge dumps without by_alias, yielding `from_` — tolerate it."""
    init_sample_anthropic_assistant_internal()
    echoed: list[Any] = [
        {
            "type": "fallback",
            "from_": {"model": REQUESTED_MODEL},
            "to": {"model": FALLBACK_MODEL},
        },
        {"type": "text", "text": "served answer"},
    ]
    content, _tcs = content_and_tool_calls_from_assistant_content_blocks(echoed, [])
    assert isinstance(content[0], ContentData)
    meta = cast(dict[str, Any], content[0].data["fallback_metadata"])
    assert meta["from"] == {"model": REQUESTED_MODEL}
    assert meta["to"] == {"model": FALLBACK_MODEL}


# ---------------------------------------------------------------------------
# live (requires API key)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_count_tokens_with_fallback_history_live() -> None:
    """The API accepts a fallen-back history for token counting (with beta)."""
    init_sample_anthropic_assistant_internal()
    message = _fallback_message(
        [_fallback_block(), {"type": "text", "text": "served answer"}]
    )
    output, _pause = await model_output_from_message(None, REQUESTED_MODEL, message, [])

    model = get_model(f"anthropic/{REQUESTED_MODEL}")
    count = await model.api.count_tokens([output.message])
    assert count > 0


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_fallback_param_accepted_live() -> None:
    """A benign request with fallback_models is accepted and round-trips a turn."""
    model = get_model(
        f"anthropic/{REQUESTED_MODEL}",
        config=GenerateConfig(max_tokens=64, fallback_models=[FALLBACK_MODEL]),
    )
    response = await model.generate(input="Say hello in one word.")
    assert len(response.completion) >= 1


@skip_if_no_anthropic
def test_fallback_eval_live() -> None:
    log = eval(
        Task(dataset=[Sample(input="Please tell a short story about toys.")]),
        model=f"anthropic/{REQUESTED_MODEL}",
        fallback_models=[FALLBACK_MODEL],
    )[0]
    assert log.status == "success"
