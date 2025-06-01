from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    TypeAlias,
    TypedDict,
    get_args,
)

from typing_extensions import Unpack

from inspect_ai._util.deprecation import deprecation_warning
from inspect_ai.tool._tool_def import ToolDef

from ..._tool import Tool, ToolResult, tool
from ._google import GoogleOptions, google_search_provider
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


class WebSearchDeprecatedArgs(TypedDict, total=False):
    provider: Literal["tavily", "google"] | None
    num_results: int | None
    max_provider_calls: int | None
    max_connections: int | None
    model: str | None


@tool
def web_search(
    providers: Provider | Providers | list[Provider | Providers] | None = None,
    **deprecated: Unpack[WebSearchDeprecatedArgs],
) -> Tool:
    """Web search tool.

    Web searches are executed using a provider. Providers are split
    into two categories:

    - Internal providers: "openai" - these use the model's built-in search
      capability and do not require separate API keys. These work only for
      their respective model provider (e.g. the "openai" search provider
      works only for `openai/*` models).

    - External providers: "tavily" and "google". These are external services
      that work with any m odel and require separate accounts and API keys.

    Internal providers will be prioritized if running on the corresponding model
    (e.g., "openai" provider will be used when running on `openai` models). If an
    internal provider is specified but the evaluation is run with a different
    model, a fallback external provider must also be specified.

    See further documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-web-search>.

    Args:
      providers: Configuration for the search providers to use. Currently supported
        providers are "openai","tavily", and "google", The `providers` parameter
        supports several formats based on either a `str` specifying a provider or
        a `dict` whose keys are the provider names and whose values are the
        provider-specific options. A single value or a list of these can be passed.
        This arg is optional just for backwards compatibility. New code should
        always provide this argument.

        Single provider:
        ```
        web_search("tavily")
        web_search({"tavily": {"max_results": 5}})  # Tavily-specific options
        ```

        Multiple providers:
        ```
        # "openai" used for OpenAI models, "tavily" as fallback
        web_search(["openai", "tavily"])

        # The None value means to use the provider with default options
        web_search({"openai": None, "tavily": {"max_results": 5}}
        ```

        Mixed format:
        ```
        web_search(["openai", {"tavily": {"max_results": 5}}])
        ```

        When specified in the `dict` format, the `None` value for a provider means
        to use the provider with default options.

        Provider-specific options:
        - openai: Supports OpenAI's web search parameters.
          See https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses

        - tavily: Supports options like `max_results`, `search_depth`, etc.
          See https://docs.tavily.com/documentation/api-reference/endpoint/search

        - google: Supports options like `num_results`, `max_provider_calls`,
          `max_connections`, and `model`

      **deprecated: Deprecated arguments.

    Returns:
       A tool that can be registered for use by models to search the web.
    """
    normalized_providers = _normalize_config(providers, **deprecated)

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
    **deprecated: Unpack[WebSearchDeprecatedArgs],
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
    #     act as if they passed provider="google"
    # 3. Only providers is set
    #     if any of the other deprecated parameters is set, then ValueError
    #     else Happy path
    # 4. Only deprecated_provider is set
    #     convert to new config format - including processing old other params

    deprecated_provider = deprecated.get("provider", None)
    # Case 1.
    if deprecated_provider and providers:
        raise ValueError("`provider` is deprecated. Please only specify `providers`.")

    # Case 2.
    if providers is None and deprecated_provider is None:
        deprecated_provider = "google"

    num_results = deprecated.get("num_results", None)
    max_provider_calls = deprecated.get("max_provider_calls", None)
    max_connections = deprecated.get("max_connections", None)
    model = deprecated.get("model", None)

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
    if "tavily" in providers:
        return tavily_search_provider(providers.get("tavily", None))

    if "google" in providers:
        return google_search_provider(providers.get("google", None))

    raise ValueError("No valid provider found.")
