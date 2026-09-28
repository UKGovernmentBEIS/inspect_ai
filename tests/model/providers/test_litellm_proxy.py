"""Tests for the LiteLLM proxy provider.

Most are unit tests or use a local stub server for the proxy's model info
listing. Those marked `skip_if_no_litellm_proxy` run against a local LiteLLM
proxy in Docker, from a locally available image with fake upstreams, so they
need no network access or provider keys (see `test_helpers.litellm_proxy.proxy`).
Reasoning round trips through a proxy are in `test_litellm_proxy_reasoning.py`.
"""

import json
import socket
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal, NamedTuple

import httpx
import httpx2
import pytest
from openai import APIError, APIStatusError, BadRequestError
from test_helpers.litellm_proxy.errors import (
    _anthropic_error,
    error_deployments,
    error_route,
)
from test_helpers.litellm_proxy.proxy import (
    CALL_ID_HEADER,
    LiteLLMProxy,
    isolate_model_info,
    run_litellm_proxy,
    skip_if_no_litellm_proxy,
    skip_if_no_litellm_proxy_database,
    upstream_exchange,
)
from test_helpers.litellm_proxy.stubs import (
    SSE,
    Reply,
    StubRequest,
    fake_upstream,
    route,
)
from test_helpers.utils import skip_if_no_openai_package

from inspect_ai._util import logger as inspect_logger
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelCost,
    ModelInfo,
    ModelOutput,
    get_model,
    set_model_info,
)
from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.model._model import RetryDecision
from inspect_ai.model._model_info import (
    MODEL_INFO_LOOKUP_API_KEY,
    _get_custom_model_info,
    _get_model_info_direct,
    get_model_input_tokens,
    set_model_cost,
)
from inspect_ai.model._openai import OpenAIResponseError
from inspect_ai.model._openai_responses import openai_responses_tools
from inspect_ai.model._providers import (
    _litellm_proxy_model_info,
    _litellm_proxy_names,
)
from inspect_ai.model._providers import litellm_proxy as litellm_proxy_module
from inspect_ai.model._providers._first_party import FRONTIER_MODELS
from inspect_ai.model._providers._litellm_proxy_caching import (
    cache_write_ttl,
    with_cache_breakpoints,
    with_tool_cache_breakpoint,
)
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
from inspect_ai.model._providers._litellm_proxy_reasoning_effort import (
    next_effort,
    rejected_effort,
    rejected_thinking,
)
from inspect_ai.model._providers._litellm_proxy_vendor import (
    Vendor,
    claude_thinks_adaptively,
    frontier_base_model,
    upstream_vendor,
)
from inspect_ai.model._providers.litellm_proxy import (
    LITELLM_PROXY_API_BASE,
    LITELLM_PROXY_BASE_URL,
    LiteLLMProxyAPI,
    PrefillNotSupportedError,
    merged_model_info,
)
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolInfo,
    ToolParam,
    ToolParams,
    code_execution,
    computer,
    web_search,
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
    # LiteLLM's mock_response can't stream Responses, which is the default for
    # an OpenAI route (streaming is covered against fake upstreams)
    model = _proxy_model(litellm_proxy, responses_api=True, stream=False)
    output = await model.generate("Hello")
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
    [deployment] = _proxy_api(_proxy_model(litellm_proxy))._deployments or []
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
    [deployment] = _proxy_api(model)._deployments or []
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


KEY_NOT_FOUND = (
    404,
    {"error": {"message": "Key not found in database", "type": "not_found_error"}},
)
"""LiteLLM's /key/info answer for the master key (no key record)."""


@dataclass
class ModelInfoStub:
    url: str
    status: int = 200
    body: bytes = json.dumps({"data": STUB_ROWS}).encode()
    requests: list[dict[str, str]] = field(default_factory=list)
    release: threading.Event = field(default_factory=threading.Event)
    hang: bool = False
    key_info: tuple[int, Any] = KEY_NOT_FOUND
    """Status and body for /key/info."""
    team_info: tuple[int, Any] = KEY_NOT_FOUND
    """Status and body for /team/info."""

    def model_info_requests(self) -> list[dict[str, str]]:
        return [r for r in self.requests if r["path"].endswith("/model/info")]


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
            status, body = stub.status, stub.body
            if "/key/info" in self.path or "/team/info" in self.path:
                reply = stub.key_info if "/key/info" in self.path else stub.team_info
                status, body = reply[0], json.dumps(reply[1]).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
    assert provider._deployments == [
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
    [request] = model_info_stub.model_info_requests()
    assert request["path"] == "/v1/model/info"
    assert request["Authorization"] == "Bearer sk-stub"
    assert request["x-gateway-token"] == "gateway"


@skip_if_no_openai_package
def test_model_info_alias_not_listed(model_info_stub: ModelInfoStub) -> None:
    provider = _stub_provider(
        model_info_stub, alias="missing", require_model_info=False
    )
    assert provider._deployments == []


@skip_if_no_openai_package
def test_model_info_cached_per_base_url_and_key(
    model_info_stub: ModelInfoStub,
) -> None:
    _stub_provider(model_info_stub)
    _stub_provider(model_info_stub, alias="other")
    assert len(model_info_stub.model_info_requests()) == 1
    _stub_provider(model_info_stub, api_key="sk-other")
    assert len(model_info_stub.model_info_requests()) == 2


@skip_if_no_openai_package
def test_model_info_fetch_skipped(model_info_stub: ModelInfoStub) -> None:
    assert _stub_provider(model_info_stub, model_info=False)._deployments is None
    placeholder = _stub_provider(model_info_stub, api_key=MODEL_INFO_LOOKUP_API_KEY)
    assert placeholder._deployments is None
    assert model_info_stub.requests == []


# Key and team aliases ---------------------------------------------------------

ALIAS_ROWS = [
    {
        "model_name": "target-a",
        "litellm_params": {"model": "anthropic/claude-sonnet-4-5"},
        "model_info": {"max_input_tokens": 200000},
    },
    {
        "model_name": "target-b",
        "litellm_params": {"model": "openai/gpt-5"},
        "model_info": {"max_input_tokens": 272000},
    },
    {
        "model_name": "shadow",
        "litellm_params": {"model": "openai/gpt-5-mini"},
        "model_info": {"max_input_tokens": 272000},
    },
]


def _key_info(aliases: dict[str, str], team_id: str | None = None) -> Any:
    return (200, {"key": "hash", "info": {"aliases": aliases, "team_id": team_id}})


def _team_info(aliases: dict[str, str]) -> Any:
    return (
        200,
        {
            "team_id": "t1",
            "team_info": {
                "model_aliases": None,
                "litellm_model_table": {"model_aliases": aliases},
            },
        },
    )


def _key_alias_provider(
    stub: ModelInfoStub, alias: str, **model_args: Any
) -> LiteLLMProxyAPI:
    stub.body = json.dumps({"data": ALIAS_ROWS}).encode()
    return _stub_provider(stub, alias=alias, memoize=False, **model_args)


@skip_if_no_openai_package
def test_key_alias_resolves(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info({"my-alias": "target-a"})
    provider = _key_alias_provider(model_info_stub, "my-alias")
    assert provider._alias_target == "target-a"
    assert [d.model_name for d in provider._deployments or []] == ["target-a"]
    assert provider.canonical_name() == "anthropic/claude-sonnet-4-5"
    info = _get_model_info_direct("litellm-proxy/my-alias")
    assert info is not None and info.context_length == 200000
    # served at the proxy root, not under /v1
    paths = [r["path"] for r in model_info_stub.requests]
    assert paths == ["/v1/model/info", "/key/info"]
    assert model_info_stub.requests[1]["Authorization"] == "Bearer sk-stub"


@skip_if_no_openai_package
def test_team_alias_resolves(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info({}, team_id="t1")
    model_info_stub.team_info = _team_info({"team-alias": "target-a"})
    provider = _key_alias_provider(model_info_stub, "team-alias")
    assert provider._alias_target == "target-a"
    assert model_info_stub.requests[-1]["path"] == "/team/info?team_id=t1"


@skip_if_no_openai_package
def test_team_alias_wins_over_key_alias(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info({"both": "target-a"}, team_id="t1")
    model_info_stub.team_info = _team_info({"both": "target-b"})
    assert _key_alias_provider(model_info_stub, "both")._alias_target == "target-b"


@skip_if_no_openai_package
def test_key_alias_shadows_listed_model(model_info_stub: ModelInfoStub) -> None:
    # LiteLLM routes a key alias before looking at model names
    model_info_stub.key_info = _key_info({"shadow": "target-a"})
    provider = _key_alias_provider(model_info_stub, "shadow")
    assert provider.canonical_name() == "anthropic/claude-sonnet-4-5"


@skip_if_no_openai_package
def test_alias_chain_and_cycle(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info(
        {"k1": "k2", "k2": "target-a", "c1": "c2", "c2": "c1"}
    )
    assert _key_alias_provider(model_info_stub, "k1")._alias_target == "target-a"
    cycle = _key_alias_provider(model_info_stub, "c1", require_model_info=False)
    assert cycle._alias_target == "c2"
    assert cycle._deployments == []


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "key_aliases,team_aliases,alias,target",
    [
        # LiteLLM applies a team alias once, without following team chains
        ({}, {"t1": "target-b", "target-b": "target-a"}, "t1", "target-b"),
        # a key alias's target is not looked up in the team aliases
        ({"a": "target-b"}, {"target-b": "target-a"}, "a", "target-b"),
        # key aliases apply to the team alias's target
        ({"target-b": "target-a"}, {"t1": "target-b"}, "t1", "target-a"),
    ],
)
def test_alias_order_matches_litellm(
    model_info_stub: ModelInfoStub,
    key_aliases: dict[str, str],
    team_aliases: dict[str, str],
    alias: str,
    target: str,
) -> None:
    model_info_stub.key_info = _key_info(key_aliases, team_id="t1")
    model_info_stub.team_info = _team_info(team_aliases)
    assert _key_alias_provider(model_info_stub, alias)._routed_name() == target


@skip_if_no_openai_package
def test_alias_default_follows_target_route(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info({"fast": "target-b"})
    assert _key_alias_provider(model_info_stub, "fast").responses_api is True


@skip_if_no_openai_package
def test_alias_lookups_cached(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info({"my-alias": "target-a"})
    _key_alias_provider(model_info_stub, "my-alias")
    _key_alias_provider(model_info_stub, "target-a")
    paths = [r["path"] for r in model_info_stub.requests]
    assert paths.count("/key/info") == 1


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "key_info",
    [
        KEY_NOT_FOUND,
        # a proxy without a database, for the master key and for other keys
        (
            500,
            {
                "error": {
                    "message": "Database not connected. Connect a database to "
                    "your proxy",
                    "type": "internal_server_error",
                }
            },
        ),
        (400, {"error": {"message": "No connected db.", "type": "no_db_connection"}}),
    ],
)
def test_no_aliases_is_not_an_error(
    model_info_stub: ModelInfoStub, key_info: Any
) -> None:
    model_info_stub.key_info = key_info
    with pytest.raises(PrerequisiteError) as ex:
        _key_alias_provider(model_info_stub, "unlisted")
    assert "not an alias of the API key or its team" in str(ex.value)
    assert "could not be read" not in str(ex.value)


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "key_info,team_info,cause",
    [
        (
            _key_info({}, team_id="t2"),
            (
                403,
                {"error": {"message": "Team key not authorized", "type": "auth_error"}},
            ),
            "HTTP 403: Team key not authorized",
        ),
        # a 404 that isn't LiteLLM's "no key record" (e.g. from a gateway)
        ((404, {"detail": "Not Found"}), KEY_NOT_FOUND, "HTTP 404"),
    ],
)
def test_alias_read_failure_reported(
    model_info_stub: ModelInfoStub,
    monkeypatch: pytest.MonkeyPatch,
    key_info: Any,
    team_info: Any,
    cause: str,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    model_info_stub.key_info = key_info
    model_info_stub.team_info = team_info
    with pytest.raises(PrerequisiteError) as ex:
        _key_alias_provider(model_info_stub, "unlisted")
    assert "could not be read" in str(ex.value)
    assert cause in str(ex.value)
    # a listed model is still usable, with a warning that aliases were not
    # applied
    assert _key_alias_provider(model_info_stub, "target-a")._deployments
    [warning] = warnings
    assert "Could not read the key and team model aliases" in warning
    assert cause in warning


@skip_if_no_openai_package
def test_alias_target_not_listed(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info({"gone": "retired-model"})
    with pytest.raises(PrerequisiteError, match="alias for 'retired-model'"):
        _key_alias_provider(model_info_stub, "gone")
    provider = _key_alias_provider(model_info_stub, "gone", require_model_info=False)
    assert provider.canonical_name() == "retired-model"
    assert provider.model_family() == "retired-model"


@skip_if_no_openai_package
def test_alias_model_info_error_names_target(model_info_stub: ModelInfoStub) -> None:
    model_info_stub.key_info = _key_info({"fast": "target-x"})
    model_info_stub.body = json.dumps(
        {"data": [_row("target-x", "openai/orion-22")]}
    ).encode()
    with pytest.raises(PrerequisiteError) as ex:
        _stub_provider(model_info_stub, alias="fast", memoize=False)
    message = str(ex.value)
    assert "model 'fast' (a key or team alias for 'target-x')" in message
    assert "add model_info to the 'target-x' deployment" in message


@skip_if_no_openai_package
def test_alias_vendor_from_target(model_info_stub: ModelInfoStub) -> None:
    # an opaque upstream: the target's name is the best evidence of the vendor
    model_info_stub.key_info = _key_info({"gpt-fast": "claude-x"})
    arn = "bedrock/arn:aws:bedrock:us-east-1:1:application-inference-profile/x"
    model_info_stub.body = json.dumps(
        {"data": [_row("claude-x", arn, max_input_tokens=200000)]}
    ).encode()
    provider = _stub_provider(model_info_stub, alias="gpt-fast", memoize=False)
    assert provider._vendor == "anthropic"


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "suffix,key_info_path",
    [("", "/key/info"), ("/v1/", "/key/info"), ("/litellm/v1", "/litellm/key/info")],
)
def test_alias_urls(
    model_info_stub: ModelInfoStub, suffix: str, key_info_path: str
) -> None:
    root = model_info_stub.url.removesuffix("/v1")
    model_info_stub.key_info = _key_info({"my-alias": "target-a"})
    _key_alias_provider(model_info_stub, "target-a", base_url=root + suffix)
    paths = [r["path"] for r in model_info_stub.requests]
    assert key_info_path in paths


DB_PROXY_CONFIG: dict[str, Any] = {
    "model_list": [
        {
            "model_name": name,
            "litellm_params": {
                "model": model,
                "api_key": "fake",
                "mock_response": name,
            },
        }
        for name, model in [
            ("target-a", "openai/gpt-5"),
            ("target-b", "anthropic/claude-sonnet-4-5"),
            ("shadow", "openai/gpt-5-mini"),
        ]
    ]
}


class AliasKeys(NamedTuple):
    proxy: LiteLLMProxy
    key: str
    """A virtual key with key aliases."""

    team_key: str
    """A key of a team with team aliases."""


@pytest.fixture(scope="module")
def alias_keys(tmp_path_factory: pytest.TempPathFactory) -> Iterator[AliasKeys]:
    with run_litellm_proxy(
        tmp_path_factory.mktemp("litellm-db"), DB_PROXY_CONFIG, database=True
    ) as proxy:
        admin = {"Authorization": f"Bearer {proxy.api_key}"}
        root = proxy.base_url.removesuffix("/v1")

        def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
            response = httpx.post(f"{root}{path}", json=body, headers=admin, timeout=60)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

        key = post(
            "/key/generate",
            {"aliases": {"key-alias": "target-a", "shadow": "target-a"}},
        )
        team = post("/team/new", {"model_aliases": {"team-alias": "target-b"}})
        team_key = post("/key/generate", {"team_id": team["team_id"]})
        yield AliasKeys(proxy=proxy, key=key["key"], team_key=team_key["key"])


@skip_if_no_openai_package
@skip_if_no_litellm_proxy_database
@pytest.mark.parametrize(
    "alias,team,target,canonical",
    [
        ("key-alias", False, "target-a", "openai/gpt-5"),
        # the key alias wins over the listed model of the same name
        ("shadow", False, "target-a", "openai/gpt-5"),
        ("team-alias", True, "target-b", "anthropic/claude-sonnet-4-5"),
    ],
)
async def test_aliases_through_proxy(
    alias_keys: AliasKeys,
    clear_model_info_cache: None,
    alias: str,
    team: bool,
    target: str,
    canonical: str,
) -> None:
    model = get_model(
        f"litellm-proxy/{alias}",
        base_url=alias_keys.proxy.base_url,
        api_key=alias_keys.team_key if team else alias_keys.key,
        # LiteLLM's mock_response can't stream Responses
        stream=False,
        memoize=False,
    )
    api = _proxy_api(model)
    assert api._alias_target == target
    assert api.canonical_name() == canonical
    # the proxy routes the alias to the same deployment (its mock response)
    output = await model.generate("Hello")
    assert output.completion == target


# Responses API default -------------------------------------------------------

VLLM_BASE = "http://vllm.internal:8000/v1"


def _route_row(
    model: str,
    *,
    alias: str = "m",
    custom_llm_provider: str | None = None,
    api_base: str | None = None,
    base_model: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"model": model}
    if custom_llm_provider:
        params["custom_llm_provider"] = custom_llm_provider
    if api_base:
        params["api_base"] = api_base
    info: dict[str, Any] = {"max_input_tokens": 200000}
    if base_model:
        info["base_model"] = base_model
    return {"model_name": alias, "litellm_params": params, "model_info": info}


def _route_provider(
    stub: ModelInfoStub, rows: list[dict[str, Any]], **model_args: Any
) -> LiteLLMProxyAPI:
    stub.body = json.dumps({"data": rows}).encode()
    _litellm_proxy_model_info._clear_cache()
    return _stub_provider(stub, alias="m", memoize=False, **model_args)


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "rows,expected",
    [
        ([_route_row("openai/gpt-5.5")], True),
        ([_route_row("gpt-5")], True),
        ([_route_row("openai/o3")], True),
        ([_route_row("openai/codex-mini-latest")], True),
        ([_route_row("openai/responses/gpt-5")], True),
        ([_route_row("openai/gpt-5", api_base="https://api.openai.com/v1")], True),
        ([_route_row("openai/gpt-5", api_base="https://us.api.openai.com/v1")], True),
        ([_route_row("openai/gpt-5", custom_llm_provider="openai")], True),
        # later GPT versions, including ones Inspect's database doesn't know
        ([_route_row("openai/gpt-6-astra")], True),
        ([_route_row("openai/gpt-7")], True),
        ([_route_row("openai/orion-22", base_model="openai/gpt-6-astra")], True),
        # an unrecognized name may be another server behind OPENAI_API_BASE
        ([_route_row("openai/orion-22")], False),
        ([_route_row("azure/orion-22", api_base="https://x.azure.com")], False),
        ([_route_row("openai/text-embedding-3-large")], False),
        ([_route_row("openai/gpt-4.1")], False),
        ([_route_row("openai/gpt-oss-120b")], False),
        ([_route_row("azure/gpt-5", api_base="https://x.openai.azure.com")], False),
        ([_route_row("openai/gpt-5", api_base=VLLM_BASE)], False),
        (
            [
                _route_row(
                    "my-served-model",
                    custom_llm_provider="openai",
                    api_base=VLLM_BASE,
                    base_model="openai/gpt-5",
                )
            ],
            False,
        ),
        (
            [_route_row("anthropic/claude-sonnet-5", base_model="openai/gpt-5")],
            False,
        ),
        ([_route_row("openai/gpt-5"), _route_row("azure/gpt-5")], False),
        ([_route_row("anthropic/claude-sonnet-5")], False),
    ],
)
def test_responses_default_route(
    model_info_stub: ModelInfoStub, rows: list[dict[str, Any]], expected: bool
) -> None:
    assert bool(_route_provider(model_info_stub, rows).responses_api) is expected


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "model_args,config",
    [
        ({"responses_api": False}, GenerateConfig()),
        ({"emulate_tools": True}, GenerateConfig()),
        ({}, GenerateConfig(num_choices=2)),
        ({"model_info": False}, GenerateConfig()),
    ],
)
def test_responses_default_off(
    model_info_stub: ModelInfoStub, model_args: dict[str, Any], config: GenerateConfig
) -> None:
    provider = _route_provider(
        model_info_stub, [_route_row("openai/gpt-5")], config=config, **model_args
    )
    assert not provider.responses_api


@skip_if_no_openai_package
def test_responses_explicit_kept_for_other_routes(
    model_info_stub: ModelInfoStub,
) -> None:
    provider = _route_provider(
        model_info_stub, [_route_row("anthropic/claude-sonnet-5")], responses_api=True
    )
    assert provider.responses_api is True


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "row,model_args,streams",
    [
        # Responses to OpenAI streams, by default or explicitly
        (_route_row("openai/gpt-5"), {}, True),
        (_route_row("openai/gpt-5.5"), {"responses_api": True}, True),
        # Responses to other upstreams doesn't (LiteLLM #43010)
        (_route_row("anthropic/claude-sonnet-5"), {"responses_api": True}, False),
        (
            _route_row("openai/gpt-5", api_base=VLLM_BASE),
            {"responses_api": True},
            False,
        ),
        # Chat Completions streams for every upstream
        (_route_row("openai/gpt-4.1"), {}, True),
        (_route_row("openai/gpt-5"), {"responses_api": False}, True),
        # an explicit stream arg wins
        (_route_row("openai/gpt-5"), {"stream": False}, False),
    ],
)
def test_responses_streaming(
    model_info_stub: ModelInfoStub,
    row: dict[str, Any],
    model_args: dict[str, Any],
    streams: bool,
) -> None:
    provider = _route_provider(model_info_stub, [row], **model_args)
    assert provider.resolve_stream(GenerateConfig()) is streams


def _wire_tool_types(provider: LiteLLMProxyAPI, tools: list[Tool]) -> dict[str, str]:
    """Tool name to the type it is sent as on the Responses API."""
    config = GenerateConfig()
    resolved, _, _ = provider.resolve_tools(get_tools_info(tools), "auto", config)
    params = openai_responses_tools(resolved, provider.model_family(), config)
    return {str(param.get("name", param["type"])): param["type"] for param in params}


@skip_if_no_openai_package
# gpt-5.5 has native computer use and code interpreter; gpt-5 only the latter
@pytest.mark.parametrize("model", ["openai/gpt-5.5", "openai/gpt-5"])
def test_responses_default_hosts_only_web_search(
    model_info_stub: ModelInfoStub, model: str
) -> None:
    provider = _route_provider(model_info_stub, [_route_row(model)])
    assert provider.responses_api is True
    types = _wire_tool_types(provider, [web_search(), computer(), code_execution()])
    # OpenAI hosts web search; the other tools are function tools, as on
    # Chat Completions
    assert types == {
        "web_search": "web_search",
        "computer": "function",
        "code_execution": "function",
    }


@skip_if_no_openai_package
def test_chat_tools_unchanged(model_info_stub: ModelInfoStub) -> None:
    provider = _route_provider(model_info_stub, [_route_row("openai/gpt-4.1")])
    tools = get_tools_info([computer(), code_execution()])
    resolved, _, _ = provider.resolve_tools(tools, "auto", GenerateConfig())
    assert resolved == tools


@skip_if_no_openai_package
def test_responses_default_claims_web_search(model_info_stub: ModelInfoStub) -> None:
    provider = _route_provider(model_info_stub, [_route_row("openai/gpt-5.5")])
    _resolve_search_tools(provider, web_search())
    # a route the default doesn't cover still gets the error, and its hint
    azure = _route_provider(
        model_info_stub, [_route_row("azure/gpt-5", api_base="https://x.azure.com")]
    )
    with pytest.raises(PrerequisiteError, match="responses_api=true"):
        _resolve_search_tools(azure, web_search())


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
    assert len(provider._deployments or []) == 2


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
    # the text goes back exactly as returned, without the reasoning
    assert replayed_dict["content"] == "Answer."


@skip_if_no_openai_package
async def test_litellm_proxy_replays_reasoning_content_unchanged() -> None:
    # open models return reasoning_content only, which goes back as is
    message = _assistant({"content": "Answer.", "reasoning_content": "Because."})
    [replayed] = await _provider().messages_to_openai([message])
    replayed_dict = dict(replayed)
    assert replayed_dict["reasoning_content"] == "Because."
    assert "thinking_blocks" not in replayed_dict


@skip_if_no_openai_package
async def test_litellm_proxy_replays_text_parts_joined() -> None:
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(
                reasoning="Hmm.", signature="s", internal="thinking_blocks"
            ),
            ContentText(text="First. "),
            ContentText(text="Second."),
        ]
    )
    [replayed] = await _provider().messages_to_openai([message])
    assert dict(replayed)["content"] == "First. Second."


@skip_if_no_openai_package
async def test_litellm_proxy_replays_other_reasoning_as_base() -> None:
    # reasoning LiteLLM did not return goes into the text, as for other providers
    message = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="Hmm."), ContentText(text="Answer.")]
    )
    [replayed] = await _provider().messages_to_openai([message])
    assert "<think>" in str(dict(replayed)["content"])


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


def test_thinking_blocks_accumulator_many_summary_deltas() -> None:
    # summarized thinking streams one entry per small delta (1,181 in one
    # live run), then the signature entry repeating the whole text
    words = [f"word{i} " for i in range(1200)]
    summary = "".join(words)
    assert _accumulate(
        *({"type": "thinking", "thinking": word} for word in words),
        {"type": "thinking", "thinking": summary, "signature": "sig-1"},
    ) == [{"type": "thinking", "thinking": summary, "signature": "sig-1"}]


def test_thinking_blocks_accumulator_omitted_text() -> None:
    # omitted thinking: a signature entry with no text and no deltas before it
    assert _accumulate({"type": "thinking", "thinking": "", "signature": "sig-1"}) == [
        {"type": "thinking", "thinking": "", "signature": "sig-1"}
    ]


def test_thinking_blocks_accumulator_no_blocks() -> None:
    # at low effort Claude may not think at all
    assert _accumulate() == []


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
def test_same_alias_on_two_proxies_warns(
    model_info_stub: ModelInfoStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    _serve(model_info_stub, [_row("big", "anthropic/claude-opus-4-5")])
    _stub_model(model_info_stub, "big", memoize=False)
    # the same server under another URL stands in for a second proxy
    other_url = model_info_stub.url.replace("127.0.0.1", "localhost")
    _serve(model_info_stub, [_row("big", "anthropic/claude-haiku-4-5")])
    _stub_model(model_info_stub, "big", base_url=other_url, memoize=False)
    assert len(warnings) == 1
    assert "served by more than one proxy" in warnings[0]


@skip_if_no_openai_package
@pytest.mark.parametrize("other_host", ["127.0.0.1", "localhost"])
def test_same_alias_same_info_does_not_warn(
    model_info_stub: ModelInfoStub, monkeypatch: pytest.MonkeyPatch, other_host: str
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    _serve(model_info_stub, [_row("big", "anthropic/claude-opus-4-5")])
    _stub_model(model_info_stub, "big", memoize=False)
    # the same proxy again, or another URL listing the same deployment
    other_url = model_info_stub.url.replace("127.0.0.1", other_host)
    _stub_model(model_info_stub, "big", base_url=other_url, memoize=False)
    assert warnings == []


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


# Reasoning effort ---------------------------------------------------------------

# rejections as LiteLLM proxy 1.104 (and OpenAI, for values it forwards) word them
PARAMETER_REJECTED = (
    "litellm.UnsupportedParamsError: xai does not support parameters: "
    "['reasoning_effort'], for model=grok-4. To drop these, set "
    "`litellm.drop_params=True` or for proxy:\n\n`litellm_settings:\n drop_params: "
    "true`\n."
)


@pytest.mark.parametrize(
    "message,sent,kind",
    [
        (PARAMETER_REJECTED, "high", "parameter"),
        (
            "litellm.UnsupportedParamsError: gpt-4.1 doesn't support "
            "`reasoning.effort` (its model cost map entry lacks "
            "`supports_reasoning`). To drop unsupported params set "
            "`litellm.drop_params = True`",
            "none",
            "parameter",
        ),
        (
            "litellm.UnsupportedParamsError: reasoning_effort=xhigh is not "
            "supported for this model.",
            "xhigh",
            "value",
        ),
        (
            "litellm.UnsupportedParamsError: Invalid `reasoning_effort`: 'max'. Must "
            "be one of: 'minimal', 'low', 'medium', 'high', 'none', 'disable'.",
            "max",
            "value",
        ),
        (
            "litellm.BadRequestError: effort='xhigh' is not supported by this "
            "model. Got model: claude-opus-4-6",
            "xhigh",
            "value",
        ),
        (
            "litellm.BadRequestError: OpenAIException - Unsupported value: "
            "'reasoning_effort' does not support 'max' with this model. Supported "
            "values are: 'minimal', 'low', 'medium', and 'high'.",
            "max",
            "value",
        ),
        (
            'litellm.BadRequestError: OpenAIException - {\n  "error": {\n    '
            '"message": "Unsupported value: \'none\' is not supported with the '
            "'gpt-5' model. Supported values are: 'minimal', 'low', 'medium', and "
            '\'high\'.",\n    "type": "invalid_request_error",\n    "param": '
            '"reasoning.effort",\n    "code": "unsupported_value"\n  }\n}',
            "none",
            "value",
        ),
        # an unsupported value for another parameter
        (
            'litellm.BadRequestError: OpenAIException - {"error": {"message": '
            "\"Unsupported value: 'none' is not supported with the 'gpt-5' "
            'model.", "param": "temperature"}}',
            "none",
            None,
        ),
        # a value rejection names a different value than the one sent
        (
            "litellm.UnsupportedParamsError: reasoning_effort=xhigh is not "
            "supported for this model.",
            "high",
            None,
        ),
        (
            "litellm.BadRequestError: OpenAIException - Invalid 'tools[0].name'",
            "high",
            None,
        ),
    ],
)
def test_rejected_effort(message: str, sent: str, kind: str | None) -> None:
    rejection = rejected_effort(message, sent)
    assert (rejection.kind if rejection else None) == kind


@pytest.mark.parametrize(
    "requested,rejected,expected",
    [
        ("xhigh", {"xhigh"}, "high"),
        ("max", {"max", "xhigh"}, "high"),
        ("minimal", {"minimal"}, "low"),
        ("minimal", {"minimal", "low"}, "medium"),
        ("high", set(), "high"),
        ("none", {"none"}, None),
        ("turbo", {"turbo"}, None),
        ("high", {"minimal", "low", "medium", "high", "xhigh", "max"}, None),
    ],
)
def test_next_effort(requested: str, rejected: set[str], expected: str | None) -> None:
    assert next_effort(requested, rejected) == expected


Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

EFFORTS: list[Effort] = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]

STRICT_OPENAI_EFFORTS = ("low", "medium", "high")
"""Efforts the strict fake OpenAI upstream accepts (like o3)."""

SUMMARIZED = {"type": "adaptive", "display": "summarized"}
"""The `thinking` the provider sends to Claude 4.6+ with an effort."""


def _strict_openai_route(request: StubRequest) -> dict[str, Any] | SSE | Reply | None:
    """The fake upstreams, plus an OpenAI model that rejects other efforts."""
    body = request.body or {}
    if body.get("model") == "strict-openai":
        param = "reasoning_effort" if "messages" in body else "reasoning.effort"
        effort = (
            body.get("reasoning_effort")
            if "messages" in body
            else (body.get("reasoning") or {}).get("effort")
        )
        if effort is not None and effort not in STRICT_OPENAI_EFFORTS:
            # OpenAI's wording differs between chat completions and Responses
            message = (
                f"Unsupported value: '{param}' does not support '{effort}' with "
                "this model."
                if "messages" in body
                else f"Unsupported value: '{effort}' is not supported with the "
                "'strict-openai' model."
            )
            return Reply(
                400,
                {
                    "error": {
                        "message": f"{message} Supported values are: 'low', "
                        "'medium', and 'high'.",
                        "type": "invalid_request_error",
                        "param": param,
                        "code": "unsupported_value",
                    }
                },
            )
    return route(request)


EFFORT_DEPLOYMENTS = {
    "claude-3-5-haiku": "anthropic/claude-3-5-haiku-20241022",
    "claude-opus-4-6": "anthropic/claude-opus-4-6",
    "claude-opus-5-5": "anthropic/claude-opus-5-5",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
    "gemini-3-pro": "gemini/gemini-3-pro-preview",
    "gpt-5": "openai/gpt-5",
    "gpt-5.5": "openai/gpt-5.5",
    "gpt-4.1": "openai/gpt-4.1",
    "grok-4": "xai/grok-4",
    "deepseek-reasoner": "deepseek/deepseek-reasoner",
    "strict-openai": "openai/strict-openai",
    # the strict fake as a codename identified by base_model
    "strict-codename": "openai/strict-openai",
}


def _effort_params(model: str, url: str) -> dict[str, Any]:
    if model.startswith("anthropic/"):
        return {"model": model, "api_base": url, "api_key": "fake"}
    if model.startswith("gemini/"):
        return {"model": model, "api_base": f"{url}/v1beta", "api_key": "fake"}
    return {"model": model, "api_base": f"{url}/v1", "api_key": "fake"}


def _effort_model_info(alias: str) -> dict[str, Any]:
    # LiteLLM's map does not know the strict fake; without supports_reasoning,
    # LiteLLM refuses reasoning.effort on the Responses path
    if alias == "strict-openai":
        return {"supports_reasoning": True}
    if alias == "strict-codename":
        return {"supports_reasoning": True, "base_model": "openai/gpt-5.5"}
    return {}


@pytest.fixture(scope="module")
def effort_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiteLLMProxy]:
    with fake_upstream(_strict_openai_route) as upstream:
        config = {
            "model_list": [
                {
                    "model_name": alias,
                    "litellm_params": _effort_params(model, upstream.docker_url),
                    "model_info": _effort_model_info(alias),
                }
                for alias, model in EFFORT_DEPLOYMENTS.items()
            ],
            "router_settings": {"num_retries": 0},
        }
        with run_litellm_proxy(
            tmp_path_factory.mktemp("litellm-effort"), config, capture=True
        ) as proxy:
            yield proxy


def _sent_effort(request: dict[str, Any]) -> Any:
    """The effort-related part of an upstream request."""
    if "generationConfig" in request or "contents" in request:
        return (request.get("generationConfig") or {}).get("thinkingConfig")
    if "output_config" in request or "thinking" in request:
        return (request.get("output_config") or {}).get("effort")
    if "reasoning" in request:
        return (request.get("reasoning") or {}).get("effort")
    return request.get("reasoning_effort")


async def _generate_effort(
    proxy: LiteLLMProxy, alias: str, responses_api: bool | None, effort: Effort
) -> tuple[ModelOutput | Exception, Any]:
    """Generate with `effort`; `responses_api=None` uses the provider default."""
    model_args: dict[str, Any] = (
        # the default needs the route from model info
        {"require_model_info": False}
        if responses_api is None
        else {"responses_api": responses_api, "model_info": False}
    )
    api = _proxy_api(
        get_model(
            f"litellm-proxy/{alias}",
            base_url=proxy.base_url,
            api_key=proxy.api_key,
            max_retries=0,
            memoize=False,
            **model_args,
        )
    )
    call_id = str(uuid.uuid4())
    result = await api.generate(
        [ChatMessageUser(content="Hello")],
        [],
        "none",
        GenerateConfig(
            reasoning_effort=effort, extra_headers={CALL_ID_HEADER: call_id}
        ),
    )
    output = result[0] if isinstance(result, tuple) else result
    sent = None
    if isinstance(output, ModelOutput):
        assert proxy.capture_dir is not None
        sent = _sent_effort(upstream_exchange(proxy.capture_dir, call_id).request)
    return output, sent


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("responses_api", [False, True], ids=["chat", "responses"])
@pytest.mark.parametrize("alias", list(EFFORT_DEPLOYMENTS))
async def test_litellm_proxy_reasoning_effort_never_fails(
    effort_proxy: LiteLLMProxy, alias: str, responses_api: bool
) -> None:
    for effort in EFFORTS:
        output, _ = await _generate_effort(effort_proxy, alias, responses_api, effort)
        assert isinstance(output, ModelOutput), f"{effort}: {output}"


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize(
    "alias,responses_api,effort,sent",
    [
        ("claude-opus-4-6", False, "xhigh", "high"),
        ("claude-opus-4-6", True, "xhigh", "high"),
        ("claude-opus-5-5", True, "max", "max"),
        (
            "gemini-3-pro",
            False,
            "max",
            {"thinkingLevel": "high", "includeThoughts": True},
        ),
        ("gpt-5", False, "xhigh", "high"),
        ("gpt-5.5", False, "minimal", "low"),
        ("gpt-4.1", False, "high", None),
        ("grok-4", False, "high", None),
        ("strict-openai", False, "max", "high"),
        ("strict-openai", True, "max", "high"),
        ("strict-openai", False, "none", None),
    ],
)
async def test_litellm_proxy_reasoning_effort_lowered(
    effort_proxy: LiteLLMProxy,
    alias: str,
    responses_api: bool,
    effort: Effort,
    sent: Any,
) -> None:
    output, upstream = await _generate_effort(
        effort_proxy, alias, responses_api, effort
    )
    assert isinstance(output, ModelOutput), output
    assert upstream == sent


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize(
    "alias,effort,sent",
    [
        ("strict-codename", "max", "high"),
        ("strict-codename", "xhigh", "high"),
        ("strict-codename", "none", None),
        # OpenAI applies its own rules to gpt-5 on Responses
        ("gpt-5", "high", "high"),
    ],
)
async def test_litellm_proxy_reasoning_effort_lowered_responses_default(
    effort_proxy: LiteLLMProxy,
    monkeypatch: pytest.MonkeyPatch,
    alias: str,
    effort: Effort,
    sent: Any,
) -> None:
    # the fake upstream stands in for OpenAI's API
    monkeypatch.setattr(
        litellm_proxy_module, "is_openai_api_base", lambda api_base: True
    )
    default = _proxy_api(
        get_model(
            f"litellm-proxy/{alias}",
            base_url=effort_proxy.base_url,
            api_key=effort_proxy.api_key,
            require_model_info=False,
            memoize=False,
        )
    )
    assert default.responses_api is True
    output, upstream = await _generate_effort(effort_proxy, alias, None, effort)
    assert isinstance(output, ModelOutput), output
    assert upstream == sent


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_reasoning_effort_remembered(
    effort_proxy: LiteLLMProxy, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    attempts = 0
    generate = OpenAICompatibleAPI.generate

    async def counting_generate(self: Any, *args: Any) -> Any:
        nonlocal attempts
        attempts += 1
        return await generate(self, *args)

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", counting_generate)
    api = _proxy_api(
        get_model(
            "litellm-proxy/gpt-5.5",
            base_url=effort_proxy.base_url,
            api_key=effort_proxy.api_key,
            model_info=False,
            max_retries=0,
            memoize=False,
        )
    )
    for expected_attempts in (2, 3):
        result = await api.generate(
            [ChatMessageUser(content="Hello")],
            [],
            "none",
            GenerateConfig(reasoning_effort="minimal"),
        )
        output = result[0] if isinstance(result, tuple) else result
        assert isinstance(output, ModelOutput)
        assert attempts == expected_attempts
    assert warnings == [
        "LiteLLM proxy model 'gpt-5.5' does not accept reasoning_effort='minimal'; "
        "using 'low'."
    ]


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize(
    "alias,effort,display,upstream",
    [
        (
            "claude-opus-5-5",
            "xhigh",
            "summarized",
            {"thinking": SUMMARIZED, "output_config": {"effort": "xhigh"}},
        ),
        (
            "claude-opus-5-5",
            "high",
            "omitted",
            {
                "thinking": {"type": "adaptive", "display": "omitted"},
                "output_config": {"effort": "high"},
            },
        ),
        # LiteLLM rejects xhigh for 4.6; the lowered effort keeps the thinking
        (
            "claude-opus-4-6",
            "xhigh",
            "summarized",
            {"thinking": SUMMARIZED, "output_config": {"effort": "high"}},
        ),
        # no effort: LiteLLM's default thinking, not ours
        ("claude-opus-5-5", "none", "summarized", {}),
    ],
)
async def test_litellm_proxy_claude_thinking_upstream(
    effort_proxy: LiteLLMProxy,
    alias: str,
    effort: Effort,
    display: str,
    upstream: dict[str, Any],
) -> None:
    api = _proxy_api(
        get_model(
            f"litellm-proxy/{alias}",
            base_url=effort_proxy.base_url,
            api_key=effort_proxy.api_key,
            model_info=False,
            max_retries=0,
            memoize=False,
            thinking_display=display,
        )
    )
    call_id = str(uuid.uuid4())
    result = await api.generate(
        [ChatMessageUser(content="Hello")],
        [],
        "none",
        GenerateConfig(
            reasoning_effort=effort, extra_headers={CALL_ID_HEADER: call_id}
        ),
    )
    output = result[0] if isinstance(result, tuple) else result
    assert isinstance(output, ModelOutput), output
    assert effort_proxy.capture_dir is not None
    request = upstream_exchange(effort_proxy.capture_dir, call_id).request
    sent = {
        key: request[key] for key in ("thinking", "output_config") if key in request
    }
    assert sent == upstream


def _adaptive_only_route(request: StubRequest) -> dict[str, Any] | SSE | Reply | None:
    """The fake upstreams, with Claude rejecting extended thinking as 4.7+ do."""
    body = request.body or {}
    if (body.get("thinking") or {}).get("type") == "enabled":
        return Reply(
            400, _anthropic_error("invalid_request_error", ADAPTIVE_THINKING_REJECTION)
        )
    return route(request)


CODENAME_BASE_MODEL = {"base_model": "anthropic/claude-opus-5-5"}


@pytest.fixture(scope="module")
def codename_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiteLLMProxy]:
    with fake_upstream(_adaptive_only_route) as upstream:

        def params(model: str) -> dict[str, Any]:
            return {"model": model, "api_base": upstream.docker_url, "api_key": "fake"}

        # distinct upstream names: LiteLLM applies a deployment's model_info
        # flags to every deployment of the same upstream model
        config = {
            "model_list": [
                {
                    "model_name": "metis",
                    "litellm_params": params("anthropic/metis-v2"),
                    "model_info": CODENAME_BASE_MODEL,
                },
                {
                    "model_name": "metis-adaptive",
                    "litellm_params": params("anthropic/metis-v3"),
                    "model_info": CODENAME_BASE_MODEL
                    | {"supports_reasoning": True, "supports_adaptive_thinking": True},
                },
                # model info from limits alone: LiteLLM refuses the effort
                {
                    "model_name": "metis-limits",
                    "litellm_params": params("anthropic/metis-v4"),
                    "model_info": {"max_input_tokens": 200000},
                },
                {
                    "model_name": "bedrock-metis-limits",
                    "litellm_params": {
                        "model": "bedrock/converse/us.anthropic.metis-v5:0",
                        "api_base": upstream.docker_url,
                        "aws_access_key_id": "fake",
                        "aws_secret_access_key": "fake",
                        "aws_region_name": "us-east-1",
                    },
                    "model_info": {"max_input_tokens": 200000},
                },
            ],
            "router_settings": {"num_retries": 0},
        }
        with run_litellm_proxy(
            tmp_path_factory.mktemp("litellm-codename"), config, capture=True
        ) as proxy:
            yield proxy


async def _generate_codename(
    proxy: LiteLLMProxy, alias: str, stream: bool
) -> tuple[ModelOutput | Exception, str]:
    api = _proxy_api(
        get_model(
            f"litellm-proxy/{alias}",
            base_url=proxy.base_url,
            api_key=proxy.api_key,
            max_retries=0,
            memoize=False,
            stream=stream,
        )
    )
    call_id = str(uuid.uuid4())
    result = await api.generate(
        [ChatMessageUser(content="Hello")],
        [],
        "none",
        GenerateConfig(
            reasoning_effort="high", extra_headers={CALL_ID_HEADER: call_id}
        ),
    )
    return (result[0] if isinstance(result, tuple) else result), call_id


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("stream", [False, True])
async def test_litellm_proxy_codename_extended_thinking_rejected(
    codename_proxy: LiteLLMProxy, stream: bool
) -> None:
    # LiteLLM sends extended thinking to a codename, even with base_model
    output, _ = await _generate_codename(codename_proxy, "metis", stream)
    assert isinstance(output, PrerequisiteError), output
    assert "supports_adaptive_thinking: true" in str(output.message)
    assert "add to the 'metis' deployment" in str(output.message)


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize(
    "alias,base_model", [("metis-limits", False), ("bedrock-metis-limits", True)]
)
async def test_litellm_proxy_codename_effort_refused_names_fix(
    codename_proxy: LiteLLMProxy,
    monkeypatch: pytest.MonkeyPatch,
    alias: str,
    base_model: bool,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    # the fake Bedrock upstream speaks Converse JSON only, not the eventstream
    output, _ = await _generate_codename(codename_proxy, alias, stream=False)
    assert isinstance(output, ModelOutput), output
    [warning] = warnings
    assert "does not accept reasoning_effort='high'; sending no reasoning_effort" in (
        warning
    )
    assert "supports_adaptive_thinking: true" in warning
    assert f"add to the '{alias}' deployment" in warning
    assert ("base_model: anthropic/" in warning) == base_model


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("stream", [False, True])
async def test_litellm_proxy_codename_adaptive_thinking_flag(
    codename_proxy: LiteLLMProxy, stream: bool
) -> None:
    # the fix the error names
    output, call_id = await _generate_codename(codename_proxy, "metis-adaptive", stream)
    assert isinstance(output, ModelOutput), output
    assert codename_proxy.capture_dir is not None
    request = upstream_exchange(codename_proxy.capture_dir, call_id).request
    assert request["thinking"] == SUMMARIZED
    assert request["output_config"] == {"effort": "high"}


# Claude request shaping, prompt caching and defaults ----------------------


@pytest.mark.parametrize(
    "names,vendor",
    [
        (["anthropic/claude-metis-v1"], "anthropic"),
        (["bedrock/converse/us.anthropic.claude-metis-v1:0"], "anthropic"),
        (["vertex_ai/claude-opus-5-5@default"], "anthropic"),
        (["anthropic/metis"], "anthropic"),
        ([None, None, "claude-metis"], "anthropic"),
        (["hosted_vllm/llama-4", "claude-metis"], "anthropic"),
        (["xai/mimas"], "grok"),
        (["openrouter/x-ai/grok-5"], "grok"),
        (["gemini/gemini-4-pro"], "google"),
        (["openai/gpt-7-preview"], "openai"),
        (["azure/o5-mini"], "openai"),
        (["bedrock/converse/us.openai.gpt-6-astra"], "openai"),
        (["openai/gpt-oss-120b"], None),
        (["hosted_vllm/llama-4"], None),
        (["openai/mimas"], None),
        ([None], None),
    ],
)
def test_upstream_vendor(names: list[str | None], vendor: str | None) -> None:
    assert upstream_vendor(names) == vendor


def _frontier_model(vendor: str) -> str:
    return FRONTIER_MODELS[vendor].split("/", 1)[1]


@pytest.mark.parametrize(
    "vendor,litellm_provider",
    [
        ("anthropic", "anthropic"),
        ("openai", "openai"),
        ("google", "gemini"),
        ("grok", "xai"),
    ],
)
def test_frontier_base_model(vendor: Vendor, litellm_provider: str) -> None:
    assert frontier_base_model(vendor) == (
        f"{litellm_provider}/{_frontier_model(vendor)}"
    )


def _cached(block: dict[str, Any]) -> bool:
    return block.get("cache_control") == {"type": "ephemeral"}


def test_with_cache_breakpoints() -> None:
    messages: list[Any] = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": [{"type": "text", "text": "Look up ABC."}]},
        {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ABC is 1."},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Done."}],
            "thinking_blocks": [THINKING],
        },
    ]
    result: list[Any] = with_cache_breakpoints(messages)
    assert _cached(result[0]["content"][-1])
    assert not _cached(result[1]["content"][-1])
    # an assistant turn with only tool calls has no block to mark
    assert result[2]["content"] is None
    assert result[3]["content"] == [
        {"type": "text", "text": "ABC is 1.", "cache_control": {"type": "ephemeral"}}
    ]
    assert _cached(result[4]["content"][-1])
    assert result[4]["thinking_blocks"] == [THINKING]
    # the input is not modified
    assert messages[0]["content"] == "Be helpful."
    assert "cache_control" not in messages[4]["content"][-1]


def test_with_cache_breakpoints_single_message() -> None:
    result: list[Any] = with_cache_breakpoints([{"role": "user", "content": "Hi"}])
    assert _cached(result[0]["content"][-1])
    assert with_cache_breakpoints([]) == []


def test_with_tool_cache_breakpoint() -> None:
    tools: list[Any] = [
        {"type": "function", "function": {"name": name, "parameters": {}}}
        for name in ("a", "b")
    ]
    result: list[Any] = with_tool_cache_breakpoint(tools)
    assert "cache_control" not in result[0]["function"]
    assert _cached(result[1]["function"])
    assert "cache_control" not in tools[1]["function"]
    assert with_tool_cache_breakpoint([]) == []


@pytest.mark.parametrize(
    "details,ttl",
    [
        ({"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 20}, "1h"),
        ({"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 0}, "5m"),
        ({"ephemeral_5m_input_tokens": 5, "ephemeral_1h_input_tokens": 20}, "1h"),
        ({"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}, None),
        (None, None),
    ],
)
def test_cache_write_ttl(details: dict[str, int] | None, ttl: str | None) -> None:
    prompt_tokens_details: dict[str, Any] = {"cache_write_tokens": 20}
    if details is not None:
        prompt_tokens_details["cache_creation_token_details"] = details
    assert cache_write_ttl({"prompt_tokens_details": prompt_tokens_details}) == ttl


def _alias_provider(alias: str, **model_args: Any) -> LiteLLMProxyAPI:
    api = get_model(
        f"litellm-proxy/{alias}",
        base_url="http://localhost:4000/v1",
        api_key="key",
        model_info=False,
        memoize=False,
        **model_args,
    ).api
    assert isinstance(api, LiteLLMProxyAPI)
    return api


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "config,max_tokens",
    [
        (GenerateConfig(), 32000),
        (GenerateConfig(reasoning_effort="none"), 32000),
        (GenerateConfig(reasoning_effort="minimal"), 36096),
        (GenerateConfig(reasoning_effort="low"), 36096),
        (GenerateConfig(reasoning_effort="high"), 48000),
        (GenerateConfig(reasoning_effort="xhigh"), 64000),
        (GenerateConfig(reasoning_effort="max"), 64000),
        # not sent through the proxy, so no room is made for it
        (GenerateConfig(reasoning_tokens=8000), 32000),
    ],
)
def test_claude_max_tokens(config: GenerateConfig, max_tokens: int) -> None:
    assert _alias_provider("claude-metis").max_tokens_for_config(config) == max_tokens


@skip_if_no_openai_package
async def test_reasoning_tokens_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])

    async def generate(self: Any, *args: Any) -> ModelOutput:
        return ModelOutput.from_content("claude", "Hi")

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", generate)
    api = _alias_provider("claude-metis")
    for _ in range(2):
        await api.generate(
            [ChatMessageUser(content="Hi")],
            [],
            "none",
            GenerateConfig(reasoning_tokens=8000),
        )
    assert len(warnings) == 1
    assert "so it is ignored" in warnings[0]


@skip_if_no_openai_package
def test_claude_max_tokens_capped_by_output_limit() -> None:
    set_model_info("litellm-proxy/claude-small", ModelInfo(output_tokens=8192))
    api = _alias_provider("claude-small")
    assert api.max_tokens_for_config(GenerateConfig(reasoning_effort="max")) == 8192


@skip_if_no_openai_package
def test_max_tokens_default_only_for_claude() -> None:
    assert _alias_provider("gpt-5").max_tokens_for_config(GenerateConfig()) is None


@pytest.mark.parametrize(
    "family,adaptive",
    [
        ("claude-opus-4-6", True),
        ("claude-opus-4-7", True),
        ("claude-sonnet-5", True),
        ("claude-opus-5-5", True),
        ("claude-fable-5-1", True),
        ("claude-metis", True),
        ("metis", True),
        ("claude-sonnet-4-5", False),
        ("claude-sonnet-4-5-20250929", False),
        ("claude-haiku-4-5", False),
        ("claude-opus-4-1", False),
        ("claude-opus-4-0", False),
        ("claude-sonnet-4", False),
        ("claude-sonnet-4-20250514", False),
        ("claude-sonnet-4@20250514", False),
        ("claude-3-7-sonnet-20250219", False),
        ("claude-3-5-haiku-20241022", False),
        ("claude-3-opus-20240229", False),
        ("claude-2.1", False),
        ("claude-instant-1.2", False),
        # dotted versions (e.g. OpenRouter) and version-first names
        ("claude-3.5-sonnet", False),
        ("claude-3.7-sonnet", False),
        ("claude-sonnet-4.5", False),
        ("claude-opus-4.1", False),
        ("claude-4-sonnet", False),
        ("claude-4-opus", False),
        ("claude-4.5-sonnet", False),
        ("claude-v2", False),
        ("claude-sonnet-4-latest", False),
        ("claude-sonnet-4.6", True),
        ("claude-opus-4.7", True),
        ("claude-opus-5.5", True),
        ("claude-opus-4-6-20260101", True),
    ],
)
def test_claude_thinks_adaptively(family: str, adaptive: bool) -> None:
    assert claude_thinks_adaptively(family) == adaptive


class _SentConfigs(NamedTuple):
    configs: list[GenerateConfig]
    """The config of each request the provider made."""


@pytest.fixture
def sent_configs(monkeypatch: pytest.MonkeyPatch) -> _SentConfigs:
    """Record each request's config instead of sending it."""
    sent = _SentConfigs(configs=[])

    async def generate(
        self: Any, input: Any, tools: Any, tool_choice: Any, config: GenerateConfig
    ) -> ModelOutput:
        sent.configs.append(config)
        return ModelOutput.from_content("claude", "Hi")

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", generate)
    return sent


async def _sent_thinking(
    api: LiteLLMProxyAPI, sent: _SentConfigs, config: GenerateConfig
) -> Any:
    await api.generate([ChatMessageUser(content="Hi")], [], "none", config)
    return (sent.configs[-1].extra_body or {}).get("thinking")


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "alias,effort,thinking",
    [
        ("claude-opus-5-5", "high", SUMMARIZED),
        ("claude-opus-4-6", "low", SUMMARIZED),
        ("claude-metis", "max", SUMMARIZED),
        # LiteLLM would replace the effort's thinking budget with its own
        ("claude-sonnet-4-5", "high", None),
        ("claude-3-7-sonnet", "high", None),
        # adaptive thinking without an effort would change the model's behavior
        ("claude-opus-5-5", None, None),
        ("claude-opus-5-5", "none", None),
        ("gpt-5.5", "high", None),
        ("gemini-3-pro", "high", None),
    ],
)
async def test_claude_thinking_display(
    sent_configs: _SentConfigs, alias: str, effort: Any, thinking: Any
) -> None:
    config = GenerateConfig(reasoning_effort=effort)
    assert await _sent_thinking(_alias_provider(alias), sent_configs, config) == (
        thinking
    )


@skip_if_no_openai_package
async def test_claude_thinking_display_omitted(sent_configs: _SentConfigs) -> None:
    api = _alias_provider("claude-opus-5-5", thinking_display="omitted")
    config = GenerateConfig(reasoning_effort="high")
    assert await _sent_thinking(api, sent_configs, config) == {
        "type": "adaptive",
        "display": "omitted",
    }


@skip_if_no_openai_package
def test_claude_thinking_display_must_be_valid() -> None:
    with pytest.raises(ValueError, match="thinking_display"):
        _alias_provider("claude-opus-5-5", thinking_display="full")


@skip_if_no_openai_package
async def test_claude_thinking_not_on_responses(sent_configs: _SentConfigs) -> None:
    api = _alias_provider("claude-opus-5-5", responses_api=True)
    config = GenerateConfig(reasoning_effort="high")
    assert await _sent_thinking(api, sent_configs, config) is None


@skip_if_no_openai_package
async def test_claude_thinking_keeps_extra_body(sent_configs: _SentConfigs) -> None:
    api = _alias_provider("claude-opus-5-5")
    await _sent_thinking(
        api,
        sent_configs,
        GenerateConfig(reasoning_effort="high", extra_body={"top_k": 5}),
    )
    assert sent_configs.configs[-1].extra_body == {"top_k": 5, "thinking": SUMMARIZED}
    user_thinking = {"type": "adaptive", "display": "omitted"}
    config = GenerateConfig(
        reasoning_effort="high", extra_body={"thinking": user_thinking}
    )
    assert await _sent_thinking(api, sent_configs, config) == user_thinking


@skip_if_no_openai_package
def test_claude_thinking_in_request_body() -> None:
    api = _alias_provider("claude-opus-5-5")
    config = GenerateConfig(
        reasoning_effort="high",
        extra_body={"thinking": SUMMARIZED},
    )
    params = api.completion_params(config, tools=False)
    assert params["reasoning_effort"] == "high"
    assert params["extra_body"] == {"thinking": SUMMARIZED}


@pytest.mark.parametrize(
    "message,rejected",
    [
        (
            "litellm.UnsupportedParamsError: anthropic does not support "
            "parameters: ['thinking'], for model=metis.",
            True,
        ),
        (
            "litellm.BadRequestError: AnthropicException - "
            '{"type":"error","error":{"type":"invalid_request_error","message":'
            "\"thinking.adaptive.display: Input should be 'summarized', "
            "'omitted'\"}}",
            True,
        ),
        (
            "litellm.BadRequestError: AnthropicException - "
            '{"type":"error","error":{"type":"invalid_request_error","message":'
            '"adaptive thinking is not supported on this model"}}',
            True,
        ),
        # both words, but not about the thinking parameter
        (
            "messages.3.content.0: the display of a thinking block is invalid",
            False,
        ),
        (
            "litellm.UnsupportedParamsError: anthropic does not support "
            "parameters: ['reasoning_effort'], for model=metis.",
            False,
        ),
        ("prompt is too long: 250000 tokens > 200000 maximum", False),
    ],
)
def test_rejected_thinking(message: str, rejected: bool) -> None:
    assert rejected_thinking(message) == rejected


@skip_if_no_openai_package
def test_thinking_rejection_reaches_generate_unchanged() -> None:
    # generate() retries on the BadRequestError that handle_bad_request returns
    for message in (
        "thinking.adaptive.display: Input should be 'summarized', 'omitted'",
        "adaptive thinking is not supported on this model",
        "litellm.UnsupportedParamsError: anthropic does not support "
        "parameters: ['thinking'], for model=metis.",
    ):
        error = _bad_request(message)
        assert _alias_provider("claude-opus-5-5").handle_bad_request(error) is error


@skip_if_no_openai_package
async def test_claude_thinking_rejected_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    configs: list[GenerateConfig] = []

    async def generate(
        self: Any, input: Any, tools: Any, tool_choice: Any, config: GenerateConfig
    ) -> ModelOutput | BadRequestError:
        configs.append(config)
        if "thinking" in (config.extra_body or {}):
            return _bad_request(
                "litellm.BadRequestError: AnthropicException - thinking.adaptive."
                "display: Extra inputs are not permitted"
            )
        return ModelOutput.from_content("claude", "Hi")

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", generate)
    api = _alias_provider("claude-opus-5-5")
    for expected_attempts in (2, 3):
        result = await api.generate(
            [ChatMessageUser(content="Hi")],
            [],
            "none",
            GenerateConfig(reasoning_effort="high"),
        )
        assert isinstance(result, ModelOutput)
        assert len(configs) == expected_attempts
    # the effort is still sent
    assert configs[-1].reasoning_effort == "high"
    assert warnings == [
        "LiteLLM proxy model 'claude-opus-5-5' does not accept "
        "thinking={'type': 'adaptive', 'display': 'summarized'}; sending no "
        "thinking parameter, so its thinking may not be summarized."
    ]


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "alias,hint",
    [("claude-metis", True), ("claude-sonnet-4-5", False), ("gpt-5.5", False)],
)
async def test_effort_refused_hint_only_for_adaptive_claude(
    monkeypatch: pytest.MonkeyPatch, alias: str, hint: bool
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(litellm_proxy_module.logger, "warning", warnings.append)
    monkeypatch.setattr(inspect_logger, "_warned", [])

    async def generate(
        self: Any, input: Any, tools: Any, tool_choice: Any, config: GenerateConfig
    ) -> ModelOutput | BadRequestError:
        if config.reasoning_effort is not None:
            return _bad_request(
                "litellm.UnsupportedParamsError: anthropic does not support "
                f"parameters: ['reasoning_effort'], for model={alias}."
            )
        return ModelOutput.from_content(alias, "Hi")

    monkeypatch.setattr(OpenAICompatibleAPI, "generate", generate)
    await _alias_provider(alias).generate(
        [ChatMessageUser(content="Hi")],
        [],
        "none",
        GenerateConfig(reasoning_effort="high"),
    )
    [warning] = warnings
    assert ("supports_adaptive_thinking: true" in warning) == hint


@skip_if_no_openai_package
def test_claude_keeps_full_tool_schemas() -> None:
    assert _alias_provider("claude-metis").schema_exclude_fields is None
    assert _alias_provider("gpt-5").schema_exclude_fields is not None


@skip_if_no_openai_package
def test_streams_by_default() -> None:
    config = GenerateConfig()
    assert _alias_provider("gpt-5").resolve_stream(config)
    assert not _alias_provider("gpt-5", stream=False).resolve_stream(config)
    assert not _alias_provider("gpt-5", responses_api=True).resolve_stream(config)
    assert not _alias_provider("gpt-5").resolve_stream(
        GenerateConfig(prompt_logprobs=1)
    )


@skip_if_no_openai_package
def test_provider_bad_request_prefill() -> None:
    message = (
        "litellm.BadRequestError: AnthropicException - "
        '{"type":"error","error":{"type":"invalid_request_error","message":'
        '"This model does not support assistant message prefill. The '
        'conversation must end with a user message."}}\nmodel=claude-metis'
    )
    error = _provider().handle_bad_request(_bad_request(message))
    assert isinstance(error, PrefillNotSupportedError)
    assert "ends with an assistant message" in str(error)
    assert "This model does not support assistant message prefill." in str(error)


ADAPTIVE_THINKING_REJECTION = (
    '"thinking.type.enabled" is not supported for this model. Use '
    '"thinking.type.adaptive" and "output_config.effort" to control thinking '
    "behavior."
)
"""Anthropic's message for extended thinking sent to Claude 4.7+."""


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "message",
    [
        # as LiteLLM wraps it: the upstream body, JSON-escaped
        "litellm.BadRequestError: AnthropicException - "
        + json.dumps(
            _anthropic_error("invalid_request_error", ADAPTIVE_THINKING_REJECTION)
        )
        + "\nmodel=metis",
        ADAPTIVE_THINKING_REJECTION,
    ],
)
def test_provider_bad_request_adaptive_thinking_required(message: str) -> None:
    error = _alias_provider("metis").handle_bad_request(_bad_request(message))
    assert isinstance(error, PrerequisiteError)
    text = str(error.message)
    assert "LiteLLM proxy model 'metis' takes only adaptive thinking" in text
    assert "add to the 'metis' deployment" in text
    assert (
        "        supports_reasoning: true\n        supports_adaptive_thinking: true\n"
        in text
    )
    assert "base_model does not change this" in text
    assert f"Proxy error: {ADAPTIVE_THINKING_REJECTION}" in text


def _search_provider(alias: str, **model_args: Any) -> LiteLLMProxyAPI:
    api = get_model(
        f"litellm-proxy/{alias}",
        base_url="http://localhost:4000/v1",
        api_key="key",
        model_info=False,
        **model_args,
    ).api
    assert isinstance(api, LiteLLMProxyAPI)
    return api


def _resolve_search_tools(
    api: LiteLLMProxyAPI, search: Tool, config: GenerateConfig = GenerateConfig()
) -> None:
    api.resolve_tools(get_tools_info([search]), "auto", config)


@skip_if_no_openai_package
@pytest.mark.parametrize("alias", ["claude-sonnet-5", "gemini-3.1-pro", "gpt-5.5"])
def test_web_search_built_in_only_fails(alias: str) -> None:
    with pytest.raises(PrerequisiteError) as ex:
        _resolve_search_tools(_search_provider(alias), web_search())
    assert "web_search() has no provider" in str(ex.value)
    assert 'web_search("tavily")' in str(ex.value)
    # the Responses API fix is offered only for OpenAI models
    assert ("responses_api=true" in str(ex.value)) == alias.startswith("gpt")


@skip_if_no_openai_package
@pytest.mark.parametrize("external", ["tavily", "exa", "google"])
def test_web_search_external_provider_passes(
    external: Literal["tavily", "exa", "google"],
) -> None:
    _resolve_search_tools(
        _search_provider("claude-sonnet-5"), web_search(["anthropic", external])
    )


@skip_if_no_openai_package
def test_web_search_openai_responses_passes() -> None:
    _resolve_search_tools(_search_provider("gpt-5.5", responses_api=True), web_search())


@skip_if_no_openai_package
def test_web_search_openai_responses_internal_tools_off_fails() -> None:
    with pytest.raises(PrerequisiteError) as ex:
        _resolve_search_tools(
            _search_provider("gpt-5.5", responses_api=True),
            web_search(),
            GenerateConfig(internal_tools=False),
        )
    # already on the Responses API, so that fix is not offered
    assert "responses_api=true" not in str(ex.value)


@skip_if_no_openai_package
def test_web_search_responses_non_openai_fails() -> None:
    with pytest.raises(PrerequisiteError):
        _resolve_search_tools(
            _search_provider("claude-sonnet-5", responses_api=True),
            web_search(["anthropic"]),
        )


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "env,key",
    [
        ({"LITELLM_PROXY_API_KEY": "proxy", "LITELLM_API_KEY": "short"}, "proxy"),
        ({"LITELLM_API_KEY": "short"}, "short"),
    ],
)
def test_env_var_fallbacks(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], key: str
) -> None:
    for var in (
        "LITELLM_PROXY_BASE_URL",
        "LITELLM_PROXY_API_BASE",
        "LITELLM_PROXY_API_KEY",
        "LITELLM_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://proxy.example:4000")
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    api = get_model("litellm-proxy/claude", model_info=False, memoize=False).api
    assert api.base_url == "http://proxy.example:4000"
    assert api.api_key == key


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "upstream,vendor",
    [
        ("anthropic/claude-metis-v1", "anthropic"),
        ("bedrock/converse/us.anthropic.claude-metis-v1:0", "anthropic"),
        ("openai/gpt-7-preview", "openai"),
        ("gemini/gemini-4-pro", "google"),
        ("xai/mimas", "grok"),
    ],
)
def test_gate_suggests_frontier_base_model(
    model_info_stub: ModelInfoStub, upstream: str, vendor: Vendor
) -> None:
    base_model = frontier_base_model(vendor)
    _serve(model_info_stub, [_row("next", upstream)])
    with pytest.raises(PrerequisiteError) as ex:
        _stub_model(model_info_stub, "next")
    assert f"        base_model: {base_model}\n" in str(ex.value.message)


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "upstream,adaptive",
    [
        ("anthropic/claude-metis-v1", True),
        ("bedrock/converse/us.anthropic.claude-metis-v1:0", True),
        ("openai/gpt-7-preview", False),
    ],
)
def test_gate_suggests_adaptive_thinking_for_claude(
    model_info_stub: ModelInfoStub, upstream: str, adaptive: bool
) -> None:
    _serve(model_info_stub, [_row("next", upstream)])
    with pytest.raises(PrerequisiteError) as ex:
        _stub_model(model_info_stub, "next")
    message = str(ex.value.message)
    assert (
        "        supports_reasoning: true\n"
        "        supports_adaptive_thinking: true\n" in message
    ) == adaptive
    assert ("base_model does not change this" in message) == adaptive


@skip_if_no_openai_package
def test_gate_suggests_limits_for_other_vendors(
    model_info_stub: ModelInfoStub,
) -> None:
    _serve(model_info_stub, [_row("next", "hosted_vllm/llama-5")])
    with pytest.raises(PrerequisiteError) as ex:
        _stub_model(model_info_stub, "next")
    message = str(ex.value.message)
    assert "max_input_tokens: <context window>" in message
    assert "max_output_tokens: <output limit>" in message


# The upstream's usage for a call that writes the prompt cache with a 1 hour TTL
CACHE_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "cache_read_input_tokens": 3000,
    "cache_creation_input_tokens": 2000,
    "cache_creation": {
        "ephemeral_5m_input_tokens": 0,
        "ephemeral_1h_input_tokens": 2000,
    },
}


def _cache_usage_route(request: StubRequest) -> dict[str, Any] | SSE | None:
    response = route(request)
    if request.path.split("?")[0].endswith("/v1/messages"):
        if isinstance(response, SSE):
            response.events[0][1]["message"]["usage"] = CACHE_USAGE
        elif isinstance(response, dict):
            response["usage"] = CACHE_USAGE
    return response


CLAUDE_DEPLOYMENTS = {
    # names neither LiteLLM nor Inspect know
    "claude-metis": "anthropic/claude-metis-v1",
    "bedrock-metis": "bedrock/converse/us.anthropic.claude-metis-v1:0",
}
CLAUDE_MODEL_INFO = {
    # without it LiteLLM rejects tool_choice for an unknown Bedrock model
    "bedrock-metis": {"base_model": "anthropic/claude-opus-5-5"},
}


@pytest.fixture(scope="module")
def claude_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiteLLMProxy]:
    with fake_upstream(_cache_usage_route) as upstream:
        credentials = {
            "anthropic": {"api_key": "fake"},
            "bedrock": {
                "aws_access_key_id": "fake",
                "aws_secret_access_key": "fake",
                "aws_region_name": "us-east-1",
            },
        }
        config = {
            "model_list": [
                {
                    "model_name": alias,
                    "litellm_params": {
                        "model": model,
                        "api_base": upstream.docker_url,
                    }
                    | credentials[model.split("/")[0]],
                    "model_info": CLAUDE_MODEL_INFO.get(alias, {}),
                }
                for alias, model in CLAUDE_DEPLOYMENTS.items()
            ],
            "router_settings": {"num_retries": 0},
        }
        with run_litellm_proxy(
            tmp_path_factory.mktemp("litellm-claude"), config, capture=True
        ) as proxy:
            yield proxy


def _lookup_tool() -> ToolInfo:
    return ToolInfo(
        name="lookup",
        description="Look up a code.",
        parameters=ToolParams(
            properties={
                "code": ToolParam(type="string", pattern="^[A-Z]{3}$", minLength=3)
            },
            required=["code"],
        ),
    )


def _tool_conversation() -> list[ChatMessage]:
    return [
        ChatMessageSystem(content="Be helpful."),
        ChatMessageUser(content="Look up ABC."),
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id="toolu_1", function="lookup", arguments={"code": "ABC"})
            ],
        ),
        ChatMessageTool(content="ABC is 1.", tool_call_id="toolu_1", function="lookup"),
    ]


class ClaudeCall(NamedTuple):
    api: LiteLLMProxyAPI
    output: ModelOutput
    request: dict[str, Any]
    """The request the provider sent to the proxy."""

    upstream: dict[str, Any]
    """The request the proxy sent upstream."""


async def _generate_claude(
    proxy: LiteLLMProxy, alias: str, config: GenerateConfig, **model_args: Any
) -> ClaudeCall:
    api = _proxy_api(
        get_model(
            f"litellm-proxy/{alias}",
            base_url=proxy.base_url,
            api_key=proxy.api_key,
            max_retries=0,
            memoize=False,
            **({"model_info": False} | model_args),
        )
    )
    call_id = str(uuid.uuid4())
    config = config.merge(GenerateConfig(extra_headers={CALL_ID_HEADER: call_id}))
    if config.max_tokens is None:
        config.max_tokens = api.max_tokens_for_config(config)
    result = await api.generate(_tool_conversation(), [_lookup_tool()], "auto", config)
    assert isinstance(result, tuple)
    output, model_call = result
    assert isinstance(output, ModelOutput), output
    assert proxy.capture_dir is not None
    return ClaudeCall(
        api=api,
        output=output,
        request=model_call.request,
        upstream=upstream_exchange(proxy.capture_dir, call_id).request,
    )


def _anthropic_breakpoints(request: dict[str, Any]) -> list[str]:
    """Where an Anthropic Messages request has cache breakpoints."""
    system = request["system"]
    blocks = system if isinstance(system, list) else []
    marked = [f"system[{i}]" for i, b in enumerate(blocks) if _cached(b)]
    marked += [f"tools[{i}]" for i, t in enumerate(request["tools"]) if _cached(t)]
    for i, message in enumerate(request["messages"]):
        content = message["content"]
        for block in content if isinstance(content, list) else []:
            nested = block.get("content") if block["type"] == "tool_result" else None
            nested = nested if isinstance(nested, list) else []
            if _cached(block) or any(_cached(b) for b in nested):
                marked.append(f"messages[{i}].{block['type']}")
    return marked


def _bedrock_breakpoints(request: dict[str, Any]) -> list[str]:
    """Where a Bedrock Converse request has cache points."""
    marked = [
        f"system[{i - 1}]"
        for i, block in enumerate(request["system"])
        if "cachePoint" in block
    ]
    for i, message in enumerate(request["messages"]):
        for j, block in enumerate(message["content"]):
            if "cachePoint" in block:
                marked.append(f"messages[{i}].{next(iter(message['content'][j - 1]))}")
    return marked


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_claude_request(claude_proxy: LiteLLMProxy) -> None:
    call = await _generate_claude(
        claude_proxy, "claude-metis", GenerateConfig(reasoning_effort="high")
    )
    assert call.request["stream"] is True
    request = call.upstream
    assert request["max_tokens"] == 48000
    schema = request["tools"][0]["input_schema"]
    assert schema["properties"]["code"]["pattern"] == "^[A-Z]{3}$"
    assert schema["properties"]["code"]["minLength"] == 3
    assert _anthropic_breakpoints(request) == [
        "system[0]",
        "tools[0]",
        "messages[0].text",
        "messages[2].tool_result",
    ]
    # no placeholder for the tool call turn's missing text
    assert request["messages"][1]["content"] == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "lookup",
            "input": {"code": "ABC"},
        }
    ]
    usage = call.output.usage
    assert usage is not None
    assert usage.input_tokens_cache_write == 2000
    assert usage.input_tokens_cache_read == 3000
    assert call.api.cache_write_ttl() == "1h"


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_claude_request_bedrock(
    claude_proxy: LiteLLMProxy,
) -> None:
    call = await _generate_claude(
        claude_proxy, "bedrock-metis", GenerateConfig(), stream=False, model_info=True
    )
    request = call.upstream
    assert request["inferenceConfig"]["maxTokens"] == 32000
    schema = request["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert schema["properties"]["code"]["pattern"] == "^[A-Z]{3}$"
    assert _bedrock_breakpoints(request) == [
        "system[0]",
        "messages[0].text",
        "messages[2].toolResult",
    ]


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_litellm_proxy_claude_cache_prompt_false(
    claude_proxy: LiteLLMProxy,
) -> None:
    call = await _generate_claude(
        claude_proxy, "claude-metis", GenerateConfig(cache_prompt=False)
    )
    assert _anthropic_breakpoints(call.upstream) == []
