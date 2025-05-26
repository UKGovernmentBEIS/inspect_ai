import os
from typing import Awaitable, Callable, Literal

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt
from inspect_ai.util._concurrency import concurrency


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


def tavily_search_provider(
    in_options: dict[str, object] | None = None,
) -> Callable[[str], Awaitable[str | None]]:
    options = TavilyOptions.model_validate(in_options) if in_options else None
    # Separate max_connections (which is an inspect thing) from the rest of the
    # options which will be passed in the request body
    max_connections = (options.max_connections if options else None) or 10
    api_options = (
        options.model_dump(exclude={"max_connections"}, exclude_none=True)
        if options
        else {}
    )
    if not api_options.get("include_answer", False):
        api_options["include_answer"] = True

    tavily_api_key = os.environ.get("TAVILY_API_KEY", None)
    if not tavily_api_key:
        raise PrerequisiteError(
            "TAVILY_API_KEY not set in the environment. Please ensure ths variable is defined to use Tavily with the web_search tool.\n\nLearn more about the Tavily web search provider at https://inspect.aisi.org.uk/tools.html#tavily-provider"
        )

    # Create the client within the provider
    client = httpx.AsyncClient(timeout=30)

    async def search(query: str) -> str | None:
        search_url = "https://api.tavily.com/search"
        headers = {
            "Authorization": f"Bearer {tavily_api_key}",
        }

        body = {"query": query, **api_options}

        # retry up to 5 times over a period of up to 1 minute
        @retry(
            wait=wait_exponential_jitter(),
            stop=stop_after_attempt(5) | stop_after_delay(60),
            retry=retry_if_exception(httpx_should_retry),
            before_sleep=log_httpx_retry_attempt(search_url),
        )
        async def _search() -> httpx.Response:
            response = await client.post(search_url, headers=headers, json=body)
            response.raise_for_status()
            return response

        async with concurrency("tavily_web_search", max_connections):
            return TavilySearchResponse.model_validate((await _search()).json()).answer

    return search
