import json
from collections.abc import Generator
from subprocess import Popen
from typing import cast
from unittest.mock import Mock

import anyio
import httpx
import httpx2
import pytest
from openai import AuthenticationError, DefaultAsyncHttpxClient

from inspect_ai import Task, eval
from inspect_ai._util._async import tg_collect
from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.dataset import Sample
from inspect_ai.hooks import ApiKeyOverride, Hooks, hooks
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelAPI,
    ModelOutput,
    get_model,
)
from inspect_ai.model._model_info import _get_model_info_direct
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.openrouter import OpenRouterAPI
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


@pytest.mark.parametrize("provider", [OpenAICompatibleAPI, OpenRouterAPI])
@pytest.mark.parametrize("parallel_status", [200, 500, 401])
async def test_refresh_preserves_concurrent_requests(
    monkeypatch: pytest.MonkeyPatch,
    provider: type[OpenAICompatibleAPI],
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

    async def respond(request: httpx2.Request) -> httpx2.Response:
        marker = json.loads(request.content)["messages"][0]["content"]
        seen[marker].append(request.headers["authorization"])
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
            json={
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
            },
        )

    http_client = DefaultAsyncHttpxClient(transport=httpx2.MockTransport(respond))
    api = provider(
        "test/model",
        api_key=token,
        base_url="https://example.com/v1",
        http_client=http_client,
        max_retries=1,
    )
    model = Model(api=api, config=GenerateConfig())
    client = api.client
    # Keep the pre-fix recreation path offline when checking the regression.
    monkeypatch.setattr(
        api,
        "_create_http_client",
        lambda: DefaultAsyncHttpxClient(transport=httpx2.MockTransport(respond)),
    )

    async def generate(marker: str) -> str | None:
        nonlocal token
        try:
            result = await client.chat.completions.create(
                model="test-model", messages=[{"role": "user", "content": marker}]
            )
        except AuthenticationError as ex:
            token = "new-token"
            await model.before_retry(ex)
            refreshed.set()
            result = await api.client.chat.completions.create(
                model="test-model", messages=[{"role": "user", "content": marker}]
            )
        return result.choices[0].message.content

    try:
        with anyio.fail_after(10):
            assert await tg_collect(
                [lambda: generate("auth"), lambda: generate("parallel")]
            ) == ["ok", "ok"]
        assert api.client is client
        assert api.http_client is http_client
        assert not http_client.is_closed
        assert seen["auth"] == ["Bearer old-token", "Bearer new-token"]
        assert seen["parallel"] == ["Bearer old-token"] + (
            ["Bearer new-token"] if parallel_status != 200 else []
        )
    finally:
        await api.aclose()
        await http_client.aclose()
    assert http_client.is_closed


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
