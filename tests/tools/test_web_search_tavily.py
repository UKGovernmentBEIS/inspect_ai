import json
from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.tool._tool import ToolError
from inspect_ai.tool._tools._web_search._tavily import tavily_search_provider

# See https://docs.tavily.com/documentation/api-reference/endpoint/search
EXAMPLE_RESPONSE = {
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
                    text="test answer",
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


def create_recording_transport(requests: list[httpx.Request]):
    """Create a mock transport that records each request and returns our test response."""

    async def mock_response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code=HTTPStatus.OK, json=EXAMPLE_RESPONSE)

    return httpx.MockTransport(mock_response)


async def _search_and_record(options: dict[str, object] | None) -> httpx.Request:
    requests: list[httpx.Request] = []
    mock_client = httpx.AsyncClient(transport=create_recording_transport(requests))
    with patch.dict("os.environ", {"TAVILY_API_KEY": "dummy-key"}):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = mock_client
            search = tavily_search_provider(options)
            await search("test query")
    assert len(requests) == 1
    return requests[0]


class TestTavilyEndpoint:
    """Test the base_url and extra_headers options."""

    async def test_default_endpoint_and_headers(self):
        request = await _search_and_record(None)
        assert str(request.url) == "https://api.tavily.com/search"
        assert request.headers["Authorization"] == "Bearer dummy-key"

    async def test_base_url_and_extra_headers(self):
        request = await _search_and_record(
            {
                "base_url": "https://proxy.example.com/tavily/",
                "extra_headers": {"X-Snapshot-Id": "20261024"},
                "max_results": 3,
            }
        )
        assert str(request.url) == "https://proxy.example.com/tavily/search"
        assert request.headers["Authorization"] == "Bearer dummy-key"
        assert request.headers["X-Snapshot-Id"] == "20261024"
        body = json.loads(request.content)
        assert body["max_results"] == 3
        assert "base_url" not in body
        assert "extra_headers" not in body

    @pytest.mark.parametrize("name", ["Authorization", "authorization"])
    async def test_extra_headers_override_authorization(self, name: str):
        request = await _search_and_record(
            {"extra_headers": {name: "Token proxy-token"}}
        )
        assert request.headers.get_list("Authorization") == ["Token proxy-token"]

    @pytest.mark.parametrize("depth", ["fast", "ultra-fast"])
    async def test_fast_search_depths_accepted(self, depth: str):
        request = await _search_and_record({"search_depth": depth})
        assert json.loads(request.content)["search_depth"] == depth
