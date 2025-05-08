from typing import Literal

import httpx

from inspect_ai._util.deprecation import deprecation_warning

from ..._tool import Tool, ToolResult, tool
from ._google import google_search_provider, maybe_get_google_api_keys
from ._tavily import tavily_search_provider


@tool
def web_search(
    provider: Literal["google", "tavily"] | None,
    num_results: int = 3,
    max_provider_calls: int = 3,
    max_connections: int = 10,
    model: str | None = None,
) -> Tool:
    """Web search tool.

    A tool that can be registered for use by models to search the web. Use
    the `use_tools()` solver to make the tool available (e.g.
    `use_tools(web_search(provider="tavily"))`))

    A web search is conducted using the specified provider.
    - With `google`, the results are parsed for relevance using the specified model,
    and the top 'num_results' relevant pages are returned.
    - With `tavily`, all logic for relevance and summarization is handled by the
    provider itself.

    See further documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-web-search>.

    Args:
      provider: Search provider to use:
        - "google": Uses Google Custom Search.
        - "tavily": Uses Tavily's LLM tailored search engine.
        Note: The `| None` type is only for backwards compatibility. Passing `None` is deprecated.
      num_results: Number of web search result pages to return to the model.
      max_provider_calls: Maximum number of search calls to make to the search provider.
      max_connections: Maximum number of concurrent connections to API
        endpoint of search provider.
      model: Model used to parse web pages for relevance - used only by the
      `google` provider.

    Returns:
       A tool that can be registered for use by models to search the web.
    """
    if provider is None:
        if maybe_get_google_api_keys():
            deprecation_warning(
                "The `google` `web_search` provider was inferred based on the presence of environment variables. Please specify the provider explicitly to avoid this warning."
            )
            provider = "google"
        else:
            raise ValueError(
                "Omitting `provider` is no longer supported. Please specify the `web_search` provider explicitly to avoid this error."
            )

    search_provider = (
        google_search_provider(num_results, max_provider_calls, max_connections, model)
        if provider == "google"
        else tavily_search_provider(num_results, max_connections)
    )

    # resolve provider (only google for now)
    async def execute(query: str) -> ToolResult:
        """
        Use the web_search tool to perform keyword searches of the web.

        Args:
            query (str): Search query.
        """
        search_result = await search_provider(query)

        return (
            (
                "Here are your web search results. Please read them carefully as they may be useful later!\n"
                + search_result
            )
            if search_result
            else ("I'm sorry, I couldn't find any relevant information on the web.")
        )

    return execute
