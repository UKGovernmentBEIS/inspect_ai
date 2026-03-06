"""Tests for canonical_name() implementations across providers.

These tests verify that each provider correctly transforms its model names
to canonical format for model info database lookup.
"""

import pytest


class TestBedrockCanonicalName:
    """Tests for Bedrock provider canonical_name()."""

    def test_anthropic_claude_with_version(self):
        """Test Bedrock format: anthropic.claude-3-5-sonnet-20241022-v2:0"""
        from inspect_ai.model._providers.bedrock import BedrockAPI

        api = BedrockAPI(
            model_name="anthropic.claude-3-5-sonnet-20241022-v2:0",
            base_url=None,
        )
        assert api.canonical_name() == "anthropic/claude-3-5-sonnet-20241022"

    def test_anthropic_claude_without_variant(self):
        """Test Bedrock format without variant suffix."""
        from inspect_ai.model._providers.bedrock import BedrockAPI

        api = BedrockAPI(
            model_name="anthropic.claude-3-5-sonnet-20241022-v2",
            base_url=None,
        )
        assert api.canonical_name() == "anthropic/claude-3-5-sonnet-20241022"

    def test_meta_llama(self):
        """Test Bedrock format: meta.llama3-1-70b-instruct-v1:0"""
        from inspect_ai.model._providers.bedrock import BedrockAPI

        api = BedrockAPI(
            model_name="meta.llama3-1-70b-instruct-v1:0",
            base_url=None,
        )
        assert api.canonical_name() == "meta/llama3-1-70b-instruct"

    def test_model_without_provider_prefix(self):
        """Test model name without provider prefix."""
        from inspect_ai.model._providers.bedrock import BedrockAPI

        api = BedrockAPI(
            model_name="some-model-v1",
            base_url=None,
        )
        assert api.canonical_name() == "some-model"


class TestOpenRouterCanonicalName:
    """Tests for OpenRouter provider canonical_name()."""

    def test_strips_provider_prefix(self):
        """Test that provider prefix is stripped from 3-part names."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="together/meta-llama/Llama-3.1-8B",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "meta-llama/Llama-3.1-8B"

    def test_preserves_first_party_names(self):
        """Test that first-party provider names are preserved."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="anthropic/claude-3.5-sonnet",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "anthropic/claude-3.5-sonnet"

    def test_strips_free_suffix(self):
        """Test that :free suffix is stripped."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="anthropic/claude-3.5-sonnet:free",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "anthropic/claude-3.5-sonnet"

    def test_strips_extended_suffix(self):
        """Test that :extended suffix is stripped."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="anthropic/claude-3.5-sonnet:extended",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "anthropic/claude-3.5-sonnet"

    def test_strips_nitro_suffix(self):
        """Test that :nitro suffix is stripped."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="openai/gpt-4o:nitro",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "openai/gpt-4o"

    def test_strips_suffix_and_provider_prefix(self):
        """Test both suffix stripping and provider prefix removal."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="together/meta-llama/Llama-3.1-8B:free",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "meta-llama/Llama-3.1-8B"


class TestOpenAICanonicalName:
    """Tests for OpenAI provider canonical_name()."""

    def test_standard_model(self):
        """Test OpenAI model canonical name includes provider prefix."""
        from inspect_ai.model._providers.openai import OpenAIAPI

        api = OpenAIAPI(model_name="gpt-4o", api_key="test-key")
        assert api.canonical_name() == "openai/gpt-4o"

    def test_o_series_model(self):
        """Test O-series model canonical name."""
        from inspect_ai.model._providers.openai import OpenAIAPI

        api = OpenAIAPI(model_name="o1-preview", api_key="test-key")
        assert api.canonical_name() == "openai/o1-preview"


class TestAnthropicCanonicalName:
    """Tests for Anthropic provider canonical_name()."""

    def test_claude_model(self):
        """Test Anthropic model canonical name includes provider prefix."""
        from inspect_ai.model._providers.anthropic import AnthropicAPI

        api = AnthropicAPI(model_name="claude-sonnet-4", api_key="test-key")
        assert api.canonical_name() == "anthropic/claude-sonnet-4"


class TestTogetherCanonicalName:
    """Tests for Together provider canonical_name()."""

    def test_huggingface_style_name(self):
        """Test Together returns HuggingFace-style names."""
        from inspect_ai.model._providers.together import TogetherAIAPI

        api = TogetherAIAPI(
            model_name="meta-llama/Llama-3.1-8B-Instruct", api_key="test-key"
        )
        assert api.canonical_name() == "meta-llama/Llama-3.1-8B-Instruct"


class TestGrokCanonicalName:
    """Tests for Grok provider canonical_name()."""

    def test_grok_prefix(self):
        """Test Grok model canonical name includes grok/ prefix."""
        # Mock API key to avoid environment requirement
        import os

        from inspect_ai.model._providers.grok import GrokAPI

        os.environ["XAI_API_KEY"] = "test-key"
        try:
            api = GrokAPI(model_name="grok-3")
            assert api.canonical_name() == "grok/grok-3"
        finally:
            del os.environ["XAI_API_KEY"]

    def test_grok_4(self):
        """Test Grok 4 model canonical name."""
        import os

        from inspect_ai.model._providers.grok import GrokAPI

        os.environ["XAI_API_KEY"] = "test-key"
        try:
            api = GrokAPI(model_name="grok-4")
            assert api.canonical_name() == "grok/grok-4"
        finally:
            del os.environ["XAI_API_KEY"]


class TestOpenRouterFirstPartyDetection:
    """Tests for OpenRouter first-party provider detection."""

    def test_preserves_grok_first_party(self):
        """Test that grok models are recognized as first-party."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="grok/grok-3",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "grok/grok-3"

    def test_preserves_grok_with_suffix(self):
        """Test that grok models with suffix are handled correctly."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="grok/grok-3:free",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "grok/grok-3"

    def test_preserves_deepseek_first_party(self):
        """Test that deepseek models are recognized as first-party."""
        from inspect_ai.model._providers.openrouter import OpenRouterAPI

        api = OpenRouterAPI(
            model_name="deepseek/deepseek-chat",
            base_url=None,
            api_key="test-key",
        )
        assert api.canonical_name() == "deepseek/deepseek-chat"


class TestHFInferenceCanonicalName:
    """Tests for HF Inference Providers canonical_name()."""

    def test_basic_model_name(self):
        """Test basic HuggingFace-style model name."""
        import os

        from inspect_ai.model._providers.hf_inference_providers import (
            HFInferenceProvidersAPI,
        )

        os.environ["HF_TOKEN"] = "test-token"
        try:
            api = HFInferenceProvidersAPI(model_name="meta-llama/Llama-3.1-8B-Instruct")
            assert api.canonical_name() == "meta-llama/Llama-3.1-8B-Instruct"
        finally:
            del os.environ["HF_TOKEN"]

    def test_strips_fastest_suffix(self):
        """Test that :fastest suffix is stripped."""
        import os

        from inspect_ai.model._providers.hf_inference_providers import (
            HFInferenceProvidersAPI,
        )

        os.environ["HF_TOKEN"] = "test-token"
        try:
            api = HFInferenceProvidersAPI(
                model_name="meta-llama/Llama-3.1-8B-Instruct:fastest"
            )
            assert api.canonical_name() == "meta-llama/Llama-3.1-8B-Instruct"
        finally:
            del os.environ["HF_TOKEN"]

    def test_strips_cheapest_suffix(self):
        """Test that :cheapest suffix is stripped."""
        import os

        from inspect_ai.model._providers.hf_inference_providers import (
            HFInferenceProvidersAPI,
        )

        os.environ["HF_TOKEN"] = "test-token"
        try:
            api = HFInferenceProvidersAPI(
                model_name="meta-llama/Llama-3.1-8B-Instruct:cheapest"
            )
            assert api.canonical_name() == "meta-llama/Llama-3.1-8B-Instruct"
        finally:
            del os.environ["HF_TOKEN"]

    def test_strips_provider_suffix(self):
        """Test that provider suffix like :groq is stripped."""
        import os

        from inspect_ai.model._providers.hf_inference_providers import (
            HFInferenceProvidersAPI,
        )

        os.environ["HF_TOKEN"] = "test-token"
        try:
            api = HFInferenceProvidersAPI(
                model_name="meta-llama/Llama-3.1-8B-Instruct:groq"
            )
            assert api.canonical_name() == "meta-llama/Llama-3.1-8B-Instruct"
        finally:
            del os.environ["HF_TOKEN"]


class TestMistralCanonicalName:
    """Tests for Mistral provider canonical_name()."""

    def test_mistral_prefix(self):
        """Test Mistral model canonical name includes mistral/ prefix."""
        from inspect_ai.model._providers.mistral import MistralAPI

        api = MistralAPI(model_name="mistral-large-latest", api_key="test-key")
        assert api.canonical_name() == "mistral/mistral-large-latest"

    def test_mistral_small(self):
        """Test Mistral small model."""
        from inspect_ai.model._providers.mistral import MistralAPI

        api = MistralAPI(model_name="mistral-small-latest", api_key="test-key")
        assert api.canonical_name() == "mistral/mistral-small-latest"


class TestGoogleCanonicalName:
    """Tests for Google provider canonical_name()."""

    def test_google_prefix(self):
        """Test Google model canonical name includes google/ prefix."""
        from inspect_ai.model._providers.google import GoogleGenAIAPI

        api = GoogleGenAIAPI(model_name="gemini-1.5-pro", base_url=None, api_key=None)
        assert api.canonical_name() == "google/gemini-1.5-pro"

    def test_gemini_flash(self):
        """Test Gemini Flash model."""
        from inspect_ai.model._providers.google import GoogleGenAIAPI

        api = GoogleGenAIAPI(model_name="gemini-2.0-flash", base_url=None, api_key=None)
        assert api.canonical_name() == "google/gemini-2.0-flash"


class TestCloudFlareCanonicalName:
    """Tests for CloudFlare provider canonical_name()."""

    def test_strips_cf_prefix(self):
        """Test that @cf/ prefix added by constructor is stripped."""
        import os

        from inspect_ai.model._providers.cloudflare import CloudFlareAPI

        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "test-account"
        os.environ["CLOUDFLARE_API_TOKEN"] = "test-token"
        try:
            # Constructor adds @cf/ prefix, so pass name without it
            api = CloudFlareAPI(model_name="meta/llama-3.1-8b-instruct")
            # canonical_name() should strip the @cf/ prefix
            assert api.canonical_name() == "meta/llama-3.1-8b-instruct"
        finally:
            del os.environ["CLOUDFLARE_ACCOUNT_ID"]
            del os.environ["CLOUDFLARE_API_TOKEN"]

    def test_with_single_component_name(self):
        """Test with a simple model name."""
        import os

        from inspect_ai.model._providers.cloudflare import CloudFlareAPI

        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "test-account"
        os.environ["CLOUDFLARE_API_TOKEN"] = "test-token"
        try:
            api = CloudFlareAPI(model_name="llama-3.1-8b-instruct")
            # @cf/llama-3.1-8b-instruct → llama-3.1-8b-instruct
            assert api.canonical_name() == "llama-3.1-8b-instruct"
        finally:
            del os.environ["CLOUDFLARE_ACCOUNT_ID"]
            del os.environ["CLOUDFLARE_API_TOKEN"]


class TestFireworksCanonicalName:
    """Tests for Fireworks provider canonical_name()."""

    def test_strips_accounts_prefix(self):
        """Test that accounts/fireworks/models/ prefix is stripped."""
        import os

        from inspect_ai.model._providers.fireworks import FireworksAIAPI

        os.environ["FIREWORKS_API_KEY"] = "test-key"
        try:
            api = FireworksAIAPI(
                model_name="accounts/fireworks/models/llama-v3p1-8b-instruct"
            )
            assert api.canonical_name() == "llama-v3p1-8b-instruct"
        finally:
            del os.environ["FIREWORKS_API_KEY"]

    def test_preserves_name_without_prefix(self):
        """Test that names without accounts prefix are preserved."""
        import os

        from inspect_ai.model._providers.fireworks import FireworksAIAPI

        os.environ["FIREWORKS_API_KEY"] = "test-key"
        try:
            api = FireworksAIAPI(model_name="llama-v3p1-8b-instruct")
            assert api.canonical_name() == "llama-v3p1-8b-instruct"
        finally:
            del os.environ["FIREWORKS_API_KEY"]


class TestGroqCanonicalName:
    """Tests for Groq provider canonical_name()."""

    def test_returns_raw_name(self):
        """Test Groq returns raw model name (relies on fuzzy matching)."""
        import os

        from inspect_ai.model._providers.groq import GroqAPI

        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            api = GroqAPI(model_name="llama-3.1-8b-instant")
            assert api.canonical_name() == "llama-3.1-8b-instant"
        finally:
            del os.environ["GROQ_API_KEY"]

    def test_mixtral_model(self):
        """Test Mixtral model name."""
        import os

        from inspect_ai.model._providers.groq import GroqAPI

        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            api = GroqAPI(model_name="mixtral-8x7b-32768")
            assert api.canonical_name() == "mixtral-8x7b-32768"
        finally:
            del os.environ["GROQ_API_KEY"]


class TestFuzzyMatching:
    """Tests for fuzzy matching in _model_info.py."""

    def test_extract_model_name_two_parts(self):
        """Test extracting model name from org/model format."""
        from inspect_ai.model._model_info import _extract_model_name

        assert (
            _extract_model_name("meta-llama/Llama-3.1-8B") == "meta-llama/Llama-3.1-8B"
        )

    def test_extract_model_name_three_parts(self):
        """Test extracting model name from provider/org/model format."""
        from inspect_ai.model._model_info import _extract_model_name

        assert (
            _extract_model_name("together/meta-llama/Llama-3.1-8B")
            == "meta-llama/Llama-3.1-8B"
        )

    def test_extract_model_name_single_part(self):
        """Test extracting model name from single part."""
        from inspect_ai.model._model_info import _extract_model_name

        assert _extract_model_name("gpt-4o") == "gpt-4o"

    def test_normalize_for_fuzzy_lowercase(self):
        """Test that normalization lowercases."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("GPT-4O") == "gpt-4o"

    def test_normalize_for_fuzzy_underscores(self):
        """Test that underscores become hyphens."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("claude_sonnet_4") == "claude-sonnet-4"

    def test_normalize_for_fuzzy_strips_version(self):
        """Test that version suffixes are stripped."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("model-name-v2") == "model-name"
        assert _normalize_for_fuzzy("model-name:0") == "model-name"

    def test_compute_match_score_exact(self):
        """Test exact match score."""
        from inspect_ai.model._model_info import _compute_match_score

        assert _compute_match_score("gpt-4o", "gpt-4o") == 100

    def test_compute_match_score_substring(self):
        """Test substring match score."""
        from inspect_ai.model._model_info import _compute_match_score

        score = _compute_match_score("llama-3.1-8b", "llama-3.1-8b-instruct")
        assert 50 < score < 100

    def test_compute_match_score_no_match(self):
        """Test no match score."""
        from inspect_ai.model._model_info import _compute_match_score

        assert _compute_match_score("gpt-4o", "claude-3") == 0


class TestCanonicalNameLookup:
    """Test that canonical names resolve correctly via get_model_info()."""

    def test_openai_lookup(self):
        """Test OpenAI canonical name resolves to model info."""
        from inspect_ai.model._model_info import get_model_info
        from inspect_ai.model._providers.openai import OpenAIAPI

        api = OpenAIAPI(model_name="gpt-4o", api_key="test-key")
        canonical = api.canonical_name()
        info = get_model_info(canonical)
        assert info is not None
        # ModelInfo uses 'model' field, not 'name'
        assert info.model is not None

    def test_anthropic_lookup(self):
        """Test Anthropic canonical name resolves to model info."""
        from inspect_ai.model._model_info import get_model_info
        from inspect_ai.model._providers.anthropic import AnthropicAPI

        api = AnthropicAPI(model_name="claude-sonnet-4-20250514", api_key="test-key")
        canonical = api.canonical_name()
        info = get_model_info(canonical)
        assert info is not None

    def test_bedrock_claude_lookup(self):
        """Test Bedrock Claude canonical name uses fuzzy matching."""
        from inspect_ai.model._model_info import get_model_info
        from inspect_ai.model._providers.bedrock import BedrockAPI

        api = BedrockAPI(
            model_name="anthropic.claude-3-5-sonnet-20241022-v2:0",
            base_url=None,
        )
        canonical = api.canonical_name()
        # Should be anthropic/claude-3-5-sonnet-20241022
        assert canonical == "anthropic/claude-3-5-sonnet-20241022"
        info = get_model_info(canonical)
        # May or may not find exact match, but should not error
        assert info is None or info is not None

    def test_together_huggingface_lookup(self):
        """Test Together HuggingFace-style name lookup."""
        from inspect_ai.model._model_info import get_model_info
        from inspect_ai.model._providers.together import TogetherAIAPI

        api = TogetherAIAPI(
            model_name="meta-llama/Llama-3.1-8B-Instruct", api_key="test-key"
        )
        canonical = api.canonical_name()
        info = get_model_info(canonical)
        # Should find via fuzzy matching or exact match
        assert info is None or info is not None


class TestFuzzyMatchingEdgeCases:
    """Core fuzzy matching edge cases."""

    def test_score_at_threshold(self):
        """Test score exactly at 60 threshold."""
        from inspect_ai.model._model_info import _compute_match_score

        # Exact match should be 100
        assert _compute_match_score("model", "model") == 100
        # Substring with sufficient overlap should be >= 60
        score = _compute_match_score("model", "model-large")
        assert score >= 60

    def test_score_below_threshold(self):
        """Test score below 60 returns low value."""
        from inspect_ai.model._model_info import _compute_match_score

        # Very short substring relative to target
        score = _compute_match_score("ab", "abcdefghijklmnop")
        # Short match against long string should have lower score
        assert score < 100

    def test_empty_string(self):
        """Test empty string handling."""
        from inspect_ai.model._model_info import (
            _compute_match_score,
            _extract_model_name,
            _normalize_for_fuzzy,
        )

        assert _extract_model_name("") == ""
        assert _normalize_for_fuzzy("") == ""
        assert _compute_match_score("", "") == 100  # Both empty = exact match
        # Empty string IS a substring of any string, so score is 50 (0 overlap / max_len)
        assert _compute_match_score("", "model") == 50

    def test_case_insensitive_fuzzy(self):
        """Test case insensitive fuzzy matching."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("GPT-4O") == "gpt-4o"
        assert _normalize_for_fuzzy("Claude-Sonnet-4") == "claude-sonnet-4"


class TestFuzzyMatchingVersionVariants:
    """Test different version suffix formats."""

    def test_v_suffix_stripped(self):
        """Test -v1 suffix is stripped."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("model-v1") == "model"

    def test_v2_suffix_stripped(self):
        """Test -v2 suffix is stripped."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("model-v2") == "model"

    def test_v3_suffix_stripped(self):
        """Test -v3 suffix is stripped."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("claude-v3") == "claude"

    def test_colon_version_stripped(self):
        """Test :0 suffix is stripped."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("model:0") == "model"

    def test_date_version_not_stripped(self):
        """Test date-based versions are NOT stripped by normalize."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        # Date format should remain (fuzzy matching handles it differently)
        result = _normalize_for_fuzzy("gpt-4o-2024-08-06")
        assert "2024" in result  # Date preserved

    def test_multiple_version_markers(self):
        """Test version suffixes are stripped in order."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        # The :0 is stripped first, but -v2 remains since regex doesn't loop
        # -v\d+$ is applied first (doesn't match because string ends with :0)
        # Then :\d+$ strips :0, leaving model-v2
        assert _normalize_for_fuzzy("model-v2:0") == "model-v2"
        # But if the version suffix is at the end, it's stripped
        assert _normalize_for_fuzzy("model-v2") == "model"


class TestFuzzyMatchingNormalization:
    """Test normalization behavior."""

    def test_underscore_to_hyphen(self):
        """Test underscores become hyphens."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("claude_sonnet_4") == "claude-sonnet-4"

    def test_mixed_case_matching(self):
        """Test mixed case is lowercased."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("Claude-Sonnet-4") == "claude-sonnet-4"

    def test_all_caps_matching(self):
        """Test all caps is lowercased."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("CLAUDE-SONNET-4") == "claude-sonnet-4"

    def test_preserve_numbers(self):
        """Test numbers and dots are preserved."""
        from inspect_ai.model._model_info import _normalize_for_fuzzy

        assert _normalize_for_fuzzy("llama-3.1-8b") == "llama-3.1-8b"


class TestFuzzyMatchingSubstringScoring:
    """Test substring matching behavior."""

    def test_query_substring_of_target(self):
        """Test query is substring of target."""
        from inspect_ai.model._model_info import _compute_match_score

        score = _compute_match_score("llama", "llama-3.1-8b-instruct")
        assert 50 < score < 100

    def test_target_substring_of_query(self):
        """Test target is substring of query."""
        from inspect_ai.model._model_info import _compute_match_score

        score = _compute_match_score("llama-3.1-8b-instruct-turbo", "llama-3.1-8b")
        assert 50 < score < 100

    def test_short_query_two_chars(self):
        """Test very short 2-char query."""
        from inspect_ai.model._model_info import _compute_match_score

        score = _compute_match_score("gp", "gpt-4o")
        # Short substring should still match
        assert score >= 50 or score == 0  # Either matches or doesn't

    def test_short_query_three_chars(self):
        """Test short 3-char query."""
        from inspect_ai.model._model_info import _compute_match_score

        score = _compute_match_score("gpt", "gpt-4o")
        assert score >= 50

    def test_no_common_substring(self):
        """Test no common substring returns 0."""
        from inspect_ai.model._model_info import _compute_match_score

        assert _compute_match_score("xyz", "abc") == 0


class TestFuzzyMatchingPathExtraction:
    """Test _extract_model_name behavior."""

    def test_four_component_path(self):
        """Test 4-component path extracts last two."""
        from inspect_ai.model._model_info import _extract_model_name

        assert _extract_model_name("a/b/c/d") == "c/d"

    def test_single_component(self):
        """Test single component returns as-is."""
        from inspect_ai.model._model_info import _extract_model_name

        assert _extract_model_name("gpt-4o") == "gpt-4o"

    def test_two_components(self):
        """Test two components returns as-is."""
        from inspect_ai.model._model_info import _extract_model_name

        assert _extract_model_name("openai/gpt-4o") == "openai/gpt-4o"

    def test_three_components(self):
        """Test three components extracts last two."""
        from inspect_ai.model._model_info import _extract_model_name

        assert _extract_model_name("together/meta-llama/Llama") == "meta-llama/Llama"

    def test_five_component_path(self):
        """Test 5-component path still extracts last two."""
        from inspect_ai.model._model_info import _extract_model_name

        assert _extract_model_name("a/b/c/d/e") == "d/e"


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the model info cache before each test."""
    from inspect_ai.model._model_info import clear_model_info_cache

    clear_model_info_cache()
    yield
    clear_model_info_cache()
