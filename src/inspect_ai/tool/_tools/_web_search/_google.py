import os
from typing import Awaitable, Callable

import anyio
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
from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt
from inspect_ai.util._concurrency import concurrency

DEFAULT_RELEVANCE_PROMPT = """I am trying to answer the following question and need to find the most relevant information on the web. Please let me know if the following content is relevant to the question or not. You should just respond with "yes" or "no".

Question: {question}
Page Content: {text}
"""


class SearchLink:
    def __init__(self, url: str, snippet: str) -> None:
        self.url = url
        self.snippet = snippet


def maybe_get_google_api_keys() -> tuple[str, str] | None:
    """
    Get Google API keys from environment variables.

    Returns:
        tuple: A tuple containing the Google API key and the Google CSE ID.
    """
    google_api_key = os.environ.get("GOOGLE_CSE_API_KEY", None)
    google_cse_id = os.environ.get("GOOGLE_CSE_ID", None)
    return (google_api_key, google_cse_id) if google_api_key and google_cse_id else None


def google_search_provider(
    num_results: int,
    max_provider_calls: int,
    max_connections: int,
    model: str | None,
) -> Callable[[str], Awaitable[str | None]]:
    keys = maybe_get_google_api_keys()
    if not keys:
        raise PrerequisiteError(
            "GOOGLE_CSE_ID and/or GOOGLE_CSE_API_KEY not set in the environment. Please ensure these variables are defined to use Google Custom Search with the web_search tool.\n\nLearn more about the Google web search provider at https://inspect.aisi.org.uk/tools.html#google-provider"
        )
    google_api_key, google_cse_id = keys

    # Create the client within the provider
    client = httpx.AsyncClient()

    async def search(query: str) -> str | None:
        # limit number of concurrent searches
        page_contents: list[str] = []
        urls: list[str] = []
        snippets: list[str] = []
        search_calls = 0

        # Paginate through search results until we have successfully extracted num_results pages or we have reached max_provider_calls
        while len(page_contents) < num_results and search_calls < max_provider_calls:
            async with concurrency("google_web_search", max_connections):
                links = await _search(query, start_idx=search_calls * 10)

            async with anyio.create_task_group() as tg:

                async def process_link(link: SearchLink) -> None:
                    try:
                        page = await page_if_relevant(link.url, query, model, client)
                        if page:
                            page_contents.append(page)
                            urls.append(link.url)
                            snippets.append(link.snippet)
                    # exceptions fetching pages are very common!
                    except Exception:
                        pass

                for lk in links:
                    tg.start_soon(process_link, lk)

            search_calls += 1

        all_page_contents = "\n\n".join(page_contents)
        return None if all_page_contents == "" else all_page_contents

    async def _search(query: str, start_idx: int) -> list[SearchLink]:
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
            before_sleep=log_httpx_retry_attempt(search_url),
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
