import pytest

from inspect_ai.model._providers.anthropic import (
    AnthropicAPI,
    _supports_web_search,
    _web_search_tool_params,
)
from inspect_ai.tool._tool_info import ToolInfo


class TestAnthropicWebSearch:
    def test_web_search_tool_param_returns_tool_param_for_empty_options(self):
        assert _web_search_tool_params({}) == [
            {"name": "web_fetch", "type": "web_fetch_20250910"},
            {
                "name": "web_search",
                "type": "web_search_20250305",
            },
        ]

    def test_web_search_tool_param_returns_tool_param_for_none_options(self):
        assert _web_search_tool_params(None) == [
            {"name": "web_fetch", "type": "web_fetch_20250910"},
            {
                "name": "web_search",
                "type": "web_search_20250305",
            },
        ]

    def test_web_search_tool_raises_type_error(self):
        with pytest.raises(TypeError):
            _web_search_tool_params("not a dict")

    def test_web_search_tool_with_options(self):
        options = {"max_uses": 666}

        result = _web_search_tool_params(options)

        assert result == [
            {"name": "web_fetch", "type": "web_fetch_20250910", "max_uses": 666},
            {"name": "web_search", "type": "web_search_20250305", "max_uses": 666},
        ]

    def test_web_search_tool_with_filtering(self):
        assert _web_search_tool_params({}, web_search_filtering=True) == [
            {"name": "web_fetch", "type": "web_fetch_20260209"},
            {
                "name": "web_search",
                "type": "web_search_20260209",
            },
        ]

    def test_web_search_tool_with_filtering_and_options(self):
        options = {"max_uses": 666, "allowed_domains": ["nhl.com"]}

        result = _web_search_tool_params(options, web_search_filtering=True)

        assert result == [
            {
                "name": "web_fetch",
                "type": "web_fetch_20260209",
                "max_uses": 666,
                "allowed_domains": ["nhl.com"],
            },
            {
                "name": "web_search",
                "type": "web_search_20260209",
                "max_uses": 666,
                "allowed_domains": ["nhl.com"],
            },
        ]


class TestWebSearchFilteringGate:
    """Gating for web search dynamic filtering.

    Dynamic filtering is enabled for frontier models (Claude 4.6 and later)
    but not on Vertex or Bedrock.
    """

    WEB_SEARCH_TOOL = ToolInfo(
        name="web_search", description="Search the web", options={"anthropic": {}}
    )

    def _api(self, model_name: str, service: str | None = None) -> AnthropicAPI:
        api = AnthropicAPI(model_name=model_name, api_key="test-key")
        if service is not None:
            api.service = service
        return api

    def _tool_types(self, api: AnthropicAPI) -> list[str] | None:
        params = api.web_search_tool_params(self.WEB_SEARCH_TOOL)
        return [str(p["type"]) for p in params] if params is not None else None

    @pytest.mark.parametrize(
        "model_name",
        [
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-fable-5",
        ],
    )
    def test_filtering_enabled_for_frontier_models(self, model_name: str):
        assert self._tool_types(self._api(model_name)) == [
            "web_fetch_20260209",
            "web_search_20260209",
        ]

    @pytest.mark.parametrize(
        "model_name",
        ["claude-sonnet-4-5", "claude-opus-4-1"],
    )
    def test_filtering_disabled_for_non_frontier_models(self, model_name: str):
        assert self._tool_types(self._api(model_name)) == [
            "web_fetch_20250910",
            "web_search_20250305",
        ]

    @pytest.mark.parametrize("service", ["vertex", "bedrock"])
    def test_filtering_disabled_on_vertex_and_bedrock(self, service: str):
        assert self._tool_types(self._api("claude-opus-4-8", service)) == [
            "web_fetch_20250910",
            "web_search_20250305",
        ]

    def test_no_params_without_anthropic_option(self):
        tool = ToolInfo(name="web_search", description="Search the web")
        assert self._api("claude-opus-4-8").web_search_tool_params(tool) is None


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
