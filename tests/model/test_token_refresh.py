import os
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
        self.seen_values: list[str] = []

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        """Provide incrementing token values."""
        if data.env_var_name != "TEST_API_KEY":
            return None

        self.seen_values.append(data.value)
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


def test_explicit_empty_key_is_reoffered_on_refresh(
    monkeypatch: pytest.MonkeyPatch, mock_refresh_token_hook: MockRefreshTokenHook
):
    monkeypatch.delenv("TEST_API_KEY", raising=False)

    @modelapi(name="mockemptyexplicit")
    def mockemptyexplicit() -> type[ModelAPI]:
        return Mock401API

    try:
        model = get_model(
            "mockemptyexplicit/test",
            api_key="",
            memoize=False,
        )
        provider = model.api
        assert isinstance(provider, Mock401API)
        assert provider.api_key == "token-1"

        provider.initialize()

        assert provider.api_key == "token-2"
        assert mock_refresh_token_hook.seen_values == ["", ""]
    finally:
        del _registry["modelapi:mockemptyexplicit"]


class MockArnResolverHook(Hooks):
    """Resolves a secret-manager ARN to an incrementing real key.

    Unlike MockRefreshTokenHook, this hook's output *depends on its input* — it
    only resolves when handed the original ARN. It therefore breaks if the
    original value is clobbered by a previous resolution.
    """

    ARN = "arn:aws:secretsmanager:us-east-1:secret:openai"
    SECOND_ARN = "arn:aws:secretsmanager:us-east-1:secret:openai-staging"

    def __init__(self) -> None:
        self.call_count = 0
        self.seen_values: list[str] = []

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        if data.env_var_name != "TEST_API_KEY":
            return None
        self.seen_values.append(data.value)
        if data.value not in (self.ARN, self.SECOND_ARN):
            return None
        self.call_count += 1
        return f"resolved-key-{self.call_count}"


class MockEnvCopyAPI(Mock401API):
    """Provider that copies its resolved environment key into self.api_key."""

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
            config=config,
            **model_args,
        )
        if self.api_key is None:
            self.api_key = os.environ["TEST_API_KEY"]
        self.initialize()


class MockSubclassKeyAPI(Mock401API):
    """Extension-provider shape that assigns an API key after super init."""

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
            config=config,
            **model_args,
        )
        self.api_key = MockArnResolverHook.ARN
        self.initialize()


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


def test_env_override_updates_provider_copy_across_instances(
    monkeypatch: pytest.MonkeyPatch, mock_arn_resolver_hook: MockArnResolverHook
):
    """An older provider copy refreshes after a newer model rotates the env key."""
    monkeypatch.setenv("TEST_API_KEY", MockArnResolverHook.ARN)

    @modelapi(name="mockenvcopy")
    def mockenvcopy() -> type[ModelAPI]:
        return MockEnvCopyAPI

    try:
        model_a = get_model("mockenvcopy/test", memoize=False)
        provider_a = model_a.api
        assert isinstance(provider_a, MockEnvCopyAPI)
        assert provider_a.api_key == "resolved-key-2"

        model_b = get_model("mockenvcopy/test", memoize=False)
        provider_b = model_b.api
        assert isinstance(provider_b, MockEnvCopyAPI)
        assert provider_b.api_key == "resolved-key-4"

        # model_a still holds resolved-key-2 while the process environment and model_b
        # have advanced to resolved-key-4. It must still recover the ARN and update its
        # copied key on refresh.
        provider_a.initialize()

        assert provider_a.api_key == "resolved-key-5"
        assert os.environ["TEST_API_KEY"] == "resolved-key-5"
        assert mock_arn_resolver_hook.seen_values == [MockArnResolverHook.ARN] * 5
    finally:
        del _registry["modelapi:mockenvcopy"]


def test_subclass_assigned_api_key_retains_its_source(
    monkeypatch: pytest.MonkeyPatch, mock_arn_resolver_hook: MockArnResolverHook
):
    """A provider-assigned non-environment key re-resolves from its first value."""
    monkeypatch.delenv("TEST_API_KEY", raising=False)

    @modelapi(name="mocksubclasskey")
    def mocksubclasskey() -> type[ModelAPI]:
        return MockSubclassKeyAPI

    try:
        model = get_model("mocksubclasskey/test", memoize=False)
        provider = model.api
        assert isinstance(provider, MockSubclassKeyAPI)
        assert provider.api_key == "resolved-key-1"

        provider.initialize()

        assert provider.api_key == "resolved-key-2"
        assert mock_arn_resolver_hook.seen_values == [
            "",
            MockArnResolverHook.ARN,
            MockArnResolverHook.ARN,
        ]
    finally:
        del _registry["modelapi:mocksubclasskey"]


def test_env_override_adopts_external_environment_change(
    monkeypatch: pytest.MonkeyPatch, mock_arn_resolver_hook: MockArnResolverHook
):
    """A live value not written by Inspect becomes the new environment source."""
    from inspect_ai.model._model import _api_key_env_overrides

    monkeypatch.setenv("TEST_API_KEY", MockArnResolverHook.ARN)

    @modelapi(name="mockenvchange")
    def mockenvchange() -> type[ModelAPI]:
        return MockEnvCopyAPI

    try:
        model = get_model("mockenvchange/test", memoize=False)
        provider = model.api
        assert isinstance(provider, MockEnvCopyAPI)
        assert provider.api_key == "resolved-key-2"

        monkeypatch.setenv("TEST_API_KEY", MockArnResolverHook.SECOND_ARN)
        provider.initialize()

        assert mock_arn_resolver_hook.seen_values[-1] == MockArnResolverHook.SECOND_ARN
        assert provider.api_key == "resolved-key-3"
        assert _api_key_env_overrides["TEST_API_KEY"].source == (
            MockArnResolverHook.SECOND_ARN
        )

        # If the replacement is already a usable credential and the hook declines it,
        # use that live value directly and leave no stale source/current association.
        monkeypatch.setenv("TEST_API_KEY", "direct-api-key")
        provider.initialize()

        assert mock_arn_resolver_hook.seen_values[-1] == "direct-api-key"
        assert provider.api_key == "direct-api-key"
        assert "TEST_API_KEY" not in _api_key_env_overrides
    finally:
        del _registry["modelapi:mockenvchange"]


def test_env_override_state_is_bounded_by_environment_variables(
    monkeypatch: pytest.MonkeyPatch, mock_arn_resolver_hook: MockArnResolverHook
):
    """Repeated refreshes replace one env-var state entry rather than accumulating."""
    from inspect_ai.model._model import _api_key_env_overrides

    monkeypatch.setenv("TEST_API_KEY", MockArnResolverHook.ARN)

    @modelapi(name="mockbounded")
    def mockbounded() -> type[ModelAPI]:
        return Mock401API

    try:
        model = get_model("mockbounded/test", memoize=False)
        provider = model.api
        assert isinstance(provider, Mock401API)

        for _ in range(50):
            provider.initialize()

        assert list(_api_key_env_overrides) == ["TEST_API_KEY"]
        state = _api_key_env_overrides["TEST_API_KEY"]
        assert state.source == MockArnResolverHook.ARN
        assert state.current == "resolved-key-51"
    finally:
        del _registry["modelapi:mockbounded"]


def test_explicit_key_override_reresolves_from_original_arn(
    monkeypatch: pytest.MonkeyPatch, mock_arn_resolver_hook: MockArnResolverHook
):
    """An explicitly-supplied api key re-resolves from the original value.

    The same re-resolution guarantee as the env-var path, but for the
    `api_key=` argument: re-initialization must re-offer the original ARN to the
    hook, not the resolved key we previously wrote into self.api_key.
    """
    # ensure the explicit key is the only source (nothing in the environment)
    monkeypatch.delenv("TEST_API_KEY", raising=False)

    @modelapi(name="mockarnexplicit")
    def mockarnexplicit() -> type[ModelAPI]:
        return Mock401API

    try:
        # initial construction resolves the explicitly-supplied ARN
        model = get_model(
            "mockarnexplicit/test",
            api_key=MockArnResolverHook.ARN,
            memoize=False,
        )
        provider = model.api
        assert isinstance(provider, Mock401API)
        assert provider.api_key == "resolved-key-1"

        # re-initialization (as happens on a 401) must hand the hook the ARN
        # again — not the resolved key now sitting in self.api_key
        provider.initialize()
        assert provider.api_key == "resolved-key-2"

        # a later, separately-constructed model also re-resolves the ARN
        model2 = get_model(
            "mockarnexplicit/test",
            api_key=MockArnResolverHook.ARN,
            memoize=False,
        )
        assert model2.api.api_key == "resolved-key-3"
        assert model2.api is not provider

        # the hook only ever saw the original ARN, never a resolved key
        assert set(mock_arn_resolver_hook.seen_values) == {MockArnResolverHook.ARN}
        assert mock_arn_resolver_hook.call_count == 3
    finally:
        # Remove the model provider from the registry to avoid conflicts in other tests.
        del _registry["modelapi:mockarnexplicit"]


class MockOwnSourceHook(Hooks):
    """Supplies credentials from its own source (e.g. OAuth/vault).

    Returns an incrementing token regardless of input, so it can provide a key
    even when none exists in the environment at all.
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.seen_values: list[str] = []

    def override_api_key(self, data: ApiKeyOverride) -> str | None:
        if data.env_var_name != "TEST_API_KEY":
            return None
        self.seen_values.append(data.value)
        self.call_count += 1
        return f"own-source-token-{self.call_count}"


@pytest.fixture
def mock_own_source_hook() -> Generator[MockOwnSourceHook, None, None]:
    @hooks("test_own_source", description="Test own-source credential hook")
    def get_hook() -> type[MockOwnSourceHook]:
        return MockOwnSourceHook

    hook = registry_lookup("hooks", "test_own_source")
    assert isinstance(hook, MockOwnSourceHook)
    try:
        yield hook
    finally:
        # Remove the hook from the registry to avoid conflicts in other tests.
        del _registry["hooks:test_own_source"]


def test_override_supplies_credentials_when_no_env_key(
    monkeypatch: pytest.MonkeyPatch, mock_own_source_hook: MockOwnSourceHook
):
    """A registered hook supplies credentials with no env key.

    The hook is invoked even when no api key exists in the environment, and its
    credential is refreshed on re-initialization.
    """
    # ensure there is no api key anywhere in the environment
    monkeypatch.delenv("TEST_API_KEY", raising=False)

    @modelapi(name="mockownsource")
    def mockownsource() -> type[ModelAPI]:
        return Mock401API

    try:
        # there is no env value to resolve, so the hook is invoked with an empty
        # string and supplies the credential from its own source
        model = get_model("mockownsource/test", memoize=False)
        provider = model.api
        assert isinstance(provider, Mock401API)
        assert provider.api_key == "own-source-token-1"
        assert mock_own_source_hook.seen_values == [""]
        # nothing is written back to the environment in this branch
        assert "TEST_API_KEY" not in os.environ

        # re-initialization (as happens on a 401) refreshes the credential
        provider.initialize()
        assert provider.api_key == "own-source-token-2"
        assert mock_own_source_hook.seen_values == ["", ""]
    finally:
        # Remove the model provider from the registry to avoid conflicts in other tests.
        del _registry["modelapi:mockownsource"]
