"""Tests for the LiteLLM proxy provider.

Most run against a local LiteLLM proxy in Docker. The proxy runs from a locally
available image with a mock-response config, so these tests need no network
access or provider keys (see `test_helpers.litellm_proxy.proxy`). The
reasoning conversion tests below need no proxy; round trips through a proxy
are in `test_litellm_proxy_reasoning.py`. The model info fetch tests use a
local stub server.
"""

import json
import socket
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import httpx2
import pytest
from openai import APIError, APIStatusError, BadRequestError
from test_helpers.litellm_proxy.errors import error_deployments, error_route
from test_helpers.litellm_proxy.proxy import (
    LiteLLMProxy,
    isolate_model_info,
    run_litellm_proxy,
    skip_if_no_litellm_proxy,
)
from test_helpers.litellm_proxy.stubs import fake_upstream
from test_helpers.utils import skip_if_no_openai_package

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelCost,
    ModelInfo,
    ModelOutput,
    get_model,
    set_model_info,
)
from inspect_ai.model._model import RetryDecision
from inspect_ai.model._model_info import (
    MODEL_INFO_LOOKUP_API_KEY,
    _get_custom_model_info,
    _get_model_info_direct,
    get_model_input_tokens,
    set_model_cost,
)
from inspect_ai.model._openai import OpenAIResponseError
from inspect_ai.model._providers import _litellm_proxy_model_info, _litellm_proxy_names
from inspect_ai.model._providers._litellm_proxy_errors import (
    litellm_error_model_output,
    upstream_message,
)
from inspect_ai.model._providers._litellm_proxy_model_info import (
    ProxyDeployment,
    proxy_model_info,
)
from inspect_ai.model._providers._litellm_proxy_names import resolve_deployments
from inspect_ai.model._providers._litellm_proxy_reasoning import (
    ThinkingBlocksAccumulator,
)
from inspect_ai.model._providers.litellm_proxy import (
    LITELLM_PROXY_API_BASE,
    LITELLM_PROXY_BASE_URL,
    LiteLLMProxyAPI,
    merged_model_info,
)

MOCK_MODEL = "mock-model"
MOCK_RESPONSE = "Hello from the mock proxy"

PROXY_CONFIG: dict[str, Any] = {
    "model_list": [
        {
            "model_name": MOCK_MODEL,
            "litellm_params": {
                "model": f"openai/{MOCK_MODEL}",
                "api_key": "fake",
                "mock_response": MOCK_RESPONSE,
            },
            "model_info": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_reasoning": True,
            },
        },
        {
            # an opaque deployment name identified by base_model
            "model_name": "azure-prod",
            "litellm_params": {
                "model": "openai/prod-deployment-7",
                "api_key": "fake",
                "mock_response": MOCK_RESPONSE,
            },
            "model_info": {"base_model": "azure/gpt-5"},
        },
    ]
}


@pytest.fixture(autouse=True)
def isolated_model_info(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_model_info(monkeypatch)


@pytest.fixture(scope="module")
def litellm_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiteLLMProxy]:
    with run_litellm_proxy(tmp_path_factory.mktemp("litellm"), PROXY_CONFIG) as proxy:
        yield proxy


def _proxy_model(proxy: LiteLLMProxy, **model_args: Any) -> Model:
    return get_model(
        f"litellm-proxy/{MOCK_MODEL}",
        base_url=proxy.base_url,
        api_key=proxy.api_key,
        config=GenerateConfig(max_retries=0),
        **model_args,
    )


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_generate(litellm_proxy: LiteLLMProxy) -> None:
    output = await _proxy_model(litellm_proxy).generate("Hello")
    assert output.completion == MOCK_RESPONSE


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_generate_responses_api(
    litellm_proxy: LiteLLMProxy,
) -> None:
    output = await _proxy_model(litellm_proxy, responses_api=True).generate("Hello")
    assert output.completion == MOCK_RESPONSE


@skip_if_no_litellm_proxy
def test_litellm_proxy_model_info(litellm_proxy: LiteLLMProxy) -> None:
    response = httpx.get(
        f"{litellm_proxy.base_url}/model/info",
        headers={"Authorization": f"Bearer {litellm_proxy.api_key}"},
    )
    response.raise_for_status()
    [model] = [m for m in response.json()["data"] if m["model_name"] == MOCK_MODEL]
    assert model["model_info"]["max_input_tokens"] == 200000
    assert model["model_info"]["max_output_tokens"] == 8192
    assert model["model_info"]["supports_reasoning"] is True


def _proxy_api(model: Model) -> LiteLLMProxyAPI:
    assert isinstance(model.api, LiteLLMProxyAPI)
    return model.api


@pytest.fixture
def clear_model_info_cache() -> Iterator[None]:
    _litellm_proxy_model_info._clear_cache()
    yield
    _litellm_proxy_model_info._clear_cache()


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
def test_litellm_proxy_fetches_model_info(
    litellm_proxy: LiteLLMProxy, clear_model_info_cache: None
) -> None:
    [deployment] = _proxy_api(_proxy_model(litellm_proxy)).proxy_deployments() or []
    assert deployment.model_name == MOCK_MODEL
    assert deployment.model == f"openai/{MOCK_MODEL}"
    assert deployment.model_info["max_input_tokens"] == 200000


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
def test_litellm_proxy_fetches_model_info_without_v1(
    litellm_proxy: LiteLLMProxy, clear_model_info_cache: None
) -> None:
    model = get_model(
        f"litellm-proxy/{MOCK_MODEL}",
        base_url=litellm_proxy.base_url.removesuffix("/v1"),
        api_key=litellm_proxy.api_key,
    )
    [deployment] = _proxy_api(model).proxy_deployments() or []
    assert deployment.model_name == MOCK_MODEL


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
def test_litellm_proxy_resolves_base_model(
    litellm_proxy: LiteLLMProxy, clear_model_info_cache: None
) -> None:
    model = get_model(
        "litellm-proxy/azure-prod",
        base_url=litellm_proxy.base_url,
        api_key=litellm_proxy.api_key,
        memoize=False,
    )
    assert model.canonical_name() == "openai/gpt-5"
    assert model.api.model_family() == "gpt-5"

    # Inspect's entry for gpt-5, with the prices LiteLLM reports for azure/gpt-5
    info = _get_model_info_direct(model)
    assert info is not None
    assert info.context_length == 400000
    assert get_model_input_tokens(model) == 272000
    assert info.cost is not None
    assert (info.cost.input, info.cost.output) == (1.25, 10.0)


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
def test_litellm_proxy_registers_proxy_model_info(
    litellm_proxy: LiteLLMProxy, clear_model_info_cache: None
) -> None:
    # mock-model is not in Inspect's database; its configured model_info is
    model = _proxy_model(litellm_proxy, memoize=False)
    info = _get_model_info_direct(model)
    assert info is not None
    assert (info.context_length, info.output_tokens) == (200000, 8192)
    assert info.reasoning is True


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
def test_litellm_proxy_model_info_unknown_key(
    litellm_proxy: LiteLLMProxy, clear_model_info_cache: None
) -> None:
    with pytest.raises(PrerequisiteError) as ex:
        get_model(
            f"litellm-proxy/{MOCK_MODEL}",
            base_url=litellm_proxy.base_url,
            api_key="sk-wrong-key",
        )
    # the test proxy has no database, so it cannot check keys other than the
    # master key (a proxy with one returns 401)
    assert "HTTP 400: No connected db." in str(ex.value.message)


@skip_if_no_openai_package
def test_litellm_proxy_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (LITELLM_PROXY_BASE_URL, LITELLM_PROXY_API_BASE):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("INSPECT_EVAL_MODEL_BASE_URL", raising=False)
    with pytest.raises(PrerequisiteError) as ex:
        get_model(f"litellm-proxy/{MOCK_MODEL}", api_key="key")
    assert LITELLM_PROXY_BASE_URL in str(ex.value.message)
    assert LITELLM_PROXY_API_BASE in str(ex.value.message)


# Model info fetch (stub server) ----------------------------------------------

STUB_ROWS = [
    {
        "model_name": "claude",
        "litellm_params": {"model": "anthropic/claude-sonnet-4-5"},
        "model_info": {"max_input_tokens": 200000},
    },
    {
        "model_name": "claude",
        "litellm_params": {
            "model": "bedrock/arn:aws:bedrock:us-east-1:1:application-inference-profile/x",
            "custom_llm_provider": "bedrock",
        },
        "model_info": {
            "base_model": "anthropic.claude-sonnet-4-5",
            "max_input_tokens": 1000000,
        },
    },
    {"model_name": "other", "litellm_params": {"model": "openai/gpt-5"}},
]


@dataclass
class ModelInfoStub:
    url: str
    status: int = 200
    body: bytes = json.dumps({"data": STUB_ROWS}).encode()
    requests: list[dict[str, str]] = field(default_factory=list)
    release: threading.Event = field(default_factory=threading.Event)
    hang: bool = False


@pytest.fixture
def model_info_stub(clear_model_info_cache: None) -> Iterator[ModelInfoStub]:
    stub: ModelInfoStub | None = None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert stub is not None
            stub.requests.append({"path": self.path, **dict(self.headers)})
            if stub.hang:
                stub.release.wait()
                return
            self.send_response(stub.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(stub.body)))
            self.end_headers()
            self.wfile.write(stub.body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    stub = ModelInfoStub(url=f"http://127.0.0.1:{server.server_address[1]}/v1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield stub
    finally:
        stub.release.set()
        server.shutdown()
        server.server_close()


def _stub_provider(
    stub: ModelInfoStub, alias: str = "claude", **model_args: Any
) -> LiteLLMProxyAPI:
    model_args = {"base_url": stub.url, "api_key": "sk-stub"} | model_args
    return _proxy_api(get_model(f"litellm-proxy/{alias}", **model_args))


@skip_if_no_openai_package
def test_model_info_deployments_for_alias(model_info_stub: ModelInfoStub) -> None:
    provider = _stub_provider(
        model_info_stub, default_headers={"x-gateway-token": "gateway"}
    )
    assert provider.proxy_deployments() == [
        ProxyDeployment(
            model_name="claude",
            model="anthropic/claude-sonnet-4-5",
            custom_llm_provider=None,
            base_model=None,
            model_info={"max_input_tokens": 200000},
        ),
        ProxyDeployment(
            model_name="claude",
            model="bedrock/arn:aws:bedrock:us-east-1:1:application-inference-profile/x",
            custom_llm_provider="bedrock",
            base_model="anthropic.claude-sonnet-4-5",
            model_info={
                "base_model": "anthropic.claude-sonnet-4-5",
                "max_input_tokens": 1000000,
            },
        ),
    ]
    [request] = model_info_stub.requests
    assert request["path"] == "/v1/model/info"
    assert request["Authorization"] == "Bearer sk-stub"
    assert request["x-gateway-token"] == "gateway"


@skip_if_no_openai_package
def test_model_info_alias_not_listed(model_info_stub: ModelInfoStub) -> None:
    provider = _stub_provider(
        model_info_stub, alias="missing", require_model_info=False
    )
    assert provider.proxy_deployments() == []


@skip_if_no_openai_package
def test_model_info_cached_per_base_url_and_key(
    model_info_stub: ModelInfoStub,
) -> None:
    _stub_provider(model_info_stub)
    _stub_provider(model_info_stub, alias="other")
    assert len(model_info_stub.requests) == 1
    _stub_provider(model_info_stub, api_key="sk-other")
    assert len(model_info_stub.requests) == 2


@skip_if_no_openai_package
def test_model_info_fetch_skipped(model_info_stub: ModelInfoStub) -> None:
    assert _stub_provider(model_info_stub, model_info=False).proxy_deployments() is None
    placeholder = _stub_provider(model_info_stub, api_key=MODEL_INFO_LOOKUP_API_KEY)
    assert placeholder.proxy_deployments() is None
    assert model_info_stub.requests == []


@skip_if_no_openai_package
def test_model_info_arg_must_be_bool(model_info_stub: ModelInfoStub) -> None:
    with pytest.raises(ValueError, match="model_info must be a bool"):
        _stub_provider(model_info_stub, model_info="no")


@skip_if_no_openai_package
def test_model_info_base_url_alias(
    model_info_stub: ModelInfoStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LITELLM_PROXY_BASE_URL, raising=False)
    monkeypatch.setenv(LITELLM_PROXY_API_BASE, model_info_stub.url)
    provider = _proxy_api(get_model("litellm-proxy/claude", api_key="sk-stub"))
    assert provider.base_url == model_info_stub.url
    assert len(provider.proxy_deployments() or []) == 2


@pytest.mark.parametrize(
    "status,body,cause",
    [
        (401, b"{}", "HTTP 401; the proxy rejected the API key"),
        (500, b"boom", "HTTP 500: boom"),
        (
            500,
            b'{"error": {"message": "Internal error", "code": "500"}}',
            "HTTP 500: Internal error",
        ),
        (200, b"<html>", "the response is not JSON"),
        (200, b'{"models": []}', "the response has no 'data' list"),
        (200, b'{"data": [{"litellm_params": {}}]}', "unexpected deployment row"),
    ],
)
@skip_if_no_openai_package
def test_model_info_fetch_errors(
    model_info_stub: ModelInfoStub, status: int, body: bytes, cause: str
) -> None:
    model_info_stub.status = status
    model_info_stub.body = body
    _assert_fetch_error(lambda: _stub_provider(model_info_stub), cause)


@skip_if_no_openai_package
def test_model_info_fetch_timeout(
    model_info_stub: ModelInfoStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_litellm_proxy_model_info, "MODEL_INFO_TIMEOUT", 0.2)
    model_info_stub.hang = True
    _assert_fetch_error(
        lambda: _stub_provider(model_info_stub), "no response within 0.2s"
    )


@skip_if_no_openai_package
def test_model_info_fetch_connection_refused(clear_model_info_cache: None) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _assert_fetch_error(
        lambda: get_model(
            "litellm-proxy/claude",
            base_url=f"http://127.0.0.1:{port}/v1",
            api_key="sk-stub",
        ),
        "ConnectError",
    )


def _assert_fetch_error(construct: Any, cause: str) -> None:
    with pytest.raises(PrerequisiteError) as ex:
        construct()
    message = str(ex.value.message)
    assert "/model/info" in message
    assert cause in message
    assert "-M model_info=false" in message


# Reasoning conversion ---------------------------------------------------------

THINKING = {"type": "thinking", "thinking": "Let me think.", "signature": "sig-1"}
REDACTED = {"type": "redacted_thinking", "data": "opaque-1"}
TOOL_CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "get_weather", "arguments": '{"city": "Oslo"}'},
}


def _provider() -> LiteLLMProxyAPI:
    api = get_model(
        "litellm-proxy/claude",
        base_url="http://localhost:4000/v1",
        api_key="key",
        model_info=False,
    ).api
    assert isinstance(api, LiteLLMProxyAPI)
    return api


def _completion(message: dict[str, Any]) -> Any:
    from openai.types.chat import ChatCompletion

    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "claude",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant"} | message,
                }
            ],
        }
    )


def _assistant(message: dict[str, Any]) -> ChatMessageAssistant:
    [choice] = _provider().chat_choices_from_completion(_completion(message), [])
    return choice.message


@skip_if_no_openai_package
def test_litellm_proxy_reads_thinking_blocks() -> None:
    message = _assistant(
        {
            "content": "Checking.",
            # LiteLLM's reasoning_content is the text of the blocks
            "reasoning_content": "Let me think.",
            "thinking_blocks": [THINKING, REDACTED],
            "tool_calls": [TOOL_CALL],
        }
    )
    assert message.content == [
        ContentReasoning(
            reasoning="Let me think.", signature="sig-1", internal="thinking_blocks"
        ),
        ContentReasoning(
            reasoning="opaque-1", redacted=True, internal="thinking_blocks"
        ),
        ContentText(text="Checking."),
    ]


@skip_if_no_openai_package
def test_litellm_proxy_reads_redacted_only_thinking() -> None:
    message = _assistant({"content": "Done.", "thinking_blocks": [REDACTED]})
    assert message.content == [
        ContentReasoning(
            reasoning="opaque-1", redacted=True, internal="thinking_blocks"
        ),
        ContentText(text="Done."),
    ]


@skip_if_no_openai_package
def test_litellm_proxy_reads_thought_signatures() -> None:
    message = _assistant(
        {
            "content": "Answer.",
            "reasoning_content": "Thought summary.",
            "provider_specific_fields": {"thought_signatures": ["gsig-1"]},
        }
    )
    assert message.content == [
        ContentReasoning(
            reasoning="gsig-1", redacted=True, internal="thought_signatures"
        ),
        ContentReasoning(reasoning="Thought summary.", internal="reasoning_content"),
        ContentText(text="Answer."),
    ]


@skip_if_no_openai_package
async def test_litellm_proxy_replays_litellm_reasoning_fields() -> None:
    provider = _provider()
    returned = {
        "content": "Answer.",
        "reasoning_content": "Let me think.",
        "thinking_blocks": [THINKING, REDACTED],
        "provider_specific_fields": {"thought_signatures": ["gsig-1"]},
        "tool_calls": [TOOL_CALL],
    }
    message = _assistant(returned)
    [_, replayed] = await provider.messages_to_openai(
        [ChatMessageUser(content="Hi"), message]
    )
    assert replayed["role"] == "assistant"
    replayed_dict = dict(replayed)
    assert replayed_dict["thinking_blocks"] == returned["thinking_blocks"]
    assert replayed_dict["reasoning_content"] == "Let me think."
    assert replayed_dict["provider_specific_fields"] == {
        "thought_signatures": ["gsig-1"]
    }
    # reasoning is not also written into the text
    assert "<think>" not in str(replayed_dict["content"])
    assert "opaque-1" not in str(replayed_dict["content"])


@skip_if_no_openai_package
async def test_litellm_proxy_replays_reasoning_content_unchanged() -> None:
    # open models return reasoning_content only, which goes back as is
    message = _assistant({"content": "Answer.", "reasoning_content": "Because."})
    [replayed] = await _provider().messages_to_openai([message])
    replayed_dict = dict(replayed)
    assert replayed_dict["reasoning_content"] == "Because."
    assert "thinking_blocks" not in replayed_dict


def _accumulate(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    accumulator = ThinkingBlocksAccumulator()
    for entry in entries:
        accumulator.add(entry)
    return accumulator.blocks()


def test_thinking_blocks_accumulator_signature_repeats_text() -> None:
    # current LiteLLM: the signature entry repeats the block's full text
    assert _accumulate(
        {"type": "thinking", "thinking": "Let me "},
        {"type": "thinking", "thinking": "think."},
        {"type": "thinking", "thinking": "Let me think.", "signature": "sig-1"},
    ) == [THINKING]


def test_thinking_blocks_accumulator_signature_without_text() -> None:
    assert _accumulate(
        {"type": "thinking", "thinking": "Let me "},
        {"type": "thinking", "thinking": "think."},
        {"type": "thinking", "signature": "sig-1"},
    ) == [THINKING]


def test_thinking_blocks_accumulator_signature_with_last_delta() -> None:
    assert _accumulate(
        {"type": "thinking", "thinking": "Let me "},
        {"type": "thinking", "thinking": "think.", "signature": "sig-1"},
    ) == [THINKING]


def test_thinking_blocks_accumulator_separates_blocks() -> None:
    assert _accumulate(
        REDACTED,
        {"type": "thinking", "thinking": "Let me think."},
        {"type": "thinking", "thinking": "Let me think.", "signature": "sig-1"},
        {"type": "redacted_thinking", "data": "opaque-2"},
        {"type": "thinking", "thinking": "Unsigned."},
    ) == [
        REDACTED,
        THINKING,
        {"type": "redacted_thinking", "data": "opaque-2"},
        {"type": "thinking", "thinking": "Unsigned."},
    ]


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> Any:
    from openai.types.chat import ChatCompletionChunk

    return ChatCompletionChunk.model_validate(
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "claude",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
    )


@skip_if_no_openai_package
async def test_litellm_proxy_streams_thinking_blocks() -> None:
    def thinking(entry: dict[str, Any], reasoning_content: str) -> dict[str, Any]:
        # LiteLLM sends each entry both on the delta and in its
        # provider_specific_fields
        return {
            "reasoning_content": reasoning_content,
            "thinking_blocks": [entry],
            "provider_specific_fields": {"thinking_blocks": [entry]},
        }

    chunks = [
        _chunk({"role": "assistant"} | thinking(REDACTED, "")),
        _chunk(thinking({"type": "thinking", "thinking": "Let me "}, "Let me ")),
        _chunk(thinking({"type": "thinking", "thinking": "think."}, "think.")),
        _chunk(thinking(THINKING, "")),
        _chunk({"content": "Answer."}, finish_reason="stop"),
    ]

    async def stream() -> AsyncIterator[Any]:
        for chunk in chunks:
            yield chunk

    completion = await _provider().stream_completion(stream())
    message = completion.choices[0].message
    assert message.model_extra is not None
    assert message.model_extra["thinking_blocks"] == [REDACTED, THINKING]
    assert message.model_extra.get("provider_specific_fields") == {}
    assert getattr(message, "reasoning_content") == "Let me think."
    assert message.content == "Answer."


# Upstream model resolution -----------------------------------------------------

# upstream model string (litellm_params.model or base_model) -> Inspect database
# key, covering the name forms in design/litellm-proxy.md
UPSTREAM_CASES = [
    ("anthropic/claude-sonnet-4-5", "anthropic/claude-sonnet-4-5"),
    ("anthropic/claude-sonnet-4-5-20250929", "anthropic/claude-sonnet-4-5-20250929"),
    ("openai/gpt-5", "openai/gpt-5"),
    ("openai/o3", "openai/o3"),
    ("gemini/gemini-2.5-pro", "google/gemini-2.5-pro"),
    ("xai/grok-4", "grok/grok-4"),
    ("mistral/mistral-small-2506", "mistral/mistral-small-2506"),
    ("deepseek/deepseek-reasoner", "DeepSeek/deepseek-reasoner"),
    ("moonshot/kimi-k2.6", "moonshotai/kimi-k2.6"),
    ("zai/glm-5.3", "z-ai/glm-5.3"),
    ("claude-opus-4-5", "anthropic/claude-opus-4-5"),
    ("gpt-4o", "openai/gpt-4o"),
    ("chatgpt/gpt-5", "openai/gpt-5"),
    ("openai/responses/gpt-5.1", "openai/gpt-5.1"),
    ("openai/ft:gpt-4o-2024-08-06:my-org::abc123", "openai/gpt-4o-2024-08-06"),
    ("text-completion-openai/gpt-3.5-turbo", "openai/gpt-3.5-turbo"),
    (
        "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic/claude-sonnet-4-5-20250929",
    ),
    (
        "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic/claude-sonnet-4-5-20250929",
    ),
    (
        "bedrock/global.anthropic.claude-opus-4-5-20251101-v1:0",
        "anthropic/claude-opus-4-5-20251101",
    ),
    (
        "bedrock/converse/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic/claude-sonnet-4-5-20250929",
    ),
    (
        "bedrock/invoke/anthropic.claude-3-5-sonnet-20240620-v1:0",
        "anthropic/claude-3-5-sonnet-20240620",
    ),
    (
        "bedrock_converse/eu.anthropic.claude-3-7-sonnet-20250219-v1:0",
        "anthropic/claude-3-7-sonnet-20250219",
    ),
    (
        "bedrock/us-gov-west-1/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic/claude-sonnet-4-5-20250929",
    ),
    ("bedrock/us.anthropic.claude-opus-4-6-v1[1m]", "anthropic/claude-opus-4-6"),
    (
        "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0:51k",
        "anthropic/claude-3-5-sonnet-20241022",
    ),
    (
        "bedrock/arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic/claude-sonnet-4-5-20250929",
    ),
    (
        "bedrock/arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/abc123",
        None,
    ),
    ("bedrock/converse/openai.gpt-oss-120b-1:0", "openai/gpt-oss-120b"),
    ("bedrock/meta.llama3-3-70b-instruct-v1:0", "meta-llama/Llama-3.3-70B-Instruct"),
    (
        "bedrock/us.meta.llama4-scout-17b-instruct-v1:0",
        "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    ),
    (
        "bedrock/mistral.mixtral-8x7b-instruct-v0:1",
        "mistralai/Mixtral-8x7B-Instruct-v0.1",
    ),
    ("bedrock/deepseek.r1-v1:0", "deepseek-ai/DeepSeek-R1"),
    ("bedrock/qwen.qwen3-32b-v1:0", "Qwen/Qwen3-32B"),
    ("bedrock/moonshot.kimi-k2-thinking", "moonshotai/Kimi-K2-Thinking"),
    ("bedrock/nvidia.nemotron-nano-9b-v2", "nvidia/NVIDIA-Nemotron-Nano-9B-v2"),
    ("bedrock/amazon.nova-pro-v1:0", None),
    ("vertex_ai/claude-opus-4-5@20251101", "anthropic/claude-opus-4-5@20251101"),
    ("vertex_ai/claude-sonnet-4-5", "anthropic/claude-sonnet-4-5"),
    ("vertex_ai/gemini-2.5-flash", "google/gemini-2.5-flash"),
    ("vertex_ai/gemini-1.5-pro-002", "google/gemini-1.5-pro-002"),
    ("vertex_ai_beta/gemini-3.1-pro-preview", "google/gemini-3.1-pro-preview"),
    ("vertex_ai/openai/gpt-oss-120b-maas", "openai/gpt-oss-120b"),
    ("vertex_ai/deepseek-ai/deepseek-r1-0528-maas", "deepseek-ai/DeepSeek-R1-0528"),
    ("azure/gpt-5", "openai/gpt-5"),
    ("azure/responses/gpt-5.1", "openai/gpt-5.1"),
    ("azure/gpt5_series/gpt-5-mini", "openai/gpt-5-mini"),
    ("azure/eu/gpt-4o", "openai/gpt-4o"),
    ("azure/gpt-35-turbo", "openai/gpt-3.5-turbo"),
    ("azure/o_series/o3-mini", "openai/o3-mini"),
    ("azure/my-prod-deployment", None),
    ("azure_ai/deepseek-r1", "deepseek-ai/DeepSeek-R1"),
    ("azure_ai/grok-4", "grok/grok-4"),
    ("fireworks_ai/accounts/fireworks/models/glm-5p3", "fireworks/glm-5p3"),
    ("fireworks_ai/glm-5p3", "fireworks/glm-5p3"),
    ("openrouter/anthropic/claude-sonnet-4.5", "anthropic/claude-sonnet-4-5"),
    ("openrouter/openai/gpt-5", "openai/gpt-5"),
    ("openrouter/z-ai/glm-4.6:exacto", "zai-org/GLM-4.6"),
    ("openrouter/x-ai/grok-4", "grok/grok-4"),
    (
        "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ),
    ("together_ai/moonshotai/Kimi-K2-Thinking", "moonshotai/Kimi-K2-Thinking"),
    ("hosted_vllm/Qwen/Qwen3-32B", "Qwen/Qwen3-32B"),
    ("openai/meta-llama/Llama-3.3-70B-Instruct", "meta-llama/Llama-3.3-70B-Instruct"),
    ("replicate/openai/gpt-5", "openai/gpt-5"),
    ("deepinfra/deepseek-ai/DeepSeek-V3.1", "deepseek-ai/DeepSeek-V3.1"),
    ("meta-llama/Llama-3.3-70B-Instruct", "meta-llama/Llama-3.3-70B-Instruct"),
    ("openai/gpt-5-mini", "openai/gpt-5-mini"),
    ("google/gemini-2.5-pro", "google/gemini-2.5-pro"),
    ("openai/gpt-5-pro", None),
    ("openai/o3-deep-research", None),
    ("openai/gpt-4-32k", None),
    ("gemini/gemini-2.5-pro-preview-tts", None),
    ("ollama/llama3.1:8b", None),
    # bare Bedrock ids, as operators write base_model
    ("anthropic.claude-sonnet-4-5", "anthropic/claude-sonnet-4-5"),
    (
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic/claude-sonnet-4-5-20250929",
    ),
]


def _deployment(
    model: str | None,
    *,
    alias: str = "alias",
    base_model: str | None = None,
    custom_llm_provider: str | None = None,
) -> ProxyDeployment:
    return ProxyDeployment(
        model_name=alias,
        model=model,
        custom_llm_provider=custom_llm_provider,
        base_model=base_model,
        model_info={},
    )


@pytest.mark.parametrize("upstream,db_key", UPSTREAM_CASES)
def test_resolve_upstream_model(upstream: str, db_key: str | None) -> None:
    resolution = resolve_deployments("alias", [_deployment(upstream)])
    assert resolution is not None
    assert resolution.db_key == db_key


def test_resolve_custom_llm_provider_prepended() -> None:
    resolution = resolve_deployments(
        "alias",
        [_deployment("Qwen/Qwen3-32B", custom_llm_provider="hosted_vllm")],
    )
    assert resolution is not None
    assert resolution.db_key == "Qwen/Qwen3-32B"


def test_resolve_base_model_wins() -> None:
    resolution = resolve_deployments(
        "alias", [_deployment("azure/prod-deployment-7", base_model="azure/gpt-5")]
    )
    assert resolution is not None
    assert resolution.db_key == "openai/gpt-5"


def test_resolve_ignores_unresolved_deployments() -> None:
    resolution = resolve_deployments(
        "alias",
        [
            _deployment(
                "bedrock/arn:aws:bedrock:us-east-1:1:application-inference-profile/x"
            ),
            _deployment("anthropic/claude-sonnet-4-5"),
        ],
    )
    assert resolution is not None
    assert resolution.db_key == "anthropic/claude-sonnet-4-5"


def test_resolve_disagreeing_deployments_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(_litellm_proxy_names.logger, "warning", warnings.append)
    resolution = resolve_deployments(
        "mixed-alias",
        [_deployment("openai/gpt-5"), _deployment("anthropic/claude-sonnet-4-5")],
    )
    assert resolution is not None
    assert resolution.db_key == "openai/gpt-5"
    [warning] = warnings
    assert "openai/gpt-5, anthropic/claude-sonnet-4-5" in warning


def test_resolve_unmatched_keeps_normalized_upstream() -> None:
    resolution = resolve_deployments(
        "alias", [_deployment("azure/responses/gpt-7-preview")]
    )
    assert resolution is not None
    assert resolution.db_key is None
    assert resolution.upstream == "openai/gpt-7-preview"


def _serve(stub: ModelInfoStub, rows: list[dict[str, Any]]) -> None:
    stub.body = json.dumps({"data": rows}).encode()


def _row(alias: str, model: str, **model_info: Any) -> dict[str, Any]:
    return {
        "model_name": alias,
        "litellm_params": {"model": model},
        "model_info": model_info,
    }


@skip_if_no_openai_package
def test_provider_canonical_name_and_family(model_info_stub: ModelInfoStub) -> None:
    provider = _stub_provider(model_info_stub)
    assert provider.canonical_name() == "anthropic/claude-sonnet-4-5"
    assert provider.model_family() == "claude-sonnet-4-5"


@skip_if_no_openai_package
def test_provider_unresolved_upstream(model_info_stub: ModelInfoStub) -> None:
    _serve(model_info_stub, [_row("next", "openai/gpt-7-preview")])
    provider = _stub_provider(model_info_stub, alias="next", require_model_info=False)
    assert provider.canonical_name() == "openai/gpt-7-preview"
    assert provider.model_family() == "gpt-7-preview"


@skip_if_no_openai_package
def test_provider_alias_without_model_info(model_info_stub: ModelInfoStub) -> None:
    provider = _stub_provider(model_info_stub, model_info=False)
    assert provider.canonical_name() == "claude"
    assert provider.model_family() == "claude"
    unlisted = _stub_provider(
        model_info_stub, alias="unlisted", require_model_info=False
    )
    assert unlisted.canonical_name() == "unlisted"
    assert unlisted.model_family() == "unlisted"


@skip_if_no_openai_package
def test_provider_registered_family_wins(
    model_info_stub: ModelInfoStub,
) -> None:
    set_model_info("litellm-proxy/claude", ModelInfo(family="gpt-5"))
    assert _stub_provider(model_info_stub).model_family() == "gpt-5"


@skip_if_no_openai_package
def test_provider_request_shape_follows_upstream(
    model_info_stub: ModelInfoStub,
) -> None:
    _serve(
        model_info_stub,
        [
            _row("prod", "azure/prod-deployment-7", base_model="azure/gpt-5"),
            _row("claude", "anthropic/claude-sonnet-4-5"),
        ],
    )
    gpt_5 = _stub_provider(model_info_stub, alias="prod")
    params = gpt_5.completion_params(GenerateConfig(max_tokens=100), tools=False)
    assert params["max_completion_tokens"] == 100
    assert "max_tokens" not in params
    claude = _stub_provider(model_info_stub)
    assert claude.model_family() == "claude-sonnet-4-5"
    params = claude.completion_params(GenerateConfig(max_tokens=100), tools=False)
    assert params["max_tokens"] == 100


# Model info registration and the gate ------------------------------------------


def _proxy_deployment(**model_info: Any) -> ProxyDeployment:
    return ProxyDeployment(
        model_name="alias",
        model="openai/x",
        custom_llm_provider=None,
        base_model=None,
        model_info=model_info,
    )


def test_proxy_model_info_fields() -> None:
    info = proxy_model_info(
        [
            _proxy_deployment(
                max_input_tokens=272000,
                max_output_tokens=128000,
                supports_reasoning=True,
                default_reasoning_effort="medium",
                input_cost_per_token=1.25e-06,
                output_cost_per_token=1e-05,
                cache_read_input_token_cost=1.25e-07,
                cache_creation_input_token_cost=None,
            )
        ]
    )
    assert info == ModelInfo(
        context_length=272000,
        output_tokens=128000,
        reasoning=True,
        reasoning_effort_default="medium",
        cost=ModelCost(
            input=1.25, output=10.0, input_cache_write=1.25, input_cache_read=0.125
        ),
    )


def test_proxy_model_info_combines_deployments() -> None:
    info = proxy_model_info(
        [
            _proxy_deployment(
                max_input_tokens=1000000,
                supports_reasoning=True,
                input_cost_per_token=3e-06,
                output_cost_per_token=1.5e-05,
            ),
            _proxy_deployment(
                max_input_tokens=200000,
                max_output_tokens=64000,
                supports_reasoning=False,
                input_cost_per_token=6e-06,
                output_cost_per_token=2.25e-05,
                cache_read_input_token_cost=6e-07,
            ),
            # prices without an output price are not a cost
            _proxy_deployment(input_cost_per_token=1e-03),
        ]
    )
    assert info is not None
    assert (info.context_length, info.output_tokens) == (200000, 64000)
    assert info.reasoning is None
    assert info.cost == ModelCost(
        input=6.0, output=22.5, input_cache_write=6.0, input_cache_read=3.0
    )


@pytest.mark.parametrize(
    "model_info",
    [
        {},
        {"max_input_tokens": "200000", "supports_reasoning": "yes"},
        {"max_input_tokens": 0, "max_output_tokens": True},
        {"input_cost_per_token": -1, "output_cost_per_token": 1e-06},
    ],
)
def test_proxy_model_info_ignores_missing_and_invalid(
    model_info: dict[str, Any],
) -> None:
    assert proxy_model_info([_proxy_deployment(**model_info)]) is None


def test_merged_model_info_precedence() -> None:
    primary = ModelInfo(family="gpt-5", output_tokens=1000)
    secondary = ModelInfo(
        organization="OpenAI",
        context_length=400000,
        output_tokens=128000,
        _input_tokens=272000,
    )
    merged = merged_model_info(primary, secondary)
    assert merged.family == "gpt-5"
    assert merged.output_tokens == 1000
    assert merged.organization == "OpenAI"
    assert (merged.context_length, merged.input_tokens) == (400000, 272000)
    assert merged_model_info(None, None) == ModelInfo()


PRICES = {"input_cost_per_token": 3e-06, "output_cost_per_token": 1.5e-05}


def _stub_model(stub: ModelInfoStub, alias: str, **model_args: Any) -> Model:
    model_args = {"base_url": stub.url, "api_key": "sk-stub"} | model_args
    return get_model(f"litellm-proxy/{alias}", **model_args)


@skip_if_no_openai_package
def test_registers_database_info_with_proxy_prices(
    model_info_stub: ModelInfoStub,
) -> None:
    _serve(
        model_info_stub,
        [_row("prod", "azure/prod-deployment-7", base_model="azure/gpt-5", **PRICES)],
    )
    model = _stub_model(model_info_stub, "prod")
    info = _get_model_info_direct(model)
    assert info is not None
    assert (info.organization, info.context_length) == ("OpenAI", 400000)
    assert get_model_input_tokens(model) == 272000
    assert info.cost is not None and (info.cost.input, info.cost.output) == (3, 15)


@skip_if_no_openai_package
def test_registers_proxy_only_model(model_info_stub: ModelInfoStub) -> None:
    _serve(
        model_info_stub,
        [_row("local", "hosted_vllm/my-model", max_input_tokens=32000, **PRICES)],
    )
    model = _stub_model(model_info_stub, "local")
    assert get_model_input_tokens(model) == 32000
    info = _get_model_info_direct(model)
    assert info is not None and info.cost is not None


@skip_if_no_openai_package
def test_user_registration_fields_win(model_info_stub: ModelInfoStub) -> None:
    _serve(model_info_stub, [_row("claude", "anthropic/claude-sonnet-4-5", **PRICES)])
    set_model_info("litellm-proxy/claude", ModelInfo(output_tokens=1000))
    set_model_cost(
        "anthropic/claude-sonnet-4-5",
        ModelCost(input=1, output=2, input_cache_write=1, input_cache_read=1),
    )
    for _ in range(2):  # constructing again merges from the user's entry again
        model = _stub_model(model_info_stub, "claude", memoize=False)
        info = _get_model_info_direct(model)
        assert info is not None
        assert info.output_tokens == 1000
        assert info.context_length == 200000
        assert info.cost is not None and info.cost.input == 1


@skip_if_no_openai_package
def test_gate_rejects_alias_without_model_info(
    model_info_stub: ModelInfoStub,
) -> None:
    _serve(model_info_stub, [_row("next", "openai/gpt-7-preview")])
    with pytest.raises(PrerequisiteError) as ex:
        _stub_model(model_info_stub, "next")
    message = str(ex.value.message)
    assert "'openai/gpt-7-preview' is not in Inspect's model database" in message
    assert "base_model" in message
    assert 'set_model_info("litellm-proxy/next"' in message
    assert "-M require_model_info=false" in message

    with pytest.raises(PrerequisiteError, match="has no deployment for it"):
        _stub_model(model_info_stub, "unlisted")


@skip_if_no_openai_package
def test_gate_accepts_user_context_window(model_info_stub: ModelInfoStub) -> None:
    _serve(model_info_stub, [_row("next", "openai/gpt-7-preview")])
    set_model_info("litellm-proxy/next", ModelInfo(context_length=500000))
    assert get_model_input_tokens(_stub_model(model_info_stub, "next")) == 500000


@skip_if_no_openai_package
def test_gate_disabled_registers_empty_info(model_info_stub: ModelInfoStub) -> None:
    # an alias that would fuzzy match a database model
    _serve(model_info_stub, [_row("gpt-5-mini", "openai/opaque-deployment")])
    model = _stub_model(model_info_stub, "gpt-5-mini", require_model_info=False)
    assert _get_model_info_direct(model) == ModelInfo()
    assert get_model_input_tokens(model) is None


@skip_if_no_openai_package
def test_require_model_info_must_be_bool(model_info_stub: ModelInfoStub) -> None:
    with pytest.raises(ValueError, match="require_model_info must be a bool"):
        _stub_model(model_info_stub, "claude", require_model_info="no")


@skip_if_no_openai_package
def test_no_registration_without_model_info(model_info_stub: ModelInfoStub) -> None:
    _stub_model(model_info_stub, "unlisted", model_info=False)
    assert _get_custom_model_info("litellm-proxy/unlisted") is None
    assert model_info_stub.requests == []


# Error messages as LiteLLM proxy 1.104 sends them (the `message` of the error
# body), with the stop reason and upstream message they should map to.
LITELLM_ERROR_MESSAGES = [
    pytest.param(
        "litellm.ContextWindowExceededError: litellm.BadRequestError: "
        'AnthropicError - b\'{"type": "error", "error": {"type": '
        '"invalid_request_error", "message": "prompt is too long: 250000 tokens > '
        "200000 maximum\"}}'\nmodel=a. context_window_fallbacks=None. "
        "fallbacks=None.\n\nSet 'context_window_fallback' - "
        "https://docs.litellm.ai/docs/routing#fallbacks\n\nLiteLLM: model group "
        "'a' failed with the error above. No fallback was attempted.",
        "model_length",
        "prompt is too long: 250000 tokens > 200000 maximum",
        id="anthropic-streaming",
    ),
    pytest.param(
        "litellm.BadRequestError: OpenAIException - Your input exceeds the "
        "context window of this model. Please adjust your input and try again."
        "\n\nLiteLLM: model group 'o' failed with the error above. No fallback "
        "was attempted.",
        "model_length",
        "Your input exceeds the context window of this model. Please adjust your "
        "input and try again.",
        id="openai-unmapped-by-litellm",
    ),
    pytest.param(
        'b\'{"error": {"code": 400, "message": "The input token count (1200000) '
        'exceeds the maximum number of tokens allowed (1048576).", "status": '
        "\"INVALID_ARGUMENT\"}}'\n\nLiteLLM: model group 'g' failed with the "
        "error above. No fallback was attempted.",
        "model_length",
        "The input token count (1200000) exceeds the maximum number of tokens "
        "allowed (1048576).",
        id="gemini-streaming-unprefixed",
    ),
    pytest.param(
        "litellm.ContextWindowExceededError: litellm.BadRequestError: "
        'BedrockException: Context Window Error - {"message": "Input is too long '
        'for requested model."}\nmodel=b. context_window_fallbacks=None. '
        "fallbacks=None.",
        "model_length",
        "Input is too long for requested model.",
        id="bedrock",
    ),
    pytest.param(
        "litellm.BadRequestError: MoonshotException - Invalid request: Your "
        "request exceeded model token limit: 262144\n\nLiteLLM: model group 'm' "
        "failed with the error above. No fallback was attempted.",
        "model_length",
        "Invalid request: Your request exceeded model token limit: 262144",
        id="moonshot",
    ),
    pytest.param(
        "litellm.BadRequestError: litellm.ContentPolicyViolationError: "
        'ContentPolicyViolationError: OpenAIException - {"error": {"message": '
        '"Invalid prompt: your prompt was flagged.", "type": '
        '"invalid_request_error", "param": null, "code": "invalid_prompt"}}\n'
        "model=o. content_policy_fallback=None. fallbacks=None.",
        "content_filter",
        "Invalid prompt: your prompt was flagged.",
        id="openai-invalid-prompt",
    ),
    pytest.param(
        "litellm.BadRequestError: litellm.ContentPolicyViolationError: The "
        "response was filtered due to the prompt triggering Azure OpenAI's "
        "content management policy.\nmodel=az. content_policy_fallback=None.",
        "content_filter",
        "The response was filtered due to the prompt triggering Azure OpenAI's "
        "content management policy.",
        id="azure-content-filter",
    ),
]


@pytest.mark.parametrize("message,stop_reason,content", LITELLM_ERROR_MESSAGES)
def test_litellm_error_model_output(
    message: str, stop_reason: str, content: str
) -> None:
    output = litellm_error_model_output("model", message)
    assert output is not None
    assert output.stop_reason == stop_reason
    assert output.completion == content
    details = output.choices[0].stop_details
    if stop_reason == "content_filter":
        assert details is not None and details.type == "refusal"
        assert details.explanation == content
    else:
        assert details is None


@pytest.mark.parametrize(
    "message",
    [
        "litellm.RateLimitError: AnthropicException - Rate limit exceeded",
        "litellm.InternalServerError: AnthropicError - Overloaded",
        "litellm.BadRequestError: OpenAIException - Invalid 'tools[0].name'",
    ],
)
def test_litellm_error_model_output_unrecognized(message: str) -> None:
    assert litellm_error_model_output("model", message) is None


def test_upstream_message_keeps_unparsed_message() -> None:
    assert upstream_message("something went wrong") == "something went wrong"
    assert upstream_message("litellm.BadRequestError: ") == "litellm.BadRequestError: "


def _bad_request(message: str) -> BadRequestError:
    request = httpx2.Request("POST", "http://proxy/v1/chat/completions")
    return BadRequestError(
        f"Error code: 400 - {message}",
        response=httpx2.Response(400, request=request),
        body={
            "message": message,
            "type": "invalid_request_error",
            "param": None,
            "code": "400",
        },
    )


@skip_if_no_openai_package
def test_provider_bad_request_context_window() -> None:
    output = _provider().handle_bad_request(
        _bad_request(
            "litellm.ContextWindowExceededError: litellm.BadRequestError: "
            "AnthropicError - prompt is too long: 250000 tokens > 200000 maximum"
        )
    )
    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "model_length"


@skip_if_no_openai_package
def test_provider_bad_request_blocked_records_upstream_message() -> None:
    output = _provider().handle_bad_request(
        _bad_request(
            'litellm.BadRequestError: AnthropicException - {"type": "error", '
            '"error": {"type": "invalid_request_error", "message": "Output '
            'blocked by content filtering policy"}}'
        )
    )
    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "content_filter"
    assert output.completion == "Output blocked by content filtering policy"


@skip_if_no_openai_package
def test_provider_bad_request_unrecognized() -> None:
    ex = _bad_request("litellm.BadRequestError: OpenAIException - Invalid tools")
    assert _provider().handle_bad_request(ex) is ex


@skip_if_no_openai_package
def test_provider_stream_error_context_window() -> None:
    output = _provider().handle_stream_error(
        OpenAIResponseError(
            "invalid_request_error",
            "litellm.ContextWindowExceededError: litellm.BadRequestError: "
            'ContextWindowExceededError: Vertex_ai_betaException - b\'{"error": '
            '{"code": 400, "message": "The input token count (1200000) exceeds '
            "the maximum number of tokens allowed (1048576).\"}}'",
        )
    )
    assert output is not None and output.stop_reason == "model_length"


@skip_if_no_openai_package
def test_provider_stream_error_keeps_retryable_errors() -> None:
    request = httpx2.Request("POST", "http://proxy/v1/chat/completions")
    overloaded = APIError(
        "litellm.InternalServerError: AnthropicError - Overloaded",
        request,
        body={"message": "litellm.InternalServerError: AnthropicError - Overloaded"},
    )
    assert _provider().handle_stream_error(overloaded) is None

    # status errors are left to retry classification whatever their message
    status_error = APIStatusError(
        "litellm.ContextWindowExceededError: prompt is too long",
        response=httpx2.Response(500, request=request),
        body=None,
    )
    assert _provider().handle_stream_error(status_error) is None


# Upstream errors and refusals through a proxy (`test_helpers.litellm_proxy.errors`):
# the stop reason of the output, or the retry kind of the raised error.
ERROR_EXPECTATIONS: dict[str, str] = {
    "anthropic-context": "model_length",
    "anthropic-blocked": "content_filter",
    "anthropic-rate-limit": "retry:rate_limit",
    "anthropic-overloaded": "retry:transient",
    "anthropic-refusal": "content_filter",
    "anthropic-context-stop": "model_length",
    "openai-context": "model_length",
    "openai-invalid-prompt": "content_filter",
    "openai-cyber": "content_filter",
    "gemini-context": "model_length",
    "gemini-rate-limit": "retry:rate_limit",
    "gemini-unavailable": "retry:transient",
    "gemini-safety": "content_filter",
    "bedrock-context": "model_length",
    "bedrock-guardrail": "content_filter",
    "deepseek-context": "model_length",
    "moonshot-context": "model_length",
    "azure-content-filter": "content_filter",
}


def _error_cases() -> list[Any]:
    cases: list[Any] = []
    for scenario in [*ERROR_EXPECTATIONS, "anthropic-overloaded-mid-stream"]:
        for responses_api in (False, True):
            for stream in (False, True):
                # the fake speaks Converse JSON only, not the eventstream encoding
                if scenario.startswith("bedrock") and stream:
                    continue
                if scenario == "anthropic-overloaded-mid-stream":
                    expected = "retry:transient" if stream else "stop"
                else:
                    expected = ERROR_EXPECTATIONS[scenario]
                # LiteLLM maps Anthropic's model_context_window_exceeded to "stop"
                marks = (
                    [pytest.mark.xfail(strict=True, reason="LiteLLM #43012")]
                    if scenario == "anthropic-context-stop"
                    else []
                )
                api = "responses" if responses_api else "chat"
                cases.append(
                    pytest.param(
                        scenario,
                        responses_api,
                        stream,
                        expected,
                        marks=marks,
                        id=f"{scenario}-{api}-{'stream' if stream else 'nostream'}",
                    )
                )
    return cases


@pytest.fixture(scope="module")
def error_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiteLLMProxy]:
    with fake_upstream(error_route) as upstream:
        config = {
            "model_list": error_deployments(upstream.docker_url),
            # Inspect's retries only, so each error reaches the client once
            "router_settings": {"num_retries": 0},
        }
        with run_litellm_proxy(
            tmp_path_factory.mktemp("litellm-errors"), config
        ) as proxy:
            yield proxy


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("scenario,responses_api,stream,expected", _error_cases())
async def test_litellm_proxy_error_handling(
    error_proxy: LiteLLMProxy,
    scenario: str,
    responses_api: bool,
    stream: bool,
    expected: str,
) -> None:
    api = _proxy_api(
        get_model(
            f"litellm-proxy/{scenario}",
            base_url=error_proxy.base_url,
            api_key=error_proxy.api_key,
            responses_api=responses_api,
            stream=stream,
            max_retries=0,
            model_info=False,
        )
    )
    try:
        result = await api.generate(
            [ChatMessageUser(content="Hello")], [], "none", GenerateConfig()
        )
        output = result[0] if isinstance(result, tuple) else result
    except Exception as ex:
        output = ex

    if expected.startswith("retry:"):
        assert isinstance(output, Exception), output
        decision = api.should_retry(output)
        assert isinstance(decision, RetryDecision) and decision.retry, output
        assert decision.kind == expected.removeprefix("retry:")
    else:
        assert isinstance(output, ModelOutput), output
        assert output.stop_reason == expected
