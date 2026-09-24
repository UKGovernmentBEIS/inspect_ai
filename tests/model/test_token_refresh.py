import json
from collections.abc import Generator

import anyio
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
    GenerateConfig,
    Model,
    ModelAPI,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.openrouter import OpenRouterAPI
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
