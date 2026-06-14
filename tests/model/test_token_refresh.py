from collections.abc import Generator

import pytest

from inspect_ai import Task, eval
from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.dataset import Sample
from inspect_ai.hooks import ApiKeyOverride, ApiKeyOverrideResult, Hooks, hooks
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    get_model,
)
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

    def connection_key(self) -> str:
        return f"{self.account_id or self.api_key}:{self.model_name}"


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


class MockAccountIdHook(Hooks):
    def __init__(self) -> None:
        self.call_count = 0

    def override_api_key(self, data: ApiKeyOverride) -> ApiKeyOverrideResult | None:
        if data.env_var_name != "TEST_API_KEY":
            return None
        self.call_count += 1
        return ApiKeyOverrideResult(
            value=f"token-{self.call_count}", account_id="account-a"
        )


@pytest.fixture
def mock_account_id_hook() -> Generator[MockAccountIdHook, None, None]:
    @hooks("test_account_id", description="Account-id override hook")
    def get_hook() -> type[MockAccountIdHook]:
        return MockAccountIdHook

    hook = registry_lookup("hooks", "test_account_id")
    assert isinstance(hook, MockAccountIdHook)
    try:
        yield hook
    finally:
        del _registry["hooks:test_account_id"]


def test_account_id_scopes_connection_key(
    mock_account_id_hook: MockAccountIdHook,
) -> None:
    """connection_key is stable across instances and refreshes given an account_id."""

    @modelapi(name="mock401_account")
    def mock401() -> type[ModelAPI]:
        return Mock401API

    try:
        a = get_model("mock401_account/test", api_key="seed", fail_count=2)
        a_key_before = a.api.connection_key()
        b = get_model("mock401_account/test", api_key="seed", memoize=False)

        assert a.api.api_key == "token-1"
        assert b.api.api_key == "token-2"
        assert a.api.connection_key() == b.api.connection_key() == "account-a:test"

        log = eval(Task(dataset=[Sample(input="t", target="t")]), model=a)[0]
        assert log.status == "success"
        assert a.api.api_key == "token-4"
        assert a.api.connection_key() == a_key_before
    finally:
        del _registry["modelapi:mock401_account"]
