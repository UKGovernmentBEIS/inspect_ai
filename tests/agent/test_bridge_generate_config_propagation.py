"""The eval's GenerateConfig must reach the provider for bridged agents.

A bridged client may send the eval model's concrete id instead of asking for
"inspect" (claude_code sends e.g. "claude-fable-5"). That resolved to a separate
Model instance via get_model() -- whose memoization key includes the config JSON --
and resolve_generate_config() only applies the eval's GenerateConfig to the active
model, so eval-level options were silently dropped before the provider request.

resolve_inspect_model() now returns the active Model instance when the client names
it. These tests pin both halves: the eval's config reaches such a client, and the
paths that must NOT be redirected (aliases, model roles, other models) still aren't.
"""

import pytest

from inspect_ai.agent._bridge.util import (
    resolve_generate_config,
    resolve_inspect_model,
)
from inspect_ai.model._generate_config import (
    GenerateConfig,
    active_generate_config_context_var,
)
from inspect_ai.model._model import (
    Model,
    active_model_context_var,
    get_model,
    init_active_model,
    init_model_roles,
)

EVAL_CONFIG = GenerateConfig(fallback_models=["mockllm/fallback"])


@pytest.fixture(autouse=True)
def _isolate_active_model():
    """init_active_model() sets process-wide contextvars; don't leak them.

    get_model() with no arguments resolves the active model, so leaking it breaks
    unrelated tests (e.g. test_resolve_inspect_model_bare_inspect). Same token
    set/reset idiom as tests/_control/conftest.py.
    """
    model_token = active_model_context_var.set(active_model_context_var.get(None))
    config_token = active_generate_config_context_var.set(
        active_generate_config_context_var.get()
    )
    try:
        yield
    finally:
        active_model_context_var.reset(model_token)
        active_generate_config_context_var.reset(config_token)
        init_model_roles({})


def _make_active() -> Model:
    active = get_model("mockllm/model", config=EVAL_CONFIG)
    init_active_model(active, EVAL_CONFIG)
    return active


def test_client_naming_eval_model_gets_the_active_instance() -> None:
    """The regression: naming the model must not fork a second instance."""
    active = _make_active()
    assert resolve_inspect_model("mockllm/model") is active


def test_client_naming_eval_model_bare_gets_the_active_instance() -> None:
    """Bare id (no provider prefix), which is what an Anthropic client sends."""
    active = _make_active()
    assert resolve_inspect_model("model") is active


def test_eval_config_reaches_provider_for_named_eval_model() -> None:
    """End of the chain: the eval's config now survives to the provider config."""
    _make_active()
    model = resolve_inspect_model("mockllm/model")
    config = resolve_generate_config(model, GenerateConfig())
    assert config.fallback_models == ["mockllm/fallback"]


def test_inspect_keyword_still_resolves_to_active_model() -> None:
    """Pre-existing path must be unchanged."""
    active = _make_active()
    assert resolve_inspect_model("inspect") is active


def test_model_role_is_not_redirected_to_the_eval_model() -> None:
    """A role must keep its own model even when the eval model shares the name."""
    _make_active()
    role_model = get_model("mockllm/model", config=GenerateConfig(max_tokens=7))
    init_model_roles({"grader": role_model})

    resolved = resolve_inspect_model("grader")
    assert resolved is role_model

    # and it must not inherit the eval's config
    config = resolve_generate_config(resolved, GenerateConfig())
    assert config.fallback_models is None
    assert config.max_tokens == 7


def test_alias_is_not_redirected_to_the_eval_model() -> None:
    """An explicit alias target wins over the active model."""
    _make_active()
    target = get_model("mockllm/alias-target")
    resolved = resolve_inspect_model("my-alias", model_aliases={"my-alias": target})
    assert resolved is target

    config = resolve_generate_config(resolved, GenerateConfig())
    assert config.fallback_models is None


def test_other_model_does_not_get_the_eval_config() -> None:
    """A genuinely different model the client asked for stays independent."""
    active = _make_active()
    other = resolve_inspect_model("mockllm/some-other-model")
    assert other is not active

    config = resolve_generate_config(other, GenerateConfig())
    assert config.fallback_models is None


def test_no_active_model_is_harmless() -> None:
    """With no eval running, resolution is unchanged."""
    active_model_context_var.set(None)
    model = resolve_inspect_model("mockllm/model")
    assert str(model) == "mockllm/model"


def test_model_instance_config_beats_bridge_default() -> None:
    """Unchanged precedence: config on the Model instance wins over the bridge's."""
    model = get_model("mockllm/model", config=GenerateConfig(max_tokens=100))
    config = resolve_generate_config(model, GenerateConfig(max_tokens=50))
    assert config.max_tokens == 100
