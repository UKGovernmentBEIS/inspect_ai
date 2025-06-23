from typing import Any, Literal

from pydantic import BaseModel, Field

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText

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


def tavily_search_provider(
    in_options: dict[str, object] | None = None,
) -> SearchProvider:
    options = TavilyOptions.model_validate(in_options) if in_options else None
    return TavilySearchProvider(
        options.model_dump(exclude_none=True) if options else None
    ).search
