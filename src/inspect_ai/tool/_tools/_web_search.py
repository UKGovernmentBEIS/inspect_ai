import asyncio
import os
from typing import Literal, Protocol, cast, runtime_checkable

import httpx
from bs4 import BeautifulSoup, NavigableString
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.retry import httpx_should_retry, log_retry_attempt
from inspect_ai.util._concurrency import concurrency

from .._tool import Tool, ToolResult, tool

DEFAULT_RELEVANCE_PROMPT = """I am trying to answer the following question and need to find the most relevant information on the web. Please let me know if the following content is relevant to the question or not. You should just respond with "yes" or "no".

Question: {question}
Page Content: {text}
"""


@tool
def web_search(
    provider: Literal["google"] = "google",
    num_results: int = 3,
    max_provider_calls: int = 3,
    max_connections: int = 10,
    model: str | None = None,
) -> Tool:
    """Web search tool.

    A tool that can be registered for use by models to search the web. Use
    the `use_tools()` solver to make the tool available (e.g. `use_tools(web_search())`))

    A web search is conducted using the specified provider, the results are parsed for relevance
    using the specified model, and the top 'num_results' relevant pages are returned.

    Args:
      provider (Literal["google"]): Search provider (defaults to "google", currently
        the only provider). Possible future providers include "brave" and "bing".
      num_results (int): Number of web search result pages to return to the model.
      max_provider_calls (int): Maximum number of search calls to make to the search provider.
      max_connections (int): Maximum number of concurrent connections to API
        endpoint of search provider.
      model (str | Model): Model used to parse web pages for relevance.

    Returns:
       A tool that can be registered for use by models to search the web.
    """
    # get search client
    client = httpx.AsyncClient()

    if provider == "google":
        search_provider = google_search_provider(client)
    else:
        raise ValueError(
            f"Provider {provider} not supported. Only 'google' is supported."
        )

    # resolve provider (only google for now)
    async def execute(query: str) -> ToolResult:
        """
        Use the web_search tool to perform keyword searches of the web.

        Args:
            query (str): Search query.
        """
        # limit number of concurrent searches
        page_contents: list[str] = []
        urls: list[str] = []
        snippets: list[str] = []
        search_calls = 0

        # Paginate through search results until we have successfully extracted num_results pages or we have reached max_provider_calls
        while len(page_contents) < num_results and search_calls < max_provider_calls:
            async with concurrency(f"{provider}_web_search", max_connections):
                links = await search_provider(query, start_idx=search_calls * 10)

            # Extract and summarize each page individually
            pages = await asyncio.gather(
                *[page_if_relevant(link.url, query, model, client) for link in links],
                return_exceptions=True,
            )
            for page, link in zip(pages, links):
                if page and not isinstance(page, Exception):
                    page_contents.append(cast(str, page))
                    urls.append(link.url)
                    snippets.append(link.snippet)
            search_calls += 1

        all_page_contents = "\n\n".join(page_contents)
        if all_page_contents == "":
            response: ToolResult = (
                "I'm sorry, I couldn't find any relevant information on the web."
            )
        else:
            response = (
                "Here are your web search results. Please read them carefully as they may be useful later! "
                + all_page_contents
            )

        return response

    return execute


async def page_if_relevant(
    link: str, query: str, relevance_model: str | None, client: httpx.AsyncClient
) -> str | None:
    """
    Use parser model to determine if a web page contents is relevant to a query.

    Args:
        link (str): Web page link.
        query (str): Search query.
        relevance_model (Model): Model used to parse web pages for relevance.
        client: (httpx.Client): HTTP client to use to fetch the page

    Returns:
        str: Web page contents if relevant, else None.
    """
    # resolve model
    from inspect_ai.model._model import get_model

    model = get_model(relevance_model)

    # retrieve document
    try:
        response = await client.get(link)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise Exception(f"HTTP error occurred: {exc}")

    # parse it
    encoding_scheme = response.encoding or "utf-8"
    soup = BeautifulSoup(response.content.decode(encoding_scheme), "html.parser")

    main_content = soup.find("main") or soup.find("body") or soup
    if not isinstance(main_content, NavigableString):
        paragraphs = main_content.find_all("p")
        full_text = ""
        for p in paragraphs:
            full_text += p.get_text(strip=True, separator=" ")
            if len(full_text.split()) > 2000:
                break
    else:
        full_text = " ".join(
            main_content.get_text(strip=True, separator=" ").split()[:2000]
        )

    is_relevant = (
        await model.generate(
            DEFAULT_RELEVANCE_PROMPT.format(question=query, text=full_text)
        )
    ).message.text

    if "yes" in is_relevant.lower():
        return full_text
    else:
        return None


class SearchLink:
    def __init__(self, url: str, snippet: str) -> None:
        self.url = url
        self.snippet = snippet


@runtime_checkable
class SearchProvider(Protocol):
    async def __call__(self, query: str, start_idx: int) -> list[SearchLink]: ...


def google_search_provider(client: httpx.AsyncClient) -> SearchProvider:
    google_api_key = os.environ.get("GOOGLE_CSE_API_KEY", None)
    google_cse_id = os.environ.get("GOOGLE_CSE_ID", None)
    if not google_api_key or not google_cse_id:
        raise PrerequisiteError(
            "GOOGLE_CSE_ID and/or GOOGLE_CSE_API_KEY not set in the environment. Please ensure these variables are defined to use Google Custom Search with the web_search tool.\n\nLearn more about the Google web search provider at https://inspect.ai-safety-institute.org.uk/tools.html#google-provider"
        )

    async def search(query: str, start_idx: int) -> list[SearchLink]:
        # List of allowed parameters can be found https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list
        search_params = {
            "q": query,
            "key": google_api_key,
            "cx": google_cse_id,
            "start": start_idx,
        }
        search_url = "https://www.googleapis.com/customsearch/v1?" + "&".join(
            [f"{key}={value}" for key, value in search_params.items()]
        )

        # retry up to 5 times over a period of up to 1 minute
        @retry(
            wait=wait_exponential_jitter(),
            stop=stop_after_attempt(5) | stop_after_delay(60),
            retry=retry_if_exception(httpx_should_retry),
            before_sleep=log_retry_attempt(search_url),
        )
        async def execute_search() -> httpx.Response:
            return await client.get(search_url)

        result = await execute_search()
        data = result.json()

        if "items" in data:
            return [SearchLink(item["link"], item["snippet"]) for item in data["items"]]
        else:
            return []

    return search
