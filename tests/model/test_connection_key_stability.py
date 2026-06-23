"""Tests for connection-pool key stability across api_key rotation.

The connection semaphore / adaptive concurrency controller are keyed by
`ModelAPI.connection_key()`. Providers scope that key by api_key so distinct
accounts get distinct pools. For long-running evals an api_key can be rotated
mid-run (e.g. a hook refreshing an OAuth token, triggered by `initialize()` on
an auth failure). Scoping the pool by the *live* `self.api_key` would discard
all learned pool/adaptive state on every rotation. Providers therefore scope by
`self.initial_api_key` — the constructor-provided value, captured once and never
mutated by `initialize()`.
"""

import pytest

from inspect_ai.model import ModelAPI, ModelOutput
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.tool import ToolChoice, ToolInfo

STUB_API_KEY = "STUB_API_KEY"


class _StubAPI(ModelAPI):
    """Minimal provider that scopes the pool by initial_api_key, as real ones do."""

    def __init__(self, model_name: str, api_key: str | None = None) -> None:
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            api_key_vars=[STUB_API_KEY],
            config=GenerateConfig(),
        )

    async def generate(
        self,
        input: list,
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        return ModelOutput.from_content(self.model_name, "ok")

    def connection_key(self) -> str:
        return f"{self.initial_api_key}:{self.model_name}"


def _install_rotating_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every override_api_key() call return a fresh, distinct token.

    Simulates a credential hook that hands out a new value each time it is
    consulted (the worst case for pool-key stability).
    """
    counter = {"n": 0}

    def rotate(var: str, value: str) -> str:
        counter["n"] += 1
        return f"rotated-token-{counter['n']}"

    # `override_api_key()` falls back to this legacy global when no Hooks
    # subclass implements override_api_key(), which is the case under test.
    monkeypatch.setattr(
        "inspect_ai.hooks._legacy._override_api_key", rotate, raising=False
    )


def test_initial_api_key_captured_from_constructor() -> None:
    api = _StubAPI("m1", api_key="explicit-key")
    assert api.initial_api_key == "explicit-key"


def test_initial_api_key_unaffected_by_construction_time_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even though the override fires during __init__ and mutates self.api_key,
    # initial_api_key reflects the value the caller passed in.
    _install_rotating_override(monkeypatch)
    api = _StubAPI("m1", api_key="explicit-key")
    assert api.initial_api_key == "explicit-key"
    assert api.api_key != "explicit-key"  # override applied to the live key


def test_connection_key_stable_across_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_rotating_override(monkeypatch)
    api = _StubAPI("m1", api_key="explicit-key")

    key_before = api.connection_key()
    live_before = api.api_key

    # initialize() re-applies overrides — the live key rotates again...
    api.initialize()

    assert api.api_key != live_before, "precondition: the live key must rotate"
    assert api.connection_key() == key_before, (
        "connection_key must not move when the live api_key rotates"
    )
    assert key_before == "explicit-key:m1"


def test_same_explicit_key_shares_pool_across_instances() -> None:
    a = _StubAPI("m1", api_key="shared-key")
    b = _StubAPI("m1", api_key="shared-key")
    assert a.connection_key() == b.connection_key()


def test_distinct_explicit_keys_get_distinct_pools() -> None:
    a = _StubAPI("m1", api_key="key-a")
    b = _StubAPI("m1", api_key="key-b")
    assert a.connection_key() != b.connection_key()


def test_env_var_keys_collapse_to_shared_pool_per_model() -> None:
    # No explicit api_key => initial_api_key is None for everyone. Per the
    # design decision, env-var-sourced keys are assumed shared process-wide, so
    # all instances of a given model share one pool (scoped only by model name).
    a = _StubAPI("m1")
    b = _StubAPI("m1")
    c = _StubAPI("m2")
    assert a.initial_api_key is None
    assert a.connection_key() == b.connection_key()
    assert a.connection_key() != c.connection_key()
