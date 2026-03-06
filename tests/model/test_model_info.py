"""Tests for model_info lookup functionality."""

import pytest

from inspect_ai.model import ModelInfo, get_model_info, set_model_info
from inspect_ai.model._model_info import clear_model_info_cache


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

    def test_unknown_model_returns_none(self):
        """Test that unknown models return None."""
        info = get_model_info("unknown-provider/unknown-model-xyz")
        assert info is None

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
            "google/gemini-2.5-flash-preview-05-20",
        ]

        for model in test_models:
            info = get_model_info(model)
            if info is not None:  # Model may not exist in database
                assert info.context_length is not None, f"{model} has no context_length"
                assert info.context_length > 0, f"{model} has invalid context_length"
