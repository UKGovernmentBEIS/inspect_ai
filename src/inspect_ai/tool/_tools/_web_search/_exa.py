import os
from typing import Literal

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt
from inspect_ai.util._concurrency import concurrency

from ._web_search_provider import SearchProvider


class ExaOptions(BaseModel):
    # See https://docs.exa.ai/reference/answer
    text: bool | None = None
    """Whether to include text content in citations"""
    model: Literal["exa", "exa-pro"] | None = None
    """LLM model to use for generating the answer"""
    max_connections: int | None = None
    """max_connections is not an Exa API option, but an inspect option"""


class ExaCitation(BaseModel):
    id: str
    url: str
    title: str
    author: str | None = None
    publishedDate: str | None = None
    text: str


class ExaSearchResponse(BaseModel):
    answer: str
    citations: list[ExaCitation]


def exa_search_provider(
    in_options: dict[str, object] | None = None,
) -> SearchProvider:
    options = ExaOptions.model_validate(in_options) if in_options else None
    # Separate max_connections (which is an inspect thing) from the rest of the
    # options which will be passed in the request body
    max_connections = (options.max_connections if options else None) or 10
    api_options = (
        options.model_dump(exclude={"max_connections"}, exclude_none=True)
        if options
        else {}
    )
    # Default to including text if not specified
    if "text" not in api_options:
        api_options["text"] = True

    exa_api_key = os.environ.get("EXA_API_KEY", None)
    if not exa_api_key:
        raise PrerequisiteError(
            "EXA_API_KEY not set in the environment. Please ensure this variable is defined to use Exa with the web_search tool.\n\nLearn more about the Exa web search provider at https://inspect.aisi.org.uk/tools.html#exa-provider"
        )

    # Create the client within the provider
    client = httpx.AsyncClient(timeout=30)

    async def search(query: str) -> str | ContentText | None:
        # See https://docs.exa.ai/reference/answer
        search_url = "https://api.exa.ai/answer"
        headers = {
            "x-api-key": exa_api_key,
            "Content-Type": "application/json",
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

        async with concurrency("exa_web_search", max_connections):
            exa_search_response = ExaSearchResponse.model_validate(
                (await _search()).json()
            )

            if not exa_search_response.answer and not exa_search_response.citations:
                return None

            return ContentText(
                text=exa_search_response.answer,
                citations=[
                    UrlCitation(
                        cited_text=citation.text, title=citation.title, url=citation.url
                    )
                    for citation in exa_search_response.citations
                ],
            )

    return search
