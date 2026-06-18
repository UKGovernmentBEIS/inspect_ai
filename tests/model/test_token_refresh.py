from collections.abc import Generator

import pytest

from inspect_ai import Task, eval
from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.dataset import Sample
from inspect_ai.hooks import ApiKeyOverride, Hooks, hooks
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


class MockArnResolverHook(Hooks):
    """Resolves a secret-manager ARN to an incrementing real key.

    Unlike MockRefreshTokenHook, this hook's output *depends on its input* — it
    only resolves when handed the original ARN. It therefore breaks if the
    original value is clobbered by a previous resolution.
    """

    ARN = "arn:aws:secretsmanager:us-east-1:secret:openai"

    def __init__(self) -> None:
        self.call_count = 0
        self.seen_values: list[str] = []

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        if data.env_var_name != "TEST_API_KEY":
            return None
        self.seen_values.append(data.value)
        if data.value != self.ARN:
            return None
        self.call_count += 1
        return f"resolved-key-{self.call_count}"


@pytest.fixture
def mock_arn_resolver_hook() -> Generator[MockArnResolverHook, None, None]:
    @hooks("test_arn_resolver", description="Test ARN resolver hook")
    def get_hook() -> type[MockArnResolverHook]:
        return MockArnResolverHook

    hook = registry_lookup("hooks", "test_arn_resolver")
    assert isinstance(hook, MockArnResolverHook)
    try:
        yield hook
    finally:
        # Remove the hook from the registry to avoid conflicts in other tests.
        del _registry["hooks:test_arn_resolver"]


def test_env_override_reresolves_from_original_arn(
    monkeypatch: pytest.MonkeyPatch, mock_arn_resolver_hook: MockArnResolverHook
):
    """Env-var overrides re-resolve from the original value.

    They must not re-resolve from the previously-resolved key written back
    into os.environ.
    """
    import os

    monkeypatch.setenv("TEST_API_KEY", MockArnResolverHook.ARN)

    @modelapi(name="mockarn")
    def mockarn() -> type[ModelAPI]:
        return Mock401API

    try:
        # initial construction resolves the ARN and writes the resolved key
        # back to os.environ for downstream SDKs
        model = get_model("mockarn/test", memoize=False)
        provider = model.api
        assert isinstance(provider, Mock401API)
        assert provider.api_key is None  # env-var path leaves api_key unset
        assert os.environ["TEST_API_KEY"] == "resolved-key-1"

        # re-initialization (as happens on a 401) must hand the hook the ARN
        # again — not the already-resolved key now sitting in os.environ
        provider.initialize()
        assert os.environ["TEST_API_KEY"] == "resolved-key-2"

        # a later, separately-constructed model must also re-resolve the ARN
        model2 = get_model("mockarn/test", memoize=False)
        assert os.environ["TEST_API_KEY"] == "resolved-key-3"
        assert model2.api is not provider

        # the hook only ever saw the original ARN, never a resolved key
        assert set(mock_arn_resolver_hook.seen_values) == {MockArnResolverHook.ARN}
        assert mock_arn_resolver_hook.call_count == 3
    finally:
        # Remove the model provider from the registry to avoid conflicts in other tests.
        del _registry["modelapi:mockarn"]
