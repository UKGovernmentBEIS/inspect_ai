from typing import (
    Awaitable,
    Callable,
    Literal,
    Tuple,
    TypeAlias,
    cast,
)

from inspect_ai._util.deprecation import deprecation_warning
from inspect_ai.tool._tool_def import ToolDef

from ..._tool import Tool, ToolResult, tool
from ._google import GoogleOptions, google_search_provider, maybe_get_google_api_keys
from ._model_options import OpenAIOptions
from ._tavily import TavilyOptions, tavily_search_provider

ModelInternalOptions: TypeAlias = dict[str, OpenAIOptions]
"""Model provider -> model specific web search options. (Currently only OpenAI)"""


InternalConfig: TypeAlias = Tuple[Literal["internal"], ModelInternalOptions]
"""This config part indicates the desire to use the model's internal web search, if available."""

InspectConfig: TypeAlias = (
    Tuple[Literal["tavily"], TavilyOptions | None]
    | Tuple[Literal["google"], GoogleOptions | None]
)
"""This config part indicates which Inspect implemented provider to use."""

ConfigType: TypeAlias = InspectConfig | Tuple[InternalConfig, InspectConfig]
"""
Complete type that specifies how the web_search provider should be chosen.

Some models (e.g. OpenAI) have their own internal web search provider. To use the
model implementation, the config must be a tuple with two elements. The first
element specifies the "internal" provider name and optional a dictionary of any
model specific options. The second element specifies the Inspect implemented
provider to fall back to in case the model used for the eval does not have
an internal provider.
"""


@tool
def web_search(
    provider: Literal["tavily", "google"] | None = None,
    config: ConfigType | None = None,
    # These four parameters are for backwards compatibility and are deprecated.
    num_results: int | None = None,
    max_provider_calls: int | None = None,
    max_connections: int | None = None,
    model: str | None = None,
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
      provider: Search provider to use:
        - "tavily": Uses Tavily's Research API.
        - "google": Uses Google Custom Search.
        Note: The `| None` type is only for backwards compatibility. Passing
        `None` is deprecated.
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
    use_internal, internal_options, inspect_config = _normalize_config(
        provider,
        config,
        num_results=num_results,
        max_provider_calls=max_provider_calls,
        max_connections=max_connections,
        model=model,
    )

    search_provider: Callable[[str], Awaitable[str | None]] | None

    async def execute(query: str) -> ToolResult:
        """
        Use the web_search tool to perform keyword searches of the web.

        Args:
            query (str): Search query.
        """
        nonlocal search_provider
        if not search_provider:
            search_provider = (
                google_search_provider(inspect_config[1])
                if inspect_config[0] == "google"
                else tavily_search_provider(inspect_config[1])
            )

        search_result = await search_provider(query)

        return (
            (
                "Here are your web search results. Please read them carefully as they may be useful later!\n"
                + search_result
            )
            if search_result
            else ("I'm sorry, I couldn't find any relevant information on the web.")
        )

    return (
        ToolDef(
            execute,
            name="web_search",  # TODO: Does this need to be specified?
            options={
                "use_internal": True,
                "internal_options": internal_options,
            },
        ).as_tool()
        if use_internal
        else execute
    )


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


def _normalize_config(
    provider: Literal["tavily", "google"] | None,
    config: ConfigType | None,
    num_results: int | None,
    max_provider_calls: int | None,
    max_connections: int | None,
    model: str | None,
) -> Tuple[bool, ModelInternalOptions | None, InspectConfig]:
    """
    Deal with breaking changes in the web_search parameter list.

    This function adapts (hopefully) all of the old variants of how the tool
    factory may have been called converts to the new config format.
    """
    # Cases to handle:
    # - Neither provider nor config is set
    #     Do the google_none_hack.
    #     if provider is still none ValueError
    # - Both provider and config are set
    #     ValueError
    # - Only config is set
    #     if any of the other parameters are set, then ValueError
    #     else Happy path
    # - Only provider is set
    #     convert to new config format - including processing old other params

    if (
        config is None
        and provider is None
        and (provider := _google_none_hack()) is None
    ):
        raise ValueError("`config` must be specified.")

    elif provider is not None and config is not None:
        raise ValueError("`provider` is deprecated. Please specify `config`.")

    # Getting here means that we have either a config or a provider
    if config is None:
        assert provider is not None, "provider should not be None here"
        config = _get_config_via_back_compat(
            provider,
            num_results=num_results,
            max_provider_calls=max_provider_calls,
            max_connections=max_connections,
            model=model,
        )

    # Pardon the cast's. The inference engine couldn't hack it
    match config[0]:
        case "tavily" | "google":
            return (False, None, cast(InspectConfig, config))
        case _:
            return (True, config[0][1], cast(InspectConfig, config[1]))


def _get_config_via_back_compat(
    provider: Literal["tavily", "google"],
    num_results: int | None,
    max_provider_calls: int | None,
    max_connections: int | None,
    model: str | None,
) -> ConfigType:
    if (
        num_results is not None
        or max_provider_calls is not None
        or max_connections is not None
        or model is not None
    ):
        deprecation_warning(
            "The `num_results`, `max_provider_calls`, `max_connections`, and `model` parameters are deprecated. Please use the `config` parameter instead."
        )
    else:
        return ("google", None) if provider == "google" else ("tavily", None)

    return (
        (
            "google",
            GoogleOptions(
                num_results=num_results,
                max_provider_calls=max_provider_calls,
                max_connections=max_connections,
                model=model,
            ),
        )
        if provider == "google"
        else (
            "tavily",
            TavilyOptions(
                num_results=num_results,
                max_connections=max_connections,
            ),
        )
    )
