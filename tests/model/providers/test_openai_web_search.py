from unittest.mock import MagicMock, patch

import pytest

from inspect_ai.model._providers._openai_web_search import (
    _web_search_tool,
    maybe_web_search_tool,
)
from inspect_ai.tool._tool_info import ToolInfo


class TestOpenAIWebSearch:
    """Tests for the _openai_web_search.py module."""

    def test_maybe_web_search_tool_returns_none_for_non_web_search(self):
        assert (
            maybe_web_search_tool(
                "gpt-4o",
                ToolInfo(
                    name="not_web_search",
                    description="Not a web search tool",
                    options={"openai": {}},
                ),
            )
            is None
        )

    def test_maybe_web_search_tool_returns_none_for_no_options(self):
        assert (
            maybe_web_search_tool(
                "gpt-4o",
                ToolInfo(
                    name="web_search", description="A web search tool", options=None
                ),
            )
            is None
        )

    def test_maybe_web_search_tool_returns_none_for_no_openai_options(self):
        assert (
            maybe_web_search_tool(
                "gpt-4o",
                ToolInfo(
                    name="web_search",
                    description="A web search tool",
                    options={"not_openai": {}},
                ),
            )
            is None
        )

    def test_maybe_web_search_tool_returns_tool_param(self):
        assert maybe_web_search_tool(
            "gpt-4o",
            ToolInfo(
                name="web_search",
                description="A web search tool",
                options={"openai": {"key": "value"}},
            ),
        ) == {"type": "web_search_preview", "key": "value"}

    def test_web_search_tool_raises_type_error(self):
        with pytest.raises(TypeError) as excinfo:
            _web_search_tool("not a dict")

        assert "Expected a dictionary for openai_options" in str(excinfo.value)

    def test_web_search_tool_with_options(self):
        options = {"key1": "value1", "key2": "value2"}

        with patch(
            "openai.types.responses.WebSearchTool.model_validate"
        ) as mock_validate:
            mock_tool = MagicMock()
            mock_tool.model_dump.return_value = {
                "type": "web_search_preview",
                **options,
            }
            mock_validate.return_value = mock_tool

            result = _web_search_tool(options)

            mock_validate.assert_called_once_with(
                {"type": "web_search_preview", **options}
            )
            assert result == {
                "type": "web_search_preview",
                "key1": "value1",
                "key2": "value2",
            }

    def test_web_search_tool_with_empty_options(self):
        assert _web_search_tool({}) == {"type": "web_search_preview"}

    def test_web_search_tool_with_none(self):
        assert _web_search_tool(None) == {"type": "web_search_preview"}
