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
