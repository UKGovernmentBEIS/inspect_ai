from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    TypeAlias,
    TypedDict,
    Unpack,
    get_args,
)

from inspect_ai._util.deprecation import deprecation_warning
from inspect_ai.tool._tool_def import ToolDef

from ..._tool import Tool, ToolResult, tool
from ._google import GoogleOptions, google_search_provider, maybe_get_google_api_keys
from ._tavily import TavilyOptions, tavily_search_provider

Provider: TypeAlias = Literal["openai", "tavily", "google"]  # , "gemini", "anthropic"
valid_providers = set(get_args(Provider))


# It would have been nice if the values below were TypedDicts. The problem is
# that if the caller creates a literal dict variable (rather than passing the
# dict inline), the type checker will erase the type of the literal to something
# that doesn't conform the the required TypedDict when passed. This is lame, but
# we'll do runtime validation instead.
#
# If the caller uses this dict form and uses a value of `None`, it means that
# they want to use that provider and to use the default options.
class Providers(TypedDict, total=False):
    google: dict[str, Any] | None
    tavily: dict[str, Any] | None
    openai: dict[str, Any] | None


def test(providers: list[Provider | Providers]) -> None:
    pass


# test("google")
test(["google"])
test(["tavily", "google"])
test(["openai", {"tavily": {"max_results": 5}}])
test(["openai", {"tavily": None}])


class WebSearchDeprecatedArgs(TypedDict, total=False):
    provider: Literal["tavily", "google"] | None
    num_results: int | None
    max_provider_calls: int | None
    max_connections: int | None
    model: str | None


@tool
def web_search(
    providers: Provider | Providers | list[Provider | Providers],
    **deprecated_args: Unpack[WebSearchDeprecatedArgs],
) -> Tool:
    """Web search tool.

    A tool that can be registered for use by models to search the web. Use
    the `use_tools()` solver to make the tool available (e.g.
    `use_tools(web_search(provider="tavily"))`))

    A web search is conducted using the specified provider.
    - When using Tavily, all logic for relevance and summarization is handled by
    the Tavily API.
    - When using Google, the results are parsed for relevance using the specified
    model, and the top 'num_results' relevant pages are returned.

    See further documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-web-search>.

    Args:
      providers: Configuration for the search providers to use. Can be a list of provider names
        or a dictionary specifying provider options.
      **deprecated_args: Deprecated keyword arguments for backward compatibility, including:
        provider: DEPRECATED - use providers instead
        num_results: The number of search result pages used to provide information
          back to the model.
        max_provider_calls: Maximum number of search calls to make to the search
          provider.
        max_connections: Maximum number of concurrent connections to API endpoint
          of search provider.
        model: Model used to parse web pages for relevance - used only by the
          `google` provider.

    Returns:
       A tool that can be registered for use by models to search the web.
    """
    normalized_providers = _normalize_config(providers, **deprecated_args)

    search_provider: Callable[[str], Awaitable[str | None]] | None = None

    async def execute(query: str) -> ToolResult:
        """
        Use the web_search tool to perform keyword searches of the web.

        Args:
            query (str): Search query.
        """
        nonlocal search_provider
        if not search_provider:
            search_provider = _create_external_provider(normalized_providers)
        search_result = await search_provider(query)

        return (
            (
                "Here are your web search results. Please read them carefully as they may be useful later!\n"
                + search_result
            )
            if search_result
            else ("I'm sorry, I couldn't find any relevant information on the web.")
        )

    return ToolDef(
        execute, name="web_search", options=dict(normalized_providers)
    ).as_tool()


def _normalize_config(
    providers: Provider | Providers | list[Provider | Providers] | None,
    **deprecated_args: Unpack[WebSearchDeprecatedArgs],
) -> Providers:
    """
    Deal with breaking changes in the web_search parameter list.

    This function adapts (hopefully) all of the old variants of how the tool
    factory may have been called converts to the new config format.
    """
    # Cases to handle:
    # 1. Both deprecated_provider and providers are set
    #     ValueError
    # 2. Neither deprecated_provider nor providers is set
    #     Do the google_none_hack.
    #     if deprecated_provider is still none ValueError
    # - Only providers is set
    #     if any of the other deprecated parameters is set, then ValueError
    #     else Happy path
    # - Only deprecated_provider is set
    #     convert to new config format - including processing old other params

    deprecated_provider = deprecated_args.get("provider", None)
    # Case 1.
    if deprecated_provider and providers:
        raise ValueError("`provider` is deprecated. Please only specify `providers`.")

    # Case 2.
    if (
        providers is None
        and deprecated_provider is None
        and (deprecated_provider := _google_none_hack()) is None
    ):
        raise ValueError("`providers` must be specified.")

    num_results = deprecated_args.get("num_results", None)
    max_provider_calls = deprecated_args.get("max_provider_calls", None)
    max_connections = deprecated_args.get("max_connections", None)
    model = deprecated_args.get("model", None)

    # Getting here means that we have either a providers or a deprecated_provider
    if deprecated_provider:
        return _get_config_via_back_compat(
            deprecated_provider,
            num_results=num_results,
            max_provider_calls=max_provider_calls,
            max_connections=max_connections,
            model=model,
        )

    assert providers, "providers should not be None here"
    normalized: Providers = {}
    for entry in providers if isinstance(providers, list) else [providers]:
        if isinstance(entry, str):
            if entry not in valid_providers:
                raise ValueError(f"Invalid provider: '{entry}'")
            normalized[entry] = None  # type: ignore
        else:
            for key, value in entry.items():
                if key not in valid_providers:
                    raise ValueError(f"Invalid provider: '{key}'")
                normalized[key] = value  # type: ignore
    return normalized


def _google_none_hack() -> Literal["google"]:
    """If no config nor provider was set, infer 'google' if the API keys are set."""
    if maybe_get_google_api_keys():
        deprecation_warning(
            "The `google` `web_search` provider was inferred based on the presence of environment variables. Please specify the provider explicitly to avoid this warning."
        )
        return "google"
    else:
        raise ValueError(
            "Omitting `provider` is no longer supported. Please specify a `web_search` config explicitly to avoid this error."
        )


def _get_config_via_back_compat(
    provider: Literal["tavily", "google"],
    num_results: int | None,
    max_provider_calls: int | None,
    max_connections: int | None,
    model: str | None,
) -> Providers:
    if (
        num_results is None
        and max_provider_calls is None
        and max_connections is None
        and model is None
    ):
        return {"google": None} if provider == "google" else {"tavily": None}

    # If we get here, we have at least one old school parameter
    deprecation_warning(
        "The `num_results`, `max_provider_calls`, `max_connections`, and `model` parameters are deprecated. Please use the `config` parameter instead."
    )

    if provider == "google":
        return {
            "google": GoogleOptions(
                num_results=num_results,
                max_provider_calls=max_provider_calls,
                max_connections=max_connections,
                model=model,
            ).model_dump(exclude_none=True)
        }
    else:
        return {
            "tavily": TavilyOptions(
                max_results=num_results, max_connections=max_connections
            ).model_dump(exclude_none=True)
        }


def _create_external_provider(
    providers: Providers,
) -> Callable[[str], Awaitable[str | None]]:
    if tavily := providers.get("tavily", None):
        return tavily_search_provider(tavily)

    if google := providers.get("google", None):
        return google_search_provider(google)

    raise ValueError("No valid provider found.")
