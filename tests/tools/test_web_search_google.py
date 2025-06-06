from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.tool._tools._web_search._google import google_search_provider

# Mock response from Google Custom Search API
# See https://developers.google.com/custom-search/v1/reference/rest/v1/Search
MOCK_GOOGLE_SEARCH_RESPONSE = {
    "items": [
        {
            "link": "https://example.com/1",
            "title": "First Result",
            "snippet": "This is the first search result snippet.",
        },
        {
            "link": "https://example.com/2",
            "title": "Second Result",
            "snippet": "This is the second search result snippet.",
        },
    ]
}

# Mock HTML content for the pages
MOCK_HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
    <main>
        <p>This is a test page content.</p>
    </main>
</body>
</html>
"""


def create_mock_transport():
    """Create a mock transport that returns our test responses."""
    call_count = 0

    async def mock_response(request):
        nonlocal call_count

        # Handle Google API search request
        if "googleapis.com/customsearch" in str(request.url):
            call_count += 1
            if call_count == 1:
                # Return mock results on first call
                return httpx.Response(
                    status_code=HTTPStatus.OK,
                    json=MOCK_GOOGLE_SEARCH_RESPONSE,
                )
            else:
                # Return empty results on subsequent calls
                return httpx.Response(
                    status_code=HTTPStatus.OK,
                    json={"items": []},
                )
        # Handle page content requests
        else:
            return httpx.Response(
                status_code=HTTPStatus.OK,
                content=MOCK_HTML_CONTENT.encode(),
                headers={"content-type": "text/html"},
            )

    return httpx.MockTransport(mock_response)


class TestGoogleSearchRendering:
    """Test the rendering of Google search results."""

    @pytest.mark.asyncio
    async def test_search_result_rendering(self):
        """Test that search results are properly rendered in the output."""
        mock_client = httpx.AsyncClient(transport=create_mock_transport())

        # Mock the model response for page relevance check
        mock_model = AsyncMock()
        mock_model.generate.return_value.message.text = "yes"

        with (
            patch("httpx.AsyncClient") as mock_async_client_cls,
            patch("inspect_ai.model._model.get_model") as mock_get_model,
            patch(
                "inspect_ai.tool._tools._web_search._google.maybe_get_google_api_keys"
            ) as mock_get_keys,
        ):
            mock_async_client_cls.return_value = mock_client
            mock_get_model.return_value = mock_model
            mock_get_keys.return_value = ("dummy-key", "dummy-cse-id")

            search = google_search_provider()

            result = await search("test query")

            assert result == [
                ContentText(
                    text="Test Page\nThis is a test page content.",
                    citations=[
                        UrlCitation(
                            title="Test Page",
                            # cited_text="This is the first search result content.",
                            url="https://example.com/1",
                        ),
                    ],
                ),
                ContentText(
                    text="Test Page\nThis is a test page content.",
                    citations=[
                        UrlCitation(
                            title="Test Page",
                            # cited_text="This is the second search result content.",
                            url="https://example.com/2",
                        ),
                    ],
                ),
            ]

            mock_model.generate.assert_called()
