import pytest

from inspect_ai.model._providers.anthropic import _web_search_tool_param


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
        options = {"key1": "value1", "key2": "value2"}

        result = _web_search_tool_param(options)

        assert result == {
            "name": "web_search",
            "type": "web_search_20250305",
            "key1": "value1",
            "key2": "value2",
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
