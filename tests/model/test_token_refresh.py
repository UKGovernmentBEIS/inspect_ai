import importlib
import json
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from subprocess import Popen
from typing import Any, NamedTuple, cast
from unittest.mock import Mock

import anthropic
import anyio
import grpc
import httpx
import httpx2
import openai
import pytest
from openai import AuthenticationError, DefaultAsyncHttpxClient
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai._util._async import tg_collect
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.dataset import Sample
from inspect_ai.hooks import ApiKeyOverride, Hooks, hooks
from inspect_ai.model import (
    BatchConfig,
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelAPI,
    ModelOutput,
    get_model,
)
from inspect_ai.model._model_info import _get_model_info_direct
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.model._providers.grok import GrokAPI
from inspect_ai.model._providers.openai import OpenAIAPI
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.openrouter import OpenRouterAPI
from inspect_ai.model._providers.providers import validate_openai_client
from inspect_ai.model._providers.vllm import VLLMAPI
from inspect_ai.model._providers.vllm_completions import VLLMCompletionsAPI
from inspect_ai.model._registry import modelapi
from inspect_ai.tool import ToolChoice, ToolInfo


class Mock401Exception(Exception):
    pass


class Mock401API(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=["TEST_API_KEY"],
            config=config,
        )
        self.fail_count = model_args.get("fail_count", 2)
        self.call_count = 0
        self.initialize_count = 0

    def initialize(self) -> None:
        """Track how many times initialize is called."""
        super().initialize()
        self.initialize_count += 1

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        """Fail with 401-like exception first N times, then succeed."""
        self.call_count += 1

        if self.call_count <= self.fail_count:
            raise Mock401Exception(f"Simulated 401 error (attempt {self.call_count})")

        # After N failures, succeed
        return ModelOutput.from_content(
            model=self.model_name,
            content="Success after token refresh",
        )

    def is_auth_failure(self, ex: Exception) -> bool:
        """Detect our mock 401 exception."""
        return isinstance(ex, Mock401Exception)

    def should_retry(self, ex: Exception) -> bool:
        """Retry on our mock 401 exception."""
        return isinstance(ex, Mock401Exception)


class MockRefreshTokenHook(Hooks):
    def __init__(self) -> None:
        self.call_count = 0
        self.provided_tokens: list[str] = []

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        """Provide incrementing token values."""
        if data.env_var_name != "TEST_API_KEY":
            return None

        self.call_count += 1
        token = f"token-{self.call_count}"
        self.provided_tokens.append(token)
        return token


@pytest.fixture
def mock_refresh_token_hook() -> Generator[MockRefreshTokenHook, None, None]:
    @hooks("test_token_refresh", description="Test token refresh hook")
    def get_hook() -> type[MockRefreshTokenHook]:
        return MockRefreshTokenHook

    hook = registry_lookup("hooks", "test_token_refresh")
    assert isinstance(hook, MockRefreshTokenHook)

    try:
        yield hook
    finally:
        # Remove the hook from the registry to avoid conflicts in other tests.
        del _registry["hooks:test_token_refresh"]


def test_reactive_token_refresh_on_401(mock_refresh_token_hook: MockRefreshTokenHook):
    @modelapi(name="mock401")
    def mock401() -> type[ModelAPI]:
        return Mock401API

    try:
        task = Task(dataset=[Sample(input="test", target="test")])

        model = get_model("mock401/test", api_key="initial-token", fail_count=2)
        provider = model.api
        assert isinstance(provider, Mock401API)
        log = eval(task, model=model)[0]

        assert log.status == "success"
        assert log.samples is not None
        assert len(log.samples) == 1

        assert provider.call_count == 3
        assert provider.initialize_count == 2

        # Verify hook was called 3 times: once during __init__, twice during retries
        assert mock_refresh_token_hook.call_count == 3
        assert mock_refresh_token_hook.provided_tokens == [
            "token-1",
            "token-2",
            "token-3",
        ]

        assert provider.api_key == "token-3"
    finally:
        # Remove the provider from the registry to avoid conflicts in other tests.
        del _registry["modelapi:mock401"]


_OPENAI_COMPLETION = {
    "id": "test",
    "object": "chat.completion",
    "created": 0,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "ok"},
        }
    ],
}

_ANTHROPIC_MESSAGE = {
    "id": "test",
    "type": "message",
    "role": "assistant",
    "model": "test-model",
    "content": [{"type": "text", "text": "ok"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


@pytest.mark.parametrize(
    "provider,model_name,base_url,auth_header",
    [
        (OpenAICompatibleAPI, "test/model", "https://example.com/v1", "authorization"),
        (OpenRouterAPI, "test/model", "https://example.com/v1", "authorization"),
        (OpenAIAPI, "gpt-4o", "https://example.com/v1", "authorization"),
        (OpenAIAPI, "azure/gpt-4o", "https://example.openai.azure.com", "api-key"),
        (AnthropicAPI, "claude-sonnet-4-6", "https://example.com", "x-api-key"),
        (
            AnthropicAPI,
            "azure/claude-sonnet-4-6",
            "https://example.services.ai.azure.com/anthropic",
            "api-key",
        ),
    ],
)
@pytest.mark.parametrize("parallel_status", [200, 500, 401])
async def test_refresh_preserves_concurrent_requests(
    monkeypatch: pytest.MonkeyPatch,
    provider: type[OpenAICompatibleAPI] | type[OpenAIAPI] | type[AnthropicAPI],
    model_name: str,
    base_url: str,
    auth_header: str,
    parallel_status: int,
) -> None:
    """Refresh during an active request, an SDK retry, or another auth failure."""
    parallel_started = anyio.Event()
    refreshed = anyio.Event()
    token = "old-token"
    seen: dict[str, list[str]] = {"auth": [], "parallel": []}

    def override_api_key(env_var_name: str, value: str) -> str:
        return token

    monkeypatch.setattr("inspect_ai.hooks._hooks.override_api_key", override_api_key)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    async def respond(request: httpx2.Request) -> httpx2.Response:
        marker = json.loads(request.content)["messages"][0]["content"]
        seen[marker].append(request.headers[auth_header].removeprefix("Bearer "))
        if len(seen[marker]) == 1:
            if marker == "auth":
                await parallel_started.wait()
                return httpx2.Response(401, json={"error": {"message": "expired"}})
            parallel_started.set()
            await refreshed.wait()
            if parallel_status != 200:
                return httpx2.Response(
                    parallel_status,
                    json={"error": {"message": "retry"}},
                )
        return httpx2.Response(
            200,
            json=_ANTHROPIC_MESSAGE if provider is AnthropicAPI else _OPENAI_COMPLETION,
        )

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    api = provider(
        model_name,
        api_key=token,
        base_url=base_url,
        http_client=http_client,
        max_retries=1,
    )
    model = Model(api=api, config=GenerateConfig())
    client = api.client

    async def create(marker: str) -> None:
        if isinstance(api, AnthropicAPI):
            await api.client.messages.create(
                model="test-model",
                max_tokens=1,
                messages=[{"role": "user", "content": marker}],
            )
        else:
            await api.client.chat.completions.create(
                model="test-model", messages=[{"role": "user", "content": marker}]
            )

    async def generate(marker: str) -> None:
        nonlocal token
        try:
            await create(marker)
        except (openai.AuthenticationError, anthropic.AuthenticationError) as ex:
            token = "new-token"
            await model.before_retry(ex)
            # before retrying, since a rebuilt client would use the real network
            assert api.client is client
            assert not http_client.is_closed
            refreshed.set()
            await create(marker)

    try:
        with anyio.fail_after(10):
            await tg_collect([lambda: generate("auth"), lambda: generate("parallel")])
        assert seen["auth"] == ["old-token", "new-token"]
        assert seen["parallel"] == ["old-token"] + (
            ["new-token"] if parallel_status != 200 else []
        )
    finally:
        await api.aclose()
        await http_client.aclose()
    assert http_client.is_closed


async def test_anthropic_auth_token_refresh_rereads_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key hooks don't cover ANTHROPIC_AUTH_TOKEN, so a refresh re-reads it."""
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    api = AnthropicAPI("claude-sonnet-4-6", api_key="api-key")
    try:
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "new-token")
        await api.refresh_credentials()
        assert isinstance(api.client, anthropic.AsyncAnthropic)
        assert api.client.auth_headers == {"Authorization": "Bearer new-token"}
    finally:
        await api.aclose()


async def test_azure_openai_refresh_ignores_environment_ad_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refreshed Azure key is sent even when AZURE_OPENAI_AD_TOKEN is set.

    openai < 3.4.0 read that variable at client construction and sent it in
    preference to the key, so an in-place key update kept sending a stale token.
    """
    token = "old-key"
    seen: list[tuple[str | None, str | None]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        return token

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(
            (request.headers.get("api-key"), request.headers.get("authorization"))
        )
        if len(seen) == 1:
            return httpx2.Response(401, json={"error": {"message": "expired"}})
        return httpx2.Response(200, json=_OPENAI_COMPLETION)

    monkeypatch.setattr("inspect_ai.hooks._hooks.override_api_key", override_api_key)
    monkeypatch.setenv("AZURE_OPENAI_AD_TOKEN", "old-ad-token")
    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    api = OpenAIAPI(
        "azure/gpt-4o",
        api_key=token,
        base_url="https://example.openai.azure.com",
        http_client=http_client,
        max_retries=0,
    )

    async def create() -> None:
        await api.client.chat.completions.create(
            model="test-model", messages=[{"role": "user", "content": "hello"}]
        )

    try:
        with pytest.raises(openai.AuthenticationError) as exc:
            await create()
        token = "new-key"
        monkeypatch.setenv("AZURE_OPENAI_AD_TOKEN", "new-ad-token")
        await Model(api=api, config=GenerateConfig()).before_retry(exc.value)
        await create()
        assert seen == [("old-key", None), ("new-key", None)]
    finally:
        await api.aclose()
        await http_client.aclose()


@pytest.mark.parametrize("installed,supported", [("3.3.1", False), ("3.4.0", True)])
def test_openai_minimum_version_supports_in_place_refresh(
    monkeypatch: pytest.MonkeyPatch, installed: str, supported: bool
) -> None:
    """The openai floor excludes SDKs where an in-place Azure key update is ignored."""
    for module in ("inspect_ai._util.version", "inspect_ai._util.error"):
        monkeypatch.setattr(f"{module}.version", lambda package: installed)
    if supported:
        validate_openai_client("OpenAI API")
    else:
        with pytest.raises(PrerequisiteError):
            validate_openai_client("OpenAI API")


@pytest.mark.parametrize("provider", [VLLMAPI, VLLMCompletionsAPI])
@pytest.mark.parametrize("managed", [True, False])
@pytest.mark.parametrize("lazy_init", [True, False])
async def test_vllm_credentials_match_server(
    monkeypatch: pytest.MonkeyPatch,
    provider: type[VLLMAPI],
    managed: bool,
    lazy_init: bool,
) -> None:
    """Managed credentials last until restart; external credentials can rotate."""
    token = "hook-key"
    launches: list[str] = []
    processes: list[Mock] = []
    clients: list[DefaultAsyncHttpxClient] = []
    reject_next = False
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.setattr("inspect_ai.model._providers.vllm._vllm_servers", {})

    def override_key(env_var_name: str, value: str) -> str | None:
        return token if env_var_name == "VLLM_API_KEY" else None

    def launch(
        api: VLLMAPI, model_path: str, port: int | None
    ) -> tuple[str, Popen[str], int]:
        assert api.api_key is not None
        launches.append(api.api_key)
        process = Mock(spec=Popen)
        process.poll.return_value = None
        processes.append(process)
        return "http://localhost:8000/v1", cast(Popen[str], process), 8000

    def terminate(process: Mock) -> None:
        process.poll.return_value = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal reject_next
        expected_key = launches[-1] if managed else token
        if request.headers.get("authorization") != f"Bearer {expected_key}":
            return httpx2.Response(401, json={"error": {"message": "wrong key"}})
        if request.url.path.endswith("/models"):
            return httpx2.Response(200, json={"data": []})
        if reject_next:
            reject_next = False
            return httpx2.Response(401, json={"error": {"message": "retry auth"}})
        choice = (
            {"message": {"role": "assistant", "content": "ok"}}
            if "/chat/" in request.url.path
            else {"text": "ok"}
        )
        return httpx2.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion"
                if "/chat/" in request.url.path
                else "text_completion",
                "created": 0,
                "model": "credential-test",
                "choices": [{"index": 0, "finish_reason": "stop", **choice}],
            },
        )

    def make_client(api: VLLMAPI) -> DefaultAsyncHttpxClient:
        client = DefaultAsyncHttpxClient(transport=httpx2.MockTransport(respond))
        clients.append(client)
        return client

    monkeypatch.setattr("inspect_ai.hooks._hooks.override_api_key", override_key)
    monkeypatch.setattr(VLLMAPI, "_start_server", launch)
    monkeypatch.setattr(VLLMAPI, "_create_http_client", make_client)
    monkeypatch.setattr("inspect_ai.model._providers.vllm.terminate_process", terminate)
    api = provider(
        "credential-test",
        api_key="initial-key",
        base_url=None if managed else "http://localhost:8000/v1",
        lazy_init=lazy_init,
    )

    async def generate(instance: VLLMAPI) -> None:
        result = await instance.generate(
            [ChatMessageUser(content="hello")], [], "none", GenerateConfig(max_tokens=1)
        )
        output = result[0] if isinstance(result, tuple) else result
        assert isinstance(output, ModelOutput)
        assert output.completion == "ok"

    try:
        await generate(api)
        assert launches == (["hook-key"] if managed else [])
        client = api.client
        token = "rotated-key"
        reject_next = managed
        with pytest.raises(AuthenticationError) as exc:
            await generate(api)
        await Model(api=api, config=GenerateConfig()).before_retry(exc.value)
        await generate(api)
        assert api.client is client
        assert not client.is_closed()
        assert launches == (["hook-key"] if managed else [])
        if managed:
            # A second client must reuse the live server's key even if the
            # hook now supplies a different key for a future server launch.
            other = provider("credential-test", api_key="another-initial-key")
            await generate(other)
            await other.client.close()
            assert other.api_key == "hook-key"
            await api.aclose()
            await generate(api)
            assert launches == ["hook-key", "rotated-key"]
        else:
            adapter_headers: list[str] = []

            def adapter_models(request: httpx.Request) -> httpx.Response:
                authorization = request.headers["authorization"]
                adapter_headers.append(authorization)
                if authorization != f"Bearer {token}":
                    return httpx.Response(401)
                return httpx.Response(200, json={"data": [{"id": "preloaded"}]})

            class AdapterClient(httpx.Client):
                def __init__(self) -> None:
                    super().__init__(transport=httpx.MockTransport(adapter_models))

            monkeypatch.setattr(
                "inspect_ai.model._providers._vllm_lora.httpx.Client",
                AdapterClient,
            )
            other = provider(
                "credential-test:preloaded",
                api_key=token,
                base_url="http://localhost:8000/v1",
            )
            try:
                await generate(other)
            finally:
                await other.client.close()
            assert adapter_headers == ["Bearer rotated-key"]
    finally:
        await api.aclose()
        for http_client in clients:
            await http_client.aclose()
        assert all(process.poll() == 0 for process in processes)


class _VLLMDiscoveryServer:
    """vLLM stand-in that rejects the first request of each kind in ``reject_once``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, managed: bool) -> None:
        import inspect_ai.model._model_info as _model_info

        self.managed = managed
        self.token = "hook-key"
        self.launches: list[str] = []
        self.processes: list[Mock] = []
        self.http_clients: list[DefaultAsyncHttpxClient] = []
        self.models_auth: list[str] = []
        self.models_started = anyio.Event()
        self.release_models: anyio.Event | None = None
        self.key_refreshed = anyio.Event()
        self.reject_once = {"models", "generate"}

        # keep set_model_info() writes out of the process-wide registry
        monkeypatch.setattr(
            _model_info, "_custom_models", dict(_model_info._custom_models)
        )
        monkeypatch.setattr(_model_info, "_result_cache", {})
        monkeypatch.setattr(
            "inspect_ai.model._providers.vllm._registered_context_windows", {}
        )
        monkeypatch.setattr("inspect_ai.model._providers.vllm._vllm_servers", {})
        monkeypatch.delenv("VLLM_BASE_URL", raising=False)
        monkeypatch.setattr(
            "inspect_ai.hooks._hooks.override_api_key", self._override_key
        )
        # plain functions, so the patched methods receive the provider
        monkeypatch.setattr(
            VLLMAPI,
            "_start_server",
            lambda api, model_path, port=None: self._launch(api, model_path, port),
        )
        monkeypatch.setattr(
            VLLMAPI, "_create_http_client", lambda api: self._make_client(api)
        )
        monkeypatch.setattr(
            "inspect_ai.model._providers.vllm.terminate_process", self._terminate
        )

    def _override_key(self, env_var_name: str, value: str) -> str | None:
        if env_var_name != "VLLM_API_KEY":
            return None
        if self.token != "hook-key":
            self.key_refreshed.set()
        return self.token

    def _launch(
        self, api: VLLMAPI, model_path: str, port: int | None
    ) -> tuple[str, Popen[str], int]:
        assert api.api_key is not None
        self.launches.append(api.api_key)
        process = Mock(spec=Popen)
        process.poll.return_value = None
        self.processes.append(process)
        return "http://localhost:8000/v1", cast(Popen[str], process), 8000

    @staticmethod
    def _terminate(process: Mock) -> None:
        process.poll.return_value = 0

    def _make_client(self, api: VLLMAPI) -> DefaultAsyncHttpxClient:
        client = DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self._respond))
        self.http_clients.append(client)
        return client

    async def _respond(self, request: httpx2.Request) -> httpx2.Response:
        is_models = request.url.path.endswith("/models")
        is_chat = "/chat/" in request.url.path
        kind = "models" if is_models else "generate"
        if is_models:
            self.models_auth.append(request.headers["authorization"])
            self.models_started.set()
            if self.release_models is not None:
                await self.release_models.wait()
        expected_key = self.launches[-1] if self.managed else self.token
        if (
            kind in self.reject_once
            or request.headers["authorization"] != f"Bearer {expected_key}"
        ):
            self.reject_once.discard(kind)
            return httpx2.Response(401, json={"error": {"message": "expired"}})
        if is_models:
            return httpx2.Response(
                200,
                json={"data": [{"id": "credential-test", "max_model_len": 4096}]},
            )
        choice = (
            {"message": {"role": "assistant", "content": "ok"}}
            if is_chat
            else {"text": "ok"}
        )
        return httpx2.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion" if is_chat else "text_completion",
                "created": 0,
                "model": "credential-test",
                "choices": [{"index": 0, "finish_reason": "stop", **choice}],
            },
        )

    async def aclose(self, api: VLLMAPI) -> None:
        await api.aclose()
        for http_client in self.http_clients:
            await http_client.aclose()


async def _generate_ok(api: VLLMAPI) -> None:
    result = await api.generate(
        [ChatMessageUser(content="hello")], [], "none", GenerateConfig(max_tokens=1)
    )
    output = result[0] if isinstance(result, tuple) else result
    assert isinstance(output, ModelOutput)
    assert output.completion == "ok"


@pytest.mark.parametrize("provider", [VLLMAPI, VLLMCompletionsAPI])
@pytest.mark.parametrize("managed", [True, False])
async def test_vllm_refresh_rediscovers_context_window(
    monkeypatch: pytest.MonkeyPatch, provider: type[VLLMAPI], managed: bool
) -> None:
    """Discovery that failed authentication runs again after a refresh."""
    server = _VLLMDiscoveryServer(monkeypatch, managed)
    api = provider(
        "credential-test",
        api_key="initial-key",
        base_url=None if managed else "http://localhost:8000/v1",
        lazy_init=False,
    )
    try:
        client = api.client
        http_client = api.http_client
        with pytest.raises(AuthenticationError) as exc:
            await _generate_ok(api)
        assert _get_model_info_direct(api.input_tokens_name()) is None

        server.token = "rotated-key"
        await Model(api=api, config=GenerateConfig()).before_retry(exc.value)
        await _generate_ok(api)

        refreshed_key = "hook-key" if managed else "rotated-key"
        assert server.models_auth == ["Bearer hook-key", f"Bearer {refreshed_key}"]
        registered = _get_model_info_direct(api.input_tokens_name())
        assert registered is not None and registered.context_length == 4096
        assert api.client is client
        assert api.http_client is http_client
        assert not client.is_closed()
        assert server.launches == (["hook-key"] if managed else [])
        assert all(process.poll() is None for process in server.processes)
    finally:
        await server.aclose(api)


@pytest.mark.parametrize("provider", [VLLMAPI, VLLMCompletionsAPI])
@pytest.mark.parametrize("cancel_refresh", [False, True])
async def test_vllm_refresh_during_discovery(
    monkeypatch: pytest.MonkeyPatch, provider: type[VLLMAPI], cancel_refresh: bool
) -> None:
    """A discovery response sent with old credentials cannot undo a refresh.

    That holds even when the sample doing the refresh is cancelled once the
    new key is in place, since other samples keep using it.
    """
    server = _VLLMDiscoveryServer(monkeypatch, managed=False)
    server.reject_once = {"models"}
    server.release_models = anyio.Event()
    api = provider(
        "credential-test",
        api_key="initial-key",
        base_url="http://localhost:8000/v1",
        lazy_init=False,
    )
    refresh_scope = anyio.CancelScope()

    async def refresh() -> None:
        with refresh_scope:
            await api.refresh_credentials()

    try:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tg:
                tg.start_soon(api._register_context_window)
                await server.models_started.wait()
                server.token = "rotated-key"
                tg.start_soon(refresh)
                # the refresh has updated the key; release the stale 401
                await server.key_refreshed.wait()
                if cancel_refresh:
                    refresh_scope.cancel()
                server.release_models.set()
        server.release_models = None
        await _generate_ok(api)

        assert server.models_auth == ["Bearer hook-key", "Bearer rotated-key"]
        registered = _get_model_info_direct(api.input_tokens_name())
        assert registered is not None and registered.context_length == 4096
    finally:
        await server.aclose(api)


# xai_sdk ships no type stubs; going through import_module keeps mypy out of it
_BATCH_PB2: Any = importlib.import_module("xai_sdk.proto").batch_pb2
_CHAT_PB2: Any = importlib.import_module("xai_sdk.proto").chat_pb2
_EMPTY_PB2: Any = importlib.import_module("google.protobuf.empty_pb2")


class _GrokBatchServer(grpc.GenericRpcHandler):
    """xAI batch API stand-in that scripts each batch by its prompt.

    `token` is the key the provider's key hook supplies. The "parallel"
    batch's status check stays in flight once the "auth" batch exists, until
    the test sets `refreshed`. The "auth" batch's first status check fails
    authentication, after which the old key is rejected. With `hold` set, the
    first call of that method waits after authenticating until the test sets
    `release`, and results come in two pages.
    """

    def __init__(self, parallel_status: grpc.StatusCode) -> None:
        self.parallel_status = parallel_status
        self.parallel_started = anyio.Event()
        self.refreshed = anyio.Event()
        self.parallel_added = anyio.Event()
        self.token = "old-token"
        self.expired = False
        self.markers: dict[str, str] = {}
        self.request_ids: dict[str, str] = {}
        self.batch_keys: dict[str, list[str]] = {}
        self.hold: str | None = None
        self.held = anyio.Event()
        self.release = anyio.Event()

    def keys_by_marker(self) -> dict[str, list[list[str]]]:
        """The keys each prompt's batches were sent with, repeats removed."""
        seen: dict[str, list[list[str]]] = {}
        for batch_id, keys in self.batch_keys.items():
            unique = [key for i, key in enumerate(keys) if i == 0 or keys[i - 1] != key]
            seen.setdefault(self.markers[batch_id], []).append(unique)
        return seen

    async def _authenticate(
        self, batch_id: str, context: grpc.aio.ServicerContext
    ) -> None:
        metadata = dict(context.invocation_metadata() or ())
        key = str(metadata["authorization"]).removeprefix("Bearer ")
        self.batch_keys.setdefault(batch_id, []).append(key)
        if self.expired and key == "old-token":
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "expired")

    async def _hold(self, method: str) -> None:
        if self.hold == method and not self.held.is_set():
            self.held.set()
            await self.release.wait()

    async def _create_batch(
        self, request: Any, context: grpc.aio.ServicerContext
    ) -> Any:
        batch_id = f"batch-{len(self.batch_keys)}"
        await self._authenticate(batch_id, context)
        await self._hold("CreateBatch")
        return _BATCH_PB2.Batch(batch_id=batch_id)

    async def _add_batch_requests(
        self, request: Any, context: grpc.aio.ServicerContext
    ) -> Any:
        await self._authenticate(request.batch_id, context)
        (batch_request,) = request.batch_requests
        marker = batch_request.completion_request.messages[0].content[0].text
        self.markers[request.batch_id] = marker
        self.request_ids[request.batch_id] = batch_request.batch_request_id
        if marker == "parallel":
            self.parallel_added.set()
        return _EMPTY_PB2.Empty()

    async def _get_batch(self, request: Any, context: grpc.aio.ServicerContext) -> Any:
        batch_id = request.batch_id
        await self._authenticate(batch_id, context)
        marker = self.markers[batch_id]
        pending = _BATCH_PB2.BatchState(num_requests=1, num_pending=1)
        if marker == "parallel" and not self.parallel_started.is_set():
            if "auth" not in self.markers.values():
                return _BATCH_PB2.Batch(batch_id=batch_id, state=pending)
            self.parallel_started.set()
            await self.refreshed.wait()
            if self.parallel_status != grpc.StatusCode.OK:
                await context.abort(self.parallel_status, "expired")
        elif marker == "auth" and not self.expired:
            await self.parallel_started.wait()
            self.expired = True
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "expired")
        done = _BATCH_PB2.BatchState(num_requests=1, num_success=1)
        return _BATCH_PB2.Batch(batch_id=batch_id, state=done)

    async def _list_batch_results(
        self, request: Any, context: grpc.aio.ServicerContext
    ) -> Any:
        await self._authenticate(request.batch_id, context)
        await self._hold("ListBatchResults")
        if self.hold is not None and not request.pagination_token:
            return _BATCH_PB2.ListBatchResultsResponse(pagination_token="page-2")
        completion = _CHAT_PB2.GetChatCompletionResponse(
            id="grok-response",
            outputs=[
                _CHAT_PB2.CompletionOutput(
                    index=0,
                    finish_reason="REASON_STOP",
                    message=_CHAT_PB2.CompletionMessage(
                        role=_CHAT_PB2.MessageRole.ROLE_ASSISTANT, content="ok"
                    ),
                )
            ],
        )
        return _BATCH_PB2.ListBatchResultsResponse(
            results=[
                _BATCH_PB2.BatchResult(
                    batch_request_id=self.request_ids[request.batch_id],
                    response=_BATCH_PB2.BatchResultData(completion_response=completion),
                )
            ]
        )

    def service(
        self, handler_call_details: grpc.HandlerCallDetails
    ) -> grpc.RpcMethodHandler | None:
        handlers = {
            "CreateBatch": (self._create_batch, _BATCH_PB2.CreateBatchRequest),
            "AddBatchRequests": (
                self._add_batch_requests,
                _BATCH_PB2.AddBatchRequestsRequest,
            ),
            "GetBatch": (self._get_batch, _BATCH_PB2.GetBatchRequest),
            "ListBatchResults": (
                self._list_batch_results,
                _BATCH_PB2.ListBatchResultsRequest,
            ),
        }
        method = str(handler_call_details.method).rsplit("/", 1)[-1]
        if method not in handlers:
            return None
        handler, request_type = handlers[method]
        return grpc.unary_unary_rpc_method_handler(
            handler,
            request_deserializer=request_type.FromString,
            response_serializer=lambda response: response.SerializeToString(),
        )


class _GrokBatchProvider(NamedTuple):
    api: GrokAPI
    # every xAI client the provider created, with a `closed` flag
    clients: list[Any]


@asynccontextmanager
async def _grok_batch_provider(
    monkeypatch: pytest.MonkeyPatch, server: _GrokBatchServer
) -> AsyncIterator[_GrokBatchProvider]:
    """A Grok provider on `server` whose key hook supplies `server.token`."""
    import inspect_ai.model._providers.grok as grok_module

    real_client: Any = importlib.import_module("xai_sdk").AsyncClient
    clients: list[Any] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        return server.token

    def recording_client(**kwargs: Any) -> Any:
        client = real_client(**kwargs)
        real_close = client.close

        async def close() -> None:
            client.closed = True
            await real_close()

        client.closed = False
        client.close = close
        clients.append(client)
        return client

    monkeypatch.setattr("inspect_ai.hooks._hooks.override_api_key", override_api_key)
    monkeypatch.setattr(grok_module, "AsyncClient", recording_client)

    grpc_server = grpc.aio.server()
    grpc_server.add_generic_rpc_handlers((server,))
    port = grpc_server.add_insecure_port("127.0.0.1:0")
    await grpc_server.start()
    api = GrokAPI(
        "grok-4.5",
        api_key=server.token,
        base_url=f"127.0.0.1:{port}",
        use_insecure_channel=True,
    )
    try:
        yield _GrokBatchProvider(api, clients)
    finally:
        await api.aclose()
        await grpc_server.stop(None)
    assert all(client.closed for client in clients)


async def _grok_batch_generate(api: GrokAPI, marker: str) -> None:
    config = GenerateConfig(
        batch=BatchConfig(
            size=1,
            max_size=1,
            send_delay=0.01,
            tick=0.01,
            max_consecutive_check_failures=1,
        )
    )
    result = await api.generate([ChatMessageUser(content=marker)], [], "none", config)
    output = result[0] if isinstance(result, tuple) else result
    assert isinstance(output, ModelOutput)
    assert output.completion == "ok"


@skip_if_trio
@pytest.mark.parametrize(
    "parallel_status", [grpc.StatusCode.OK, grpc.StatusCode.UNAUTHENTICATED]
)
async def test_grok_batch_refresh_preserves_concurrent_batches(
    monkeypatch: pytest.MonkeyPatch, parallel_status: grpc.StatusCode
) -> None:
    """A refresh leaves in-flight batch calls running and sends the new key after.

    The old client is closed once its in-flight call ends, whether that call
    succeeds or fails.
    """
    server = _GrokBatchServer(parallel_status)
    # whether the old client was closed by the refresh, while the parallel
    # batch's status check was still running on it
    closed_at_refresh: list[bool] = []
    async with _grok_batch_provider(monkeypatch, server) as (api, clients):
        model = Model(api=api, config=GenerateConfig())

        async def generate(marker: str) -> None:
            if marker == "auth":
                await server.parallel_added.wait()
            try:
                await _grok_batch_generate(api, marker)
            except grpc.RpcError as ex:
                assert ex.code() == grpc.StatusCode.UNAUTHENTICATED
                server.token = "new-token"
                await model.before_retry(ex)
                if marker == "auth":
                    closed_at_refresh.append(clients[0].closed)
                    server.refreshed.set()
                await _grok_batch_generate(api, marker)

        with anyio.fail_after(10):
            await tg_collect([lambda: generate("parallel"), lambda: generate("auth")])
        assert server.keys_by_marker() == {
            "auth": [["old-token"], ["new-token"]],
            "parallel": [["old-token", "new-token"]]
            if parallel_status == grpc.StatusCode.OK
            else [["old-token"], ["new-token"]],
        }
        assert closed_at_refresh == [False]
        assert len(clients) == 2
        assert clients[0].closed
        assert not clients[1].closed


@skip_if_trio
async def test_grok_batch_refresh_replaces_idle_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no batch call running, a refresh closes the old client at once.

    A refresh that gets the same key back keeps the current client.
    """
    server = _GrokBatchServer(grpc.StatusCode.OK)
    async with _grok_batch_provider(monkeypatch, server) as (api, clients):
        with anyio.fail_after(10):
            await _grok_batch_generate(api, "first")
            server.token = "new-token"
            await api.refresh_credentials()
            old_client_closed = clients[0].closed
            await api.refresh_credentials()
            await _grok_batch_generate(api, "second")
        assert server.keys_by_marker() == {
            "first": [["old-token"]],
            "second": [["new-token"]],
        }
        assert old_client_closed
        assert len(clients) == 2
        assert not clients[1].closed


@skip_if_trio
@pytest.mark.parametrize("method", ["CreateBatch", "ListBatchResults"])
async def test_grok_batch_refresh_during_multi_call_operation(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """A refresh between the calls of one batch operation applies to the next call.

    Creating a batch adds its requests in later calls, and results can span
    several pages. The call in flight finishes with the old key; the old key
    then expires, so the following calls must use the new one.
    """
    server = _GrokBatchServer(grpc.StatusCode.OK)
    server.hold = method
    closed_at_refresh: list[bool] = []
    async with _grok_batch_provider(monkeypatch, server) as (api, clients):

        async def refresh() -> None:
            await server.held.wait()
            server.token = "new-token"
            server.expired = True
            await api.refresh_credentials()
            closed_at_refresh.append(clients[0].closed)
            server.release.set()

        with anyio.fail_after(10):
            await tg_collect([lambda: _grok_batch_generate(api, "held"), refresh])
        assert server.keys_by_marker() == {"held": [["old-token", "new-token"]]}
        assert closed_at_refresh == [False]
        assert len(clients) == 2
        assert clients[0].closed
        assert not clients[1].closed
