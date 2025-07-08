import pytest

from inspect_ai.model._providers.anthropic import (
    _supports_web_search,
    _web_search_tool_param,
)


class TestAnthropicWebSearch:
    def test_web_search_tool_param_returns_tool_param_for_empty_options(self):
        assert _web_search_tool_param({}) == {
            "name": "web_search",
            "type": "web_search_20250305",
        }

    def test_web_search_tool_param_returns_tool_param_for_none_options(self):
        assert _web_search_tool_param(None) == {
            "name": "web_search",
            "type": "web_search_20250305",
        }

    def test_web_search_tool_raises_type_error(self):
        with pytest.raises(TypeError):
            _web_search_tool_param("not a dict")

    def test_web_search_tool_with_options(self):
        options = {"max_uses": 666}

        result = _web_search_tool_param(options)

        assert result == {
            "name": "web_search",
            "type": "web_search_20250305",
            "max_uses": 666,
        }

    def test_web_search_tool_with_empty_options(self):
        assert _web_search_tool_param({}) == {
            "name": "web_search",
            "type": "web_search_20250305",
        }

    def test_web_search_tool_with_none(self):
        assert _web_search_tool_param(None) == {
            "name": "web_search",
            "type": "web_search_20250305",
        }


class TestSupportsWebSearch:
    """Test the _supports_web_search function to ensure it correctly identifies models that support web search."""

    # Table of test cases: (model_name, expected_result, description)
    test_cases = [
        # Supported Claude Opus 4 models
        ("claude-opus-4", True, "base claude-opus-4"),
        ("claude-opus-4-latest", True, "claude-opus-4 latest"),
        ("claude-opus-4-20250120", True, "claude-opus-4 dated"),
        ("claude-opus-4-beta", True, "claude-opus-4 beta"),
        ("claude-opus-4-experimental", True, "claude-opus-4 experimental"),
        # Supported Claude Sonnet 4 models
        ("claude-sonnet-4", True, "base claude-sonnet-4"),
        ("claude-sonnet-4-latest", True, "claude-sonnet-4 latest"),
        ("claude-sonnet-4-20250120", True, "claude-sonnet-4 dated"),
        ("claude-sonnet-4-beta", True, "claude-sonnet-4 beta"),
        ("claude-sonnet-4-experimental", True, "claude-sonnet-4 experimental"),
        # Supported Claude 3.7 Sonnet models
        ("claude-3-7-sonnet", True, "base claude-3-7-sonnet"),
        ("claude-3-7-sonnet-latest", True, "claude-3-7-sonnet latest"),
        ("claude-3-7-sonnet-20241022", True, "claude-3-7-sonnet dated"),
        ("claude-3-7-sonnet-beta", True, "claude-3-7-sonnet beta"),
        ("claude-3-7-sonnet-experimental", True, "claude-3-7-sonnet experimental"),
        # Supported specific latest models
        ("claude-3-5-sonnet-latest", True, "claude-3-5-sonnet-latest"),
        ("claude-3-5-haiku-latest", True, "claude-3-5-haiku-latest"),
        # Unsupported older Claude 3 models
        ("claude-3-opus", False, "claude-3-opus"),
        ("claude-3-sonnet", False, "claude-3-sonnet"),
        ("claude-3-haiku", False, "claude-3-haiku"),
        ("claude-3-opus-20240229", False, "claude-3-opus dated"),
        ("claude-3-sonnet-20240229", False, "claude-3-sonnet dated"),
        ("claude-3-haiku-20240307", False, "claude-3-haiku dated"),
        ("claude-3-5-sonnet", False, "claude-3-5-sonnet (not latest)"),
        ("claude-3-5-sonnet-20240620", False, "claude-3-5-sonnet dated"),
        ("claude-3-5-sonnet-20241022", False, "claude-3-5-sonnet another date"),
        ("claude-3-5-haiku", False, "claude-3-5-haiku (not latest)"),
        ("claude-3-5-haiku-20241022", False, "claude-3-5-haiku dated"),
        # Unsupported Claude 2 models
        ("claude-2", False, "claude-2"),
        ("claude-2.0", False, "claude-2.0"),
        ("claude-2.1", False, "claude-2.1"),
        ("claude-instant-1.2", False, "claude-instant-1.2"),
        # Unsupported invalid/unrecognized models
        ("", False, "empty string"),
        ("gpt-4", False, "gpt-4"),
        ("claude", False, "claude only"),
        ("claude-invalid", False, "claude-invalid"),
        ("claude-3", False, "claude-3 only"),
        ("claude-4", False, "claude-4 without variant"),
        ("claude-5-sonnet", False, "non-existent claude-5"),
        ("not-a-model", False, "random string"),
        ("claude-3-6-sonnet", False, "non-existent claude-3-6"),
        # Case sensitivity tests
        ("Claude-opus-4", False, "Claude-opus-4 (wrong case)"),
        ("CLAUDE-OPUS-4", False, "CLAUDE-OPUS-4 (all caps)"),
        ("Claude-3-7-Sonnet", False, "Claude-3-7-Sonnet (mixed case)"),
        ("CLAUDE-3-5-SONNET-LATEST", False, "CLAUDE-3-5-SONNET-LATEST (all caps)"),
        # Edge cases that should not be supported
        (" claude-3-sonnet ", False, "claude-3-sonnet with spaces (unsupported base)"),
        ("claude-3-5-sonnet ", False, "claude-3-5-sonnet with space (not latest)"),
        ("   ", False, "only whitespace"),
    ]

    @pytest.mark.parametrize("model_name,expected,description", test_cases)
    def test_supports_web_search(
        self, model_name: str, expected: bool, description: str
    ):
        """Table-driven test for _supports_web_search function."""
        result = _supports_web_search(model_name)
        assert result == expected, (
            f"Model '{model_name}' ({description}): expected {expected}, got {result}"
        )
