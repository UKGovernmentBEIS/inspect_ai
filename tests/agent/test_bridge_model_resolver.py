from __future__ import annotations

from typing import NamedTuple

from inspect_ai.agent._bridge.util import resolve_inspect_model
from inspect_ai.model import Model, ModelResolver, get_model


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
