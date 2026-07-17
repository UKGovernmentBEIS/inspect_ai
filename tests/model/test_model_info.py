"""Tests for model_info lookup functionality."""

from typing import Any

import pytest

from inspect_ai.model import (
    ModelAPI,
    ModelInfo,
    get_model,
    get_model_info,
    set_model_info,
)
from inspect_ai.model._model_data.model_data import ModelCost
from inspect_ai.model._model_info import (
    _get_model_info_direct,
    clear_model_info_cache,
    get_model_input_tokens,
    set_model_cost,
)
from inspect_ai.model._registry import modelapi


class _TestModelAPI(ModelAPI):
    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@modelapi("noload")
def noload() -> type[ModelAPI]:
    """A registered provider whose constructor loads nothing (no weights)."""

    class NoLoadModelAPI(ModelAPI):
        async def generate(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    return NoLoadModelAPI


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the model info cache before each test."""
    clear_model_info_cache()
    yield
    clear_model_info_cache()


class TestGetModelInfo:
    """Tests for get_model_info function."""

    def test_known_anthropic_model(self):
        """Test lookup of a known Anthropic model."""
        info = get_model_info("anthropic/claude-sonnet-4")
        assert info is not None
        assert info.context_length is not None
        assert info.context_length > 0
        assert info.organization == "Anthropic"

    def test_known_openai_model(self):
        """Test lookup of a known OpenAI model."""
        info = get_model_info("openai/gpt-4o")
        assert info is not None
        assert info.context_length is not None
        assert info.organization == "OpenAI"

    def test_known_kimi_model(self):
        """Test lookup of a known Moonshot AI Kimi model."""
        info = get_model_info("moonshotai/kimi-k3")
        assert info is not None
        assert info.organization == "Moonshot AI"
        assert info.context_length == 1048576
        assert info.output_tokens == 1048576
        assert info.reasoning is True
        assert info.reasoning_effort_default == "max"

    def test_kimi_via_moonshot_provider(self):
        """Test lookup via the moonshot provider prefix."""
        info = get_model_info("moonshot/kimi-k3")
        assert info is not None
        assert info.organization == "Moonshot AI"
        assert info.context_length == 1048576

    def test_kimi_org_detection_on_hosting_provider(self):
        """Test kimi-* org detection for hosting providers (e.g. azureai)."""
        info = get_model_info("azureai/kimi-k3")
        assert info is not None
        assert info.organization == "Moonshot AI"
        assert info.context_length == 1048576

    def test_unknown_model_returns_none(self):
        """Test that unknown models return None."""
        info = get_model_info("unknown-provider/unknown-model-xyz")
        assert info is None

    def test_set_model_info_family(self):
        """Test that set_model_info with family is retrievable."""
        set_model_info("custom/aliased-model", ModelInfo(family="gpt-5"))
        info = get_model_info("custom/aliased-model")
        assert info is not None
        assert info.family == "gpt-5"

    def test_model_family_does_not_instantiate_provider(self, monkeypatch):
        """Unknown model-family lookups must not recursively resolve a provider."""

        def fail_provider_resolution(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("model_family() attempted provider resolution")

        monkeypatch.setattr(
            "inspect_ai.model._model.get_model", fail_provider_resolution
        )
        api = _TestModelAPI("unknown-provider/custom-alias")
        assert api.model_family() == "unknown-provider/custom-alias"

    def test_direct_lookup_does_not_poison_provider_resolved_lookup(self, monkeypatch):
        """A direct miss must not prevent normal lookup from resolving a provider."""

        class _ResolvedModel:
            def canonical_name(self) -> str:
                return "resolved-provider/resolved-model"

        resolved_info = ModelInfo(family="resolved-family")
        set_model_info("resolved-provider/resolved-model", resolved_info)
        monkeypatch.setattr(
            "inspect_ai.model._model.get_model",
            lambda *args, **kwargs: _ResolvedModel(),
        )

        assert _get_model_info_direct("unknown-provider/nonmatching-alias") is None
        assert get_model_info("unknown-provider/nonmatching-alias") is resolved_info

    def test_case_insensitive_lookup(self):
        """Test that model name lookups are case-insensitive.

        Note: Provider names (e.g., 'anthropic') are case-sensitive as they
        must match the registered provider. The case-insensitive matching
        applies to the model name portion.
        """
        # Get with correct case
        info_correct = get_model_info("anthropic/claude-sonnet-4")
        assert info_correct is not None

        # Get with different case in model name (provider must be lowercase)
        info_upper = get_model_info("anthropic/Claude-Sonnet-4")
        assert info_upper is not None
        assert info_upper.context_length == info_correct.context_length

        # Mixed case in model name
        info_mixed = get_model_info("anthropic/CLAUDE-SONNET-4")
        assert info_mixed is not None
        assert info_mixed.context_length == info_correct.context_length

    def test_claude_opus_4_6_context_length(self):
        """Test that Claude Opus 4.6 has 1MM context window."""
        info = get_model_info("anthropic/claude-opus-4-6")
        assert info is not None
        assert info.context_length == 1_000_000

    def test_claude_sonnet_4_6_context_length(self):
        """Test that Claude Sonnet 4.6 has 1MM context window."""
        info = get_model_info("anthropic/claude-sonnet-4-6")
        assert info is not None
        assert info.context_length == 1_000_000

    def test_underscore_hyphen_normalization(self):
        """Test that underscores and hyphens are treated equivalently."""
        # Look up with hyphen
        info_hyphen = get_model_info("anthropic/claude-sonnet-4")
        assert info_hyphen is not None

        # Look up with underscore
        info_underscore = get_model_info("anthropic/claude_sonnet_4")
        assert info_underscore is not None
        assert info_underscore.context_length == info_hyphen.context_length


class TestSetModelInfo:
    """Tests for set_model_info function."""

    def test_set_custom_model(self):
        """Test setting custom model info.

        Note: The key should be in canonical form (org/model) as it will be
        looked up after resolving the model's canonical name.
        """
        custom_info = ModelInfo(
            context_length=64000,
            output_tokens=8192,
            organization="Custom Org",
            model="Custom Model",
        )
        # Register with canonical name format (org/model)
        set_model_info("meta-llama/custom-model", custom_info)

        # Look up via Together (which will resolve to canonical name)
        info = get_model_info("together/meta-llama/custom-model")
        assert info is not None
        assert info.context_length == 64000
        assert info.output_tokens == 8192
        assert info.organization == "Custom Org"
        assert info.model == "Custom Model"

    def test_custom_overrides_builtin(self):
        """Test that custom model info overrides built-in info."""
        # First verify the built-in value
        builtin_info = get_model_info("anthropic/claude-sonnet-4")
        assert builtin_info is not None
        original_context = builtin_info.context_length

        # Override with custom info
        set_model_info(
            "anthropic/claude-sonnet-4",
            ModelInfo(context_length=999999),
        )

        # Custom should take precedence
        info = get_model_info("anthropic/claude-sonnet-4")
        assert info is not None
        assert info.context_length == 999999
        assert info.context_length != original_context

    def test_set_minimal_model_info(self):
        """Test setting model info with only context_length."""
        # Register with canonical name format (use a HuggingFace-style name)
        set_model_info("test-org/minimal-model", ModelInfo(context_length=16000))

        # Look up via Together (which will resolve to canonical name)
        info = get_model_info("together/test-org/minimal-model")
        assert info is not None
        assert info.context_length == 16000
        assert info.organization is None
        assert info.model is None


class TestModelInfoFields:
    """Tests for ModelInfo field access."""

    def test_context_length_is_numeric(self):
        """Test that context_length values are numeric."""
        info = get_model_info("anthropic/claude-sonnet-4")
        assert info is not None
        assert isinstance(info.context_length, (int, float))

    def test_all_known_providers_have_context_length(self):
        """Test that major providers have context_length set."""
        test_models = [
            "anthropic/claude-sonnet-4",
            "openai/gpt-4o",
            "openai/gpt-5.3-chat",
            "openai/gpt-5.4-mini",
            "openai/gpt-5.4-nano",
            "google/gemini-2.5-flash-preview-05-20",
            "google/gemini-2.5-flash-lite",
            "google/gemini-3-flash-preview",
            "google/gemini-3.1-flash-image-preview",
            "google/gemini-3.1-flash-lite",
        ]

        for model in test_models:
            info = get_model_info(model)
            if info is not None:  # Model may not exist in database
                assert info.context_length is not None, f"{model} has no context_length"
                assert info.context_length > 0, f"{model} has invalid context_length"


class TestGetModelInputTokens:
    """Tests for get_model_input_tokens function."""

    def test_claude_sonnet_4_6(self):
        """Test that Claude Sonnet 4.6 reports 1MM input tokens."""
        model = get_model("anthropic/claude-sonnet-4-6")
        tokens = get_model_input_tokens(model)
        assert tokens == 1_000_000

    def test_claude_opus_4_6(self):
        """Test that Claude Opus 4.6 reports 1MM input tokens."""
        model = get_model("anthropic/claude-opus-4-6")
        tokens = get_model_input_tokens(model)
        assert tokens == 1_000_000

    def test_claude_fable_5(self):
        """Test that Claude Fable 5 reports 1MM input tokens."""
        model = get_model("anthropic/claude-fable-5")
        tokens = get_model_input_tokens(model)
        assert tokens == 1_000_000

    def test_claude_mythos_5(self):
        """Test that Claude Mythos 5 reports 1MM input tokens."""
        model = get_model("anthropic/claude-mythos-5")
        tokens = get_model_input_tokens(model)
        assert tokens == 1_000_000

    def test_claude_latest_defaults_to_1m(self):
        """An unknown/future Claude model (is_claude_latest) assumes the 1M frontier."""
        # Use a hypothetical future model name that triggers is_claude_latest()
        model = get_model("anthropic/claude-sonnet-4-9")
        tokens = get_model_input_tokens(model)
        assert tokens == 1_000_000

    def test_unregistered_claude_5_defaults_to_1m(self):
        """Unregistered Claude 5 variants assume the 1M frontier.

        Claude 5 detection matches any ``claude-*-5``, so a tier-named
        ``claude-opus-5-0`` or a new codename ``claude-saga-5`` is classified as
        Claude 5 (is_claude_5) even though it is not in the database. The
        input_tokens_name() fallback must still resolve such names to 1M rather
        than missing the database lookup entirely.
        """
        for model_name in (
            "anthropic/claude-opus-5-0",
            "anthropic/claude-sonnet-5-0",
            "anthropic/claude-saga-5",
        ):
            model = get_model(model_name)
            tokens = get_model_input_tokens(model)
            assert tokens == 1_000_000, model_name

    def test_claude_latest_with_1m_beta(self):
        """Test that a future Claude model with 1M beta maps to opus-4-6 (1MM)."""
        model = get_model(
            "anthropic/claude-sonnet-4-9",
            betas=["context-1m-2025-08-07"],
        )
        tokens = get_model_input_tokens(model)
        assert tokens == 1_000_000

    def test_openai_codename_maps_to_gpt_5_6(self):
        """An OpenAI codename (is_latest) aliases to gpt-5.6's input tokens."""
        model = get_model("openai/foo-bar-22", api_key="test-key")
        tokens = get_model_input_tokens(model)
        assert tokens == 922_000

    def test_openai_known_model_unaffected(self):
        """A known OpenAI model still reports its own input tokens."""
        model = get_model("openai/gpt-4o", api_key="test-key")
        tokens = get_model_input_tokens(model)
        assert tokens == get_model_info("openai/gpt-4o").input_tokens

    def test_explicit_set_model_info_overrides_codename_alias(self):
        """An explicit set_model_info() wins over the frontier aliasing.

        A codename normally aliases to gpt-5.6's window; an explicit registration
        means the caller knows the real window and must take precedence.
        """
        model = get_model("openai/foo-bar-22", api_key="test-key")
        assert get_model_input_tokens(model) == 922_000  # aliased by default
        set_model_info("openai/foo-bar-22", ModelInfo(context_length=4242))
        assert get_model_input_tokens(model) == 4242

    def test_codename_override_does_not_affect_frontier_model(self):
        """Overriding a codename must not leak into the real frontier model."""
        set_model_info("openai/foo-bar-22", ModelInfo(context_length=4242))
        frontier = get_model("openai/gpt-5.6", api_key="test-key")
        tokens = get_model_input_tokens(frontier)
        assert tokens is not None
        assert tokens != 4242


class TestResultCaching:
    """Tests for the result-level memoization in get_model_info."""

    def test_failed_lookup_only_runs_fuzzy_match_once(self, monkeypatch):
        """A second lookup of an unknown model must not re-run fuzzy matching."""
        from inspect_ai.model import _model_info as model_info_module

        call_count = 0
        original_fuzzy = model_info_module._fuzzy_match

        def counting_fuzzy(name, db):
            nonlocal call_count
            call_count += 1
            return original_fuzzy(name, db)

        monkeypatch.setattr(model_info_module, "_fuzzy_match", counting_fuzzy)

        # First call: cache miss, fuzzy runs.
        result1 = get_model_info("unknown-provider/never-heard-of-it-xyz")
        assert result1 is None
        assert call_count == 1

        # Second call: cache hit, fuzzy must not run again.
        result2 = get_model_info("unknown-provider/never-heard-of-it-xyz")
        assert result2 is None
        assert call_count == 1

    def test_successful_lookup_is_cached(self, monkeypatch):
        """A second lookup of a known model must not re-run any matching."""
        from inspect_ai.model import _model_info as model_info_module

        # Prime the cache.
        first = get_model_info("anthropic/claude-sonnet-4")
        assert first is not None

        lookup_calls = 0
        original_lookup = model_info_module._lookup_in_db

        def counting_lookup(name, db):
            nonlocal lookup_calls
            lookup_calls += 1
            return original_lookup(name, db)

        monkeypatch.setattr(model_info_module, "_lookup_in_db", counting_lookup)

        second = get_model_info("anthropic/claude-sonnet-4")
        assert second is first
        assert lookup_calls == 0

    def test_set_model_info_invalidates_cache(self):
        """set_model_info() must make subsequent lookups see the new info."""
        # Cache a None result for a name we'll subsequently register.
        before = get_model_info("test-org/cache-invalidation-model")
        assert before is None

        # Register custom info under that exact name.
        set_model_info(
            "test-org/cache-invalidation-model",
            ModelInfo(context_length=12345),
        )

        # The cached None must have been invalidated.
        after = get_model_info("test-org/cache-invalidation-model")
        assert after is not None
        assert after.context_length == 12345

    def test_set_model_cost_invalidates_cache(self):
        """set_model_cost() must make subsequent lookups see the new cost."""
        # Prime the cache with a known model.
        first = get_model_info("anthropic/claude-sonnet-4")
        assert first is not None

        set_model_cost(
            "anthropic/claude-sonnet-4",
            ModelCost(
                input=1.0, output=2.0, input_cache_write=0.5, input_cache_read=0.1
            ),
        )

        after = get_model_info("anthropic/claude-sonnet-4")
        assert after is not None
        assert after.cost is not None
        assert after.cost.input == 1.0
        assert after.cost.output == 2.0


class TestDoesNotReinstantiateProvider:
    """Lookups for an already-instantiated model must never re-resolve a provider.

    Re-resolving instantiates the provider a second time, which for local
    providers (e.g. HuggingFace) reloads the model weights into GPU memory and
    can OOM-crash the run. These guard the per-generation / startup hot paths.
    """

    @staticmethod
    def _track_get_model(monkeypatch: Any) -> list[Any]:
        """Patch get_model to record calls. Returns the call-args list.

        Counting (rather than raising) is required because the provider-resolving
        fallback in _resolve_model_info swallows exceptions via a broad
        ``except (ValueError, Exception)`` -- a raised AssertionError would be
        caught and the unwanted instantiation would go undetected.
        """
        calls: list[Any] = []

        def tracking_get_model(*args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))
            raise RuntimeError("provider resolution should not happen")

        monkeypatch.setattr("inspect_ai.model._model.get_model", tracking_get_model)
        return calls

    def test_record_usage_does_not_instantiate_provider(self, monkeypatch):
        """Recording usage for a local model must not re-resolve (reload) it."""
        from inspect_ai.model._model import record_and_check_model_usage
        from inspect_ai.model._model_output import ModelUsage

        # create the model first
        model = get_model("noload/totally-unknown-model-xyz")

        calls = self._track_get_model(monkeypatch)

        record_and_check_model_usage(
            model,
            ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )
        assert calls == []

    def test_get_model_input_tokens_does_not_instantiate_provider(self, monkeypatch):
        """Compaction's context-window lookup must not re-resolve the model."""
        # create the model first (via the registered no-load provider) so the
        # patch below only affects the get_model_input_tokens() call path
        model = get_model("noload/totally-unknown-model-xyz")

        calls = self._track_get_model(monkeypatch)

        assert get_model_input_tokens(model) is None
        assert calls == []

    def test_direct_lookup_still_returns_configured_cost(self):
        """The fix must not drop cost data for the usage-recording path.

        Built-in models ship no cost; cost comes from set_model_cost() /
        --model-cost-config. record_and_check_model_usage() now uses the direct
        lookup, so configured costs must still be visible through it.
        """
        set_model_cost(
            "anthropic/claude-sonnet-4",
            ModelCost(
                input=1.0, output=2.0, input_cache_write=0.5, input_cache_read=0.1
            ),
        )
        info = _get_model_info_direct("anthropic/claude-sonnet-4")
        assert info is not None
        assert info.cost is not None
        assert info.cost.input == 1.0

    def test_direct_lookup_finds_cost_keyed_by_full_model_string(self):
        """Cost keyed under the user-facing string must be found for a Model.

        Routed providers (together, hf-inference-providers, custom routed
        providers) strip a route prefix in canonical_name(), so it differs from
        the user-facing string that set_model_info/set_model_cost key under.
        mockllm reproduces the mismatch: str(model) is "mockllm/model" but
        canonical_name() is "model". A canonical-only lookup drops the cost.
        """
        from inspect_ai.model._model import record_and_check_model_usage
        from inspect_ai.model._model_output import ModelUsage

        set_model_info(
            "mockllm/model",
            ModelInfo(
                cost=ModelCost(
                    input=1000.0,
                    output=1000.0,
                    input_cache_write=0.0,
                    input_cache_read=0.0,
                )
            ),
        )
        model = get_model("mockllm/model")
        assert str(model) == "mockllm/model"
        assert model.canonical_name() == "model"

        info = _get_model_info_direct(model)
        assert info is not None
        assert info.cost is not None
        assert info.cost.input == 1000.0

        usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
        record_and_check_model_usage(model, usage)
        # (3 * 1000 + 4 * 1000) / 1_000_000 = 0.007
        assert usage.total_cost == pytest.approx(0.007)
