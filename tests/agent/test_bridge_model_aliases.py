"""Tests for model_aliases in resolve_inspect_model."""

import pytest

from inspect_ai.agent._bridge.util import resolve_inspect_model
from inspect_ai.model._model import Model, get_model


def test_resolve_inspect_model_bare_inspect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSPECT_EVAL_MODEL", "mockllm/default")
    model = resolve_inspect_model("inspect")
    assert str(model) == "mockllm/default"


def test_resolve_inspect_model_prefixed() -> None:
    model = resolve_inspect_model("inspect/mockllm/model")
    assert str(model) == "mockllm/model"


def test_resolve_inspect_model_alias_takes_priority() -> None:
    target = get_model("mockllm/alias-target")
    aliases: dict[str, str | Model] = {"my-alias": target}
    result = resolve_inspect_model("my-alias", model_aliases=aliases)
    assert result is target


def test_resolve_inspect_model_alias_string() -> None:
    aliases: dict[str, str | Model] = {"my-alias": "mockllm/alias-target"}
    result = resolve_inspect_model("my-alias", model_aliases=aliases)
    assert str(result) == "mockllm/alias-target"


def test_resolve_inspect_model_fallback_used_for_non_inspect() -> None:
    result = resolve_inspect_model(
        "some-random-model", fallback_model="inspect/mockllm/fallback"
    )
    assert str(result) == "mockllm/fallback"


def test_resolve_inspect_model_alias_over_fallback() -> None:
    """Aliases are checked before fallback."""
    target = get_model("mockllm/alias-target")
    aliases: dict[str, str | Model] = {"my-name": target}
    result = resolve_inspect_model(
        "my-name", model_aliases=aliases, fallback_model="inspect/mockllm/other"
    )
    assert result is target


def test_resolve_inspect_model_resolver_routes_request() -> None:
    """A model_resolver routes the requested name (checked after aliases)."""
    target = get_model("mockllm/resolver-target")
    result = resolve_inspect_model(
        "anything-at-all", model_resolver=lambda name: target
    )
    assert result is target


def test_resolve_inspect_model_resolver_string_spec() -> None:
    result = resolve_inspect_model(
        "foo", model_resolver=lambda name: "mockllm/spec-target"
    )
    assert str(result) == "mockllm/spec-target"


def test_resolve_inspect_model_resolver_none_defers_to_fallback() -> None:
    """Returning None from the resolver defers to the static fallback."""
    result = resolve_inspect_model(
        "gpt-4o",
        fallback_model="inspect/mockllm/fallback",
        model_resolver=lambda name: None,
    )
    assert str(result) == "mockllm/fallback"


def test_resolve_inspect_model_alias_over_resolver() -> None:
    """Aliases are checked before the resolver."""
    target = get_model("mockllm/alias-target")

    def resolver(name: str) -> Model:
        raise AssertionError("resolver must not run when an alias matches")

    result = resolve_inspect_model(
        "my-name", model_aliases={"my-name": target}, model_resolver=resolver
    )
    assert result is target


def test_sandbox_agent_bridge_threads_model_resolver() -> None:
    """model_resolver must reach the constructed bridge.

    (sandbox_agent_bridge -> SandboxAgentBridge -> AgentBridge).
    """
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

    def resolver(name: str) -> Model:
        return get_model("mockllm/model")

    bridge = SandboxAgentBridge(
        AgentState(messages=[]),
        None,  # filter
        None,  # retry_refusals
        None,  # compaction
        13131,  # port
        None,  # model (fallback)
        model_resolver=resolver,
    )
    assert bridge.model_resolver is resolver
