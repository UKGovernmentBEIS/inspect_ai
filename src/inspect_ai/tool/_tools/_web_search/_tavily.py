import os
from typing import Awaitable, Callable

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
    num_results: int, max_connections: int
) -> Callable[[str], Awaitable[str | None]]:
    tavily_api_key = os.environ.get("TAVILY_API_KEY", None)
    if not tavily_api_key:
        raise PrerequisiteError(
            "TAVILY_API_KEY not set in the environment. Please ensure ths variable is defined to use Tavily with the web_search tool.\n\nLearn more about the Tavily web search provider at https://inspect.aisi.org.uk/tools.html#tavily-provider"
        )
    if num_results > 20:
        raise PrerequisiteError(
            "The Tavily search provider is limited to 20 results per query."
        )

    # Create the client within the provider
    client = httpx.AsyncClient(timeout=30)

    async def search(query: str) -> str | None:
        search_url = "https://api.tavily.com/search"
        headers = {
            "Authorization": f"Bearer {tavily_api_key}",
        }
        body = {
            "query": query,
            "max_results": 10,  # num_results,
            # "search_depth": "advanced",
            "include_answer": "advanced",
        }

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
