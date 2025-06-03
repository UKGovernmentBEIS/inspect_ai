from http import HTTPStatus
from unittest.mock import patch

import httpx
import pytest

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

    @pytest.mark.asyncio
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
                assert "Answer: test answer" in result
                assert "[First Result](https://example.com/1):" in result
                assert "This is the first search result content." in result
                assert "[Second Result](https://example.com/2):" in result
                assert "This is the second search result content." in result
