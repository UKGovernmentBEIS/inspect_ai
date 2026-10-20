import json
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.model import ChatMessageTool
from inspect_ai.model._openai_responses import _openai_responses_function_call_output
from inspect_ai.model._providers.anthropic import message_block_params
from inspect_ai.tool._tool import ToolError
from inspect_ai.tool._tools._web_search._tavily import (
    TavilySearchProvider,
    tavily_search_provider,
)

# See https://docs.tavily.com/documentation/api-reference/endpoint/search
EXAMPLE_RESPONSE: dict[str, Any] = {
    "query": "test query",
    "answer": "test answer",
    "follow_up_questions": None,
    "images": [],
    "results": [
        {
            "title": "First Result",
            "url": "https://example.com/1",
            "content": "This is the first search result content.",
            "score": 0.80698997,
            "raw_content": None,
        },
        {
            "title": "Second Result",
            "url": "https://example.com/2",
            "content": "This is the second search result content.",
            "score": 0.79901963,
            "raw_content": None,
        },
    ],
    "response_time": 2.42,
}

EXPECTED_SOURCES = (
    "Sources:\n\n"
    "[1] First Result\n"
    "URL: https://example.com/1\n"
    "This is the first search result content.\n\n"
    "[2] Second Result\n"
    "URL: https://example.com/2\n"
    "This is the second search result content."
)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> TavilySearchProvider:
    monkeypatch.setenv("TAVILY_API_KEY", "dummy-key")
    return TavilySearchProvider()


@pytest.mark.parametrize("api", ["openai", "anthropic"])
async def test_sources_reach_model(provider: TavilySearchProvider, api: str) -> None:
    result = provider.parse_response(EXAMPLE_RESPONSE)
    assert result is not None
    if api == "openai":
        output = json.dumps(
            await _openai_responses_function_call_output(
                ChatMessageTool(
                    content=[result], tool_call_id="search", function="web_search"
                )
            )
        )
    else:
        output = json.dumps(await message_block_params(result))
    for source in EXAMPLE_RESPONSE["results"]:
        assert source["title"] in output
        assert source["url"] in output
        assert source["content"] in output


def test_sources_without_answer(provider: TavilySearchProvider) -> None:
    result = provider.parse_response({**EXAMPLE_RESPONSE, "answer": None})
    assert result is not None
    assert result.text == EXPECTED_SOURCES


def test_answer_without_sources(provider: TavilySearchProvider) -> None:
    result = provider.parse_response({**EXAMPLE_RESPONSE, "results": []})
    assert result is not None
    assert result.text == "test answer"
    assert result.citations == []


def test_empty_response(provider: TavilySearchProvider) -> None:
    assert (
        provider.parse_response({**EXAMPLE_RESPONSE, "answer": None, "results": []})
        is None
    )


def create_mock_transport():
    """Create a mock transport that returns our test response."""

    async def mock_response(request):
        return httpx.Response(
            status_code=HTTPStatus.OK,
            json=EXAMPLE_RESPONSE,
        )

    return httpx.MockTransport(mock_response)


class TestTavilySearchRendering:
    """Test the rendering of Tavily search results."""

    async def test_search_result_rendering(self):
        """Test that search results are properly rendered in the output."""
        # Create a client with our mock transport
        mock_client = httpx.AsyncClient(transport=create_mock_transport())

        # Patch the environment and create the search function
        with patch.dict("os.environ", {"TAVILY_API_KEY": "dummy-key"}):
            # Patch the AsyncClient to use our mock transport
            with patch("httpx.AsyncClient") as mock_async_client_cls:
                mock_async_client_cls.return_value = mock_client
                search = tavily_search_provider()

                # Execute the search
                result = await search("test query")

                # Verify the result contains all expected content
                assert result == ContentText(
                    text=f"test answer\n\n{EXPECTED_SOURCES}",
                    citations=[
                        UrlCitation(
                            title="First Result",
                            cited_text="This is the first search result content.",
                            url="https://example.com/1",
                        ),
                        UrlCitation(
                            title="Second Result",
                            cited_text="This is the second search result content.",
                            url="https://example.com/2",
                        ),
                    ],
                )


QUERY_TOO_LONG_RESPONSE = {
    "detail": {"error": "Query is too long. Max query length is 400 characters."}
}


def create_error_transport(status_code: int, json_body: dict):
    """Create a mock transport that returns an error response."""

    async def mock_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            json=json_body,
            request=request,
        )

    return httpx.MockTransport(mock_response)


class TestTavilyQueryTooLong:
    """Test that Tavily query-too-long 400 errors are raised as ToolError."""

    async def test_query_too_long_raises_tool_error(self):
        """A 400 with Tavily's query-too-long body should raise ToolError."""
        mock_client = httpx.AsyncClient(
            transport=create_error_transport(400, QUERY_TOO_LONG_RESPONSE)
        )

        with patch.dict("os.environ", {"TAVILY_API_KEY": "dummy-key"}):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value = mock_client
                search = tavily_search_provider()

                with pytest.raises(ToolError, match="Query is too long"):
                    await search("a" * 401)

    async def test_other_400_error_raises_http_status_error(self):
        """A 400 without a parseable Tavily error should propagate as HTTPStatusError."""
        mock_client = httpx.AsyncClient(
            transport=create_error_transport(400, {"unexpected": "format"})
        )

        with patch.dict("os.environ", {"TAVILY_API_KEY": "dummy-key"}):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value = mock_client
                search = tavily_search_provider()

                with pytest.raises(httpx.HTTPStatusError):
                    await search("test query")

    async def test_query_too_long_with_string_detail(self):
        """A 400 with a string detail should also raise ToolError."""
        mock_client = httpx.AsyncClient(
            transport=create_error_transport(
                400,
                {"detail": "Query is too long. Max query length is 400 characters."},
            )
        )

        with patch.dict("os.environ", {"TAVILY_API_KEY": "dummy-key"}):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value = mock_client
                search = tavily_search_provider()

                with pytest.raises(ToolError, match="Query is too long"):
                    await search("a" * 401)
