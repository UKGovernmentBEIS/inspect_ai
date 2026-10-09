from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from test_helpers.limits import (
    exceed_token_limit_and_terminate_in_child_tasks,
    exceed_token_limit_in_child_task,
)

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.tool._tools._web_search._google import google_search_provider
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import (
    LimitExceededError,
    enclosing_limit_error,
    token_limit,
)

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

    async def test_search_relevance_limit_error_propagates(self) -> None:
        """A limit hit by the page relevance model call ends the search."""
        mock_client = httpx.AsyncClient(transport=create_mock_transport())
        mock_model = AsyncMock()
        mock_model.generate.side_effect = LimitExceededError("token", value=2, limit=1)

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

            with pytest.raises(Exception) as exc_info:
                await search("test query")

        assert isinstance(inner_exception(exc_info.value), LimitExceededError)

    async def test_search_relevance_grouped_limit_error_propagates(self) -> None:
        """A limit raised from a child task of the relevance call ends the search."""
        mock_client = httpx.AsyncClient(transport=create_mock_transport())

        async def generate(*args, **kwargs):
            await exceed_token_limit_in_child_task()

        mock_model = AsyncMock()
        mock_model.generate.side_effect = generate

        with (
            patch("httpx.AsyncClient") as mock_async_client_cls,
            patch("inspect_ai.model._model.get_model") as mock_get_model,
            patch(
                "inspect_ai.tool._tools._web_search._google.maybe_get_google_api_keys"
            ) as mock_get_keys,
            token_limit(1) as limit,
        ):
            mock_async_client_cls.return_value = mock_client
            mock_get_model.return_value = mock_model
            mock_get_keys.return_value = ("dummy-key", "dummy-cse-id")

            search = google_search_provider()

            with pytest.raises(Exception) as exc_info:
                await search("test query")

            found = enclosing_limit_error(exc_info.value)
            assert found is not None and found.source is limit
        # the first page's two relevance calls, and no further pages
        assert mock_model.generate.await_count <= 2

    async def test_search_relevance_sample_ending_error_wins_over_agent_limit(
        self,
    ) -> None:
        """An error that ends the sample propagates over an agent limit raised with it."""
        mock_client = httpx.AsyncClient(transport=create_mock_transport())

        async def generate(*args, **kwargs):
            await exceed_token_limit_and_terminate_in_child_tasks()

        mock_model = AsyncMock()
        mock_model.generate.side_effect = generate

        with (
            patch("httpx.AsyncClient") as mock_async_client_cls,
            patch("inspect_ai.model._model.get_model") as mock_get_model,
            patch(
                "inspect_ai.tool._tools._web_search._google.maybe_get_google_api_keys"
            ) as mock_get_keys,
            # the sample's limit and an agent's
            token_limit(None),
            token_limit(1),
        ):
            mock_async_client_cls.return_value = mock_client
            mock_get_model.return_value = mock_model
            mock_get_keys.return_value = ("dummy-key", "dummy-cse-id")

            search = google_search_provider()

            with pytest.raises(Exception) as exc_info:
                await search("test query")

        # each relevance call raised both; only the sample-ending error is kept
        assert exc_info.group_contains(TerminateSampleError, depth=None)
        assert not exc_info.group_contains(LimitExceededError, depth=None)

    async def test_search_url_encodes_non_printable_characters(self):
        """Test that search queries with non-printable characters are properly URL-encoded."""
        mock_client = httpx.AsyncClient(transport=create_mock_transport())

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

            # Non-printable ASCII character should not crash
            result = await search("test\x01query")
            assert result is not None

    async def test_search_url_encodes_special_characters(self) -> None:
        """Test that queries with special characters don't corrupt the URL structure."""
        captured_urls: list[str] = []
        inner_transport = create_mock_transport()

        async def capturing_handler(request):
            captured_urls.append(str(request.url))
            return await inner_transport.handle_async_request(request)

        mock_client = httpx.AsyncClient(
            transport=httpx.MockTransport(capturing_handler)
        )

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

            result = await search("a&b=c#d")
            assert result is not None

            api_urls = [u for u in captured_urls if "googleapis.com" in u]
            # The mock returns 2 results but num_results defaults to 3,
            # so the provider paginates up to max_provider_calls (3) times
            assert len(api_urls) == 3

            # The query parameter value should be percent-encoded so that '&',
            # '=', and '#' aren't interpreted as special characters
            for api_url in api_urls:
                assert "q=a%26b%3Dc%23d" in api_url, (
                    f"Expected encoded query param in URL, got: {api_url}"
                )
