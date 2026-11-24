import json
from http import HTTPStatus
from unittest.mock import patch

import httpx

from inspect_ai._util.content import ContentText
from inspect_ai.tool._tools._web_search._exa import exa_search_provider

# See https://docs.exa.ai/reference/answer
# Exa omits `text` from citations unless the request asks for it.
# Exa guarantees only url and title; id and text are conditional.
CITATION_MINIMAL = {
    "url": "https://example.com/1",
    "title": "First Result",
}
CITATION_WITHOUT_TEXT = {**CITATION_MINIMAL, "id": "https://example.com/1"}

CITATION_WITH_TEXT = {**CITATION_WITHOUT_TEXT, "text": "Page contents."}


def create_mock_transport(citation: dict[str, object], captured: dict[str, object]):
    """Mock transport returning `citation`, recording the request body."""

    async def mock_response(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            status_code=HTTPStatus.OK,
            json={"answer": "test answer", "citations": [citation]},
        )

    return httpx.MockTransport(mock_response)


async def run_search(
    citation: dict[str, object], options: dict[str, object] | None = None
) -> tuple[str | ContentText | list[ContentText] | None, dict[str, object]]:
    captured: dict[str, object] = {}
    mock_client = httpx.AsyncClient(transport=create_mock_transport(citation, captured))
    with patch.dict("os.environ", {"EXA_API_KEY": "dummy-key"}):
        with patch("httpx.AsyncClient") as mock_async_client_cls:
            mock_async_client_cls.return_value = mock_client
            search = exa_search_provider(options)
            result = await search("test query")
    return result, captured


class TestExaSearchTextOption:
    """Citations must validate whether or not the response includes `text`."""

    async def test_text_requested_by_default(self):
        """Without explicit options, the request asks for citation text."""
        result, request_body = await run_search(CITATION_WITH_TEXT)

        assert request_body["text"] is True
        assert isinstance(result, ContentText)
        assert result.text == "test answer"
        assert result.citations is not None
        assert result.citations[0].cited_text == "Page contents."

    async def test_caller_can_opt_out_of_text(self):
        """An explicit text=False is respected and still parses."""
        result, request_body = await run_search(
            CITATION_WITHOUT_TEXT, options={"text": False}
        )

        assert request_body["text"] is False
        assert isinstance(result, ContentText)
        assert result.citations is not None
        assert result.citations[0].cited_text is None

    async def test_missing_text_does_not_raise(self):
        """A citation without `text` must not fail validation.

        Regression test: `ExaCitation.text` was required, so every response
        raised ValidationError when text had not been requested.
        """
        result, _ = await run_search(CITATION_WITHOUT_TEXT)

        assert isinstance(result, ContentText)
        assert result.citations is not None
        assert result.citations[0].url == "https://example.com/1"

    async def test_default_survives_other_options(self):
        """Unrelated options don't displace the text default.

        Also pins that `max_connections` is an Inspect option and must not be
        forwarded to Exa.
        """
        result, request_body = await run_search(
            CITATION_WITH_TEXT, options={"model": "exa-pro", "max_connections": 5}
        )

        assert request_body == {
            "query": "test query",
            "model": "exa-pro",
            "text": True,
        }
        assert isinstance(result, ContentText)

    async def test_citation_with_only_required_fields(self):
        """Exa guarantees only url and title; the rest are conditional."""
        result, _ = await run_search(CITATION_MINIMAL)

        assert isinstance(result, ContentText)
        assert result.citations is not None
        assert result.citations[0].url == "https://example.com/1"
