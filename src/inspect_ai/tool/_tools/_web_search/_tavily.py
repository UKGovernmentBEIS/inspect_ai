from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.tool._tool import ToolError

from ._base_http_provider import BaseHttpProvider
from ._web_search_provider import SearchProvider


class TavilyOptions(BaseModel):
    topic: Literal["general", "news"] | None = None
    search_depth: Literal["basic", "advanced"] | None = None
    chunks_per_source: Literal[1, 2, 3] | None = None
    max_results: int | None = None
    time_range: Literal["day", "week", "month", "year", "d", "w", "m", "y"] | None = (
        None
    )
    days: int | None = None
    include_answer: bool | Literal["basic", "advanced"] | None = None
    include_raw_content: bool | None = None
    include_images: bool | None = None
    include_image_descriptions: bool | None = None
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None
    # max_connections is not a Tavily API option, but an inspect option
    max_connections: int | None = None


class TavilySearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float


class TavilySearchResponse(BaseModel):
    query: str
    answer: str | None = Field(default=None)
    images: list[object]
    results: list[TavilySearchResult]
    response_time: float


class TavilySearchProvider(BaseHttpProvider):
    """Tavily-specific implementation of HttpSearchProvider."""

    def __init__(self, options: dict[str, Any] | None = None):
        super().__init__(
            env_key_name="TAVILY_API_KEY",
            api_endpoint="https://api.tavily.com/search",
            provider_name="Tavily",
            concurrency_key="tavily_web_search",
            options=options,
        )

    def prepare_headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
        }

    def set_default_options(self, options: dict[str, Any]) -> dict[str, Any]:
        # Force inclusion of answer if not specified
        new_options = options.copy()
        new_options["include_answer"] = True
        return new_options

    async def search(self, query: str) -> ContentText | None:
        """Execute a search, converting query-too-long 400s to ToolError."""
        try:
            return await super().search(query)
        except httpx.HTTPStatusError as ex:
            if ex.response.status_code == 400:
                detail = _is_query_too_long_error(ex)
                if detail:
                    raise ToolError(detail) from ex
            raise

    def parse_response(self, response_data: dict[str, Any]) -> ContentText | None:
        tavily_search_response = TavilySearchResponse.model_validate(response_data)

        if not tavily_search_response.results and not tavily_search_response.answer:
            return None

        return ContentText(
            text=tavily_search_response.answer or "No answer found.",
            citations=[
                UrlCitation(
                    cited_text=result.content, title=result.title, url=result.url
                )
                for result in tavily_search_response.results
            ],
        )


_QUERY_TOO_LONG = "query is too long"


def _is_query_too_long_error(ex: httpx.HTTPStatusError) -> str | None:
    """Check if a Tavily 400 is a query-too-long error.

    Returns the error message if it matches, or None otherwise.
    """
    try:
        body = ex.response.json()
        detail = body.get("detail", {})
        if isinstance(detail, dict):
            message = detail.get("error", "")
        elif isinstance(detail, str):
            message = detail
        else:
            return None
        if _QUERY_TOO_LONG in message.lower():
            return message
    except Exception:
        pass
    return None


def tavily_search_provider(
    in_options: dict[str, object] | None = None,
) -> SearchProvider:
    options = TavilyOptions.model_validate(in_options) if in_options else None
    return TavilySearchProvider(
        options.model_dump(exclude_none=True) if options else None
    ).search
