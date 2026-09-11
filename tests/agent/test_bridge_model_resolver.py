from __future__ import annotations

from typing import NamedTuple

import pytest

from inspect_ai.agent._bridge.util import resolve_inspect_model
from inspect_ai.model import Model, ModelResolver, get_model
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    active_model_context_var,
    init_active_model,
    init_model_roles,
)


class _CapturingResolver(NamedTuple):
    seen: list[str]
    resolver: ModelResolver


def _capturing_resolver() -> _CapturingResolver:
    seen: list[str] = []

    def resolver(model_name: str) -> Model:
        seen.append(model_name)
        return get_model("mockllm/model")

    return _CapturingResolver(seen=seen, resolver=resolver)


def test_bare_name_qualified_by_provider_before_resolver() -> None:
    # A bare name on a provider-specific endpoint is qualified before the resolver sees it.
    seen, resolver = _capturing_resolver()
    resolve_inspect_model("gpt-5.1", model_resolver=resolver, provider="openai")
    assert seen == ["openai/gpt-5.1"]


def test_already_qualified_name_left_untouched() -> None:
    # A name that already contains a provider prefix is not double-qualified.
    seen, resolver = _capturing_resolver()
    resolve_inspect_model("openai/gpt-5.1", model_resolver=resolver, provider="openai")
    assert seen == ["openai/gpt-5.1"]


def test_no_provider_leaves_bare_name() -> None:
    # Default provider="" is a no-op: the resolver still receives the raw bare name.
    seen, resolver = _capturing_resolver()
    resolve_inspect_model("gpt-5.1", model_resolver=resolver)
    assert seen == ["gpt-5.1"]


def test_alias_wins_before_provider_qualification() -> None:
    # An explicit alias short-circuits before both qualification and the resolver.
    seen, resolver = _capturing_resolver()
    result = resolve_inspect_model(
        "gpt-5.1",
        model_aliases={"gpt-5.1": "mockllm/model"},
        model_resolver=resolver,
        provider="openai",
    )
    assert seen == []
    assert isinstance(result, Model)


@pytest.fixture(autouse=True)
def _isolate_active_model():
    """``init_active_model()`` sets a process-wide contextvar; don't leak it.

    Same idiom as ``tests/agent/test_bridge_generate_config_propagation.py``.
    """
    token = active_model_context_var.set(active_model_context_var.get(None))
    try:
        yield
    finally:
        active_model_context_var.reset(token)
        init_model_roles({})


def _make_active(spec: str) -> Model:
    active = get_model(spec)
    init_active_model(active, GenerateConfig())
    return active


def test_no_resolver_no_fallback_resolves_via_get_model_with_provider() -> None:
    # The headline no-resolver behavior dragonstyle flagged as untested (#4897
    # review): bare name + provider endpoint + no resolver + no fallback resolves
    # via get_model() using the provider-qualified name.
    result = resolve_inspect_model("model", provider="mockllm")
    assert str(result) == "mockllm/model"


def test_bare_name_matches_active_model_under_different_provider() -> None:
    """Regression vs #4706 (e9add1d85318): qualification must not defeat the active-model match.

    Also answers direction 2 of the fallback/active-model precedence question
    below: with no fallback configured, the active-model match applies.

    Eval's active model is on a different provider than the bridge endpoint (e.g.
    ``azureai/gpt-4o`` while the client hits the openai-compatible endpoint and
    sends the bare name ``gpt-4o``). Provider qualification alone would widen that
    to ``openai/gpt-4o``, which no longer matches ``azureai/gpt-4o`` or its short
    name -- so resolve_inspect_model must also compare the pre-qualification raw
    name against the active model's short name.
    """
    active = _make_active("mockllm/gpt-4o")
    assert resolve_inspect_model("gpt-4o", provider="azureai") is active


def test_fallback_model_wins_over_active_model_raw_name_match() -> None:
    """An explicitly configured fallback must not be silently shadowed.

    Direction 1 of the open question: a bare name that happens to match the
    active model's short name must NOT override an explicitly configured
    ``fallback_model`` -- the operator's explicit fallback wins.
    """
    _make_active("mockllm/gpt-4o")
    result = resolve_inspect_model(
        "gpt-4o", fallback_model="mockllm/other", provider="azureai"
    )
    assert str(result) == "mockllm/other"
