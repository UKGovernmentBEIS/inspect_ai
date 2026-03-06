from typing import (
    Any,
    Literal,
    TypeAlias,
    TypedDict,
    get_args,
)

from typing_extensions import Unpack

from inspect_ai._util.deprecation import deprecation_warning
from inspect_ai.tool._tool_def import ToolDef

from ..._tool import Tool, ToolResult, tool
from ._exa import ExaOptions, exa_search_provider
from ._google import GoogleOptions, google_search_provider, maybe_get_google_api_keys
from ._tavily import TavilyOptions, tavily_search_provider
from ._web_search_provider import SearchProvider

WebSearchProvider: TypeAlias = Literal[
    "grok",
    "gemini",
    "openai",
    "anthropic",
    "mistral",
    "perplexity",
    "tavily",
    "google",
    "exa",
]
valid_providers = set(get_args(WebSearchProvider))


# It would have been nice if the values below were TypedDicts. The problem is
# that if the caller creates a literal dict variable (rather than passing the
# dict inline), the type checker will erase the type of the literal to something
# that doesn't conform the the required TypedDict when passed. This is lame, but
# we'll do runtime validation instead.
#
# If the caller uses this dict form and uses a value of `None`, it means that
# they want to use that provider and to use the default options.
class WebSearchProviders(TypedDict, total=False):
    """Provider configuration for `web_search()` tool.

    The `web_search()` tool provides models the ability to enhance their context window by performing a search. Web searches are executed using a provider. Providers are split into two categories:

    -   Internal providers: `"openai"`, `"anthropic"`, `"gemini"`, `"grok"`, `mistral`, and `"perplexity"` - these use the model's built-in search capability and do not require separate API keys. These work only for their respective model provider (e.g. the "openai" search provider works only for `openai/*` models).

    -   External providers: `"tavily"`, `"exa"`, and `"google"`. These are external services that work with any model and require separate accounts and API keys. Note that "google" is different from "gemini" - "google" refers to Google's Programmable Search Engine service, while "gemini" refers to Google's built-in search capability for Gemini models.

    By default, all internal providers are enabled if there are no external providers defined.
    If an external provider is defined then you need to explicitly enable internal providers
    that you want to use.

    Internal providers will be prioritized if running on the corresponding model (e.g., "openai" provider will be used when running on `openai` models). If an internal provider is specified but the evaluation is run with a different model, a fallback external provider must also be specified.
    """

    openai: dict[str, Any] | bool
    """Use OpenAI internal provider. For available options see <https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses>."""

    anthropic: dict[str, Any] | bool
    """Use Anthropic internal provider. For available options see <https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool>."""

    grok: dict[str, Any] | bool
    """Use Grok internal provider. For available options see <https://docs.x.ai/docs/guides/tools/search-tools#web-search-parameters>."""

    gemini: dict[str, Any] | bool
    """Use Gemini internal provider. For available options see <https://ai.google.dev/gemini-api/docs/google-search>."""

    mistral: dict[str, Any] | bool
    """Use Mistral internal provider. For available options see <https://docs.mistral.ai/agents/tools/built-in/websearch>."""

    perplexity: dict[str, Any] | bool
    """Use Perplexity internal provider. For available options see <https://docs.perplexity.ai/api-reference/chat-completions-post>"""

    tavily: dict[str, Any] | bool
    """Use Tavili external provider. For available options see <Use Exa external provider. For available options see <https://inspect.aisi.org.uk/tools-standard.html#tavili-options>."""

    google: dict[str, Any] | bool
    """Use Google external provider. For available options see <https://inspect.aisi.org.uk/tools-standard.html#google-options>."""

    exa: dict[str, Any] | bool
    """Use Exa external provider. For available options see <https://inspect.aisi.org.uk/tools-standard.html#exa-options>."""


class _NormalizedProviders(TypedDict, total=False):
    openai: dict[str, Any]
    anthropic: dict[str, Any]
    grok: dict[str, Any]
    gemini: dict[str, Any]
    mistral: dict[str, Any]
    perplexity: dict[str, Any]
    tavily: dict[str, Any]
    google: dict[str, Any]
    exa: dict[str, Any]


class WebSearchDeprecatedArgs(TypedDict, total=False):
    provider: Literal["tavily", "google"] | None
    num_results: int | None
    max_provider_calls: int | None
    max_connections: int | None
    model: str | None


@tool
def web_search(
    providers: WebSearchProvider
    | WebSearchProviders
    | list[WebSearchProvider | WebSearchProviders]
    | None = None,
    **deprecated: Unpack[WebSearchDeprecatedArgs],
) -> Tool:
    """Web search tool.

    Web searches are executed using a provider. Providers are split
    into two categories:

    - Internal providers: "openai", "anthropic", "grok", "gemini", "mistral", "perplexity".
      These use the model's built-in search capability and do not require separate
      API keys. These work only for their respective model provider (e.g. the
      "openai" search provider works only for `openai/*` models).

    - External providers: "tavily", "google", and "exa". These are external services
      that work with any model and require separate accounts and API keys.

    By default, all internal providers are enabled if there are no external providers defined.
    If an external provider is defined then you need to explicitly enable internal providers
    that you want to use.

    Internal providers will be prioritized if running on the corresponding model
    (e.g., "openai" provider will be used when running on `openai` models). If an
    internal provider is specified but the evaluation is run with a different
    model, a fallback external provider must also be specified.

    See further documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-web-search>.

    Args:
      providers: Configuration for the search providers to use. Currently supported
        providers are "openai", "anthropic", "perplexity", "tavily", "gemini", "mistral", "grok",
        "google", and "exa". The `providers` parameter supports several formats
        based on either a `str` specifying a provider or a `dict` whose keys are
        the provider names and whose values are the provider-specific options. A
        single value or a list of these can be passed.

        Use built-in search for all providers:
        ```
        web_search()
        ```

        Single external provider:
        ```
        web_search("tavily")
        web_search({"tavily": {"max_results": 5}})  # Tavily-specific options
        ```

        Multiple providers:
        ```
        # "openai" used for OpenAI models, "tavily" for other models
        web_search(["openai", "tavily"])

        # The True value means to use the provider with default options
        web_search({"openai": True, "tavily": {"max_results": 5}}
        ```

        Mixed format:
        ```
        web_search(["openai", "anthropic", {"tavily": {"max_results": 5}}])
        ```

        When specified in the `dict` format, the `None` value for a provider means
        to use the provider with default options.

        Provider-specific options:
        - openai: Supports OpenAI's web search parameters.
          See https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses

        - anthropic: Supports Anthropic's web search parameters.
          See https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool#tool-definition

        - perplexity: Supports Perplexity's web search parameters.
          See https://docs.perplexity.ai/api-reference/chat-completions-post

        - tavily: Supports options like `max_results`, `search_depth`, etc.
          See https://docs.tavily.com/documentation/api-reference/endpoint/search

        - exa: Supports options like `text`, `model`, etc.
          See https://docs.exa.ai/reference/answer

        - google: Supports options like `num_results`, `max_provider_calls`,
          `max_connections`, and `model`

        - grok: Supports X-AI's live search parameters.
          See https://docs.x.ai/docs/guides/live-search#live-search

      **deprecated: Deprecated arguments.

    Returns:
       A tool that can be registered for use by models to search the web.
    """
    normalized_providers = _normalize_config(providers, **deprecated)

    search_provider: SearchProvider | None = None

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

        # This is gunky here because ToolResult is typed with a List rather than
        # a Sequence, and Lists are variant (rather than covariant). This means
        # it's illegal to assign a List of a narrower type to a List of a broader
        # type. By making a copy of the list and not capturing an alias to it,
        # mypy knows it's safe.
        return (
            list(search_result)
            if isinstance(search_result, list)
            else search_result
            if search_result is not None
            else "I couldn't find any relevant information on the web."
        )

    return ToolDef(
        execute, name="web_search", options=dict(normalized_providers)
    ).as_tool()


def _normalize_config(
    providers: WebSearchProvider
    | WebSearchProviders
    | list[WebSearchProvider | WebSearchProviders]
    | None,
    **deprecated: Unpack[WebSearchDeprecatedArgs],
) -> _NormalizedProviders:
    """
    Deal with breaking changes in the web_search parameter list.

    This function adapts (hopefully) all of the old variants of how the tool
    factory may have been called converts to the new config format.
    """
    # Cases to handle:
    # 1. Both deprecated_provider and providers are set
    #     ValueError
    # 2. Neither is set and google env vars are defined
    #     act as if they passed provider="google"
    # 3. Only providers is set
    #     if any of the other deprecated parameters is set, then ValueError
    #     else Happy path
    # 4. Only deprecated_provider is set
    #     convert to new config format - including processing old other params

    # can't use both provider and providers
    deprecated_provider = deprecated.get("provider", None)
    if deprecated_provider and providers:
        raise ValueError("`provider` is deprecated. Please only specify `providers`.")

    # no providers but google env vars are set
    if (
        providers is None
        and deprecated_provider is None
        and maybe_get_google_api_keys() is not None
    ):
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

    # normalize providers to list
    providers = providers or []
    providers = providers if isinstance(providers, list) else [providers]

    # determine default -- if there is at least one external provider then
    # internal providers are disabled by default, otherwise they are enabled
    if _has_external_provider(providers):
        normalized: _NormalizedProviders = {}
    else:
        normalized = {
            "openai": {},
            "anthropic": {},
            "grok": {},
            "gemini": {},
            "mistral": {},
            "perplexity": {},
        }
    for entry in providers:
        if isinstance(entry, str):
            if entry not in valid_providers:
                raise ValueError(f"Invalid provider: '{entry}'")
            normalized[entry] = {}  # type: ignore
        else:
            for key, value in entry.items():
                if key not in valid_providers:
                    raise ValueError(f"Invalid provider: '{key}'")

                if not isinstance(value, dict | bool) and value is not None:
                    raise ValueError(
                        f"Invalid value for provider '{key}': {value}. Expected a dict, bool, or None"
                    )
                if value is False:
                    normalized.pop(key, None)  # type: ignore[misc]
                else:
                    normalized[key] = value if isinstance(value, dict) else {}  # type: ignore
    return normalized


EXTERNAL_PROVIDERS = ["tavily", "google", "exa"]


def _has_external_provider(
    providers: list[WebSearchProvider | WebSearchProviders],
) -> bool:
    for provider in providers:
        if isinstance(provider, str):
            if provider in EXTERNAL_PROVIDERS:
                return True
        elif isinstance(provider, dict):
            for key in provider.keys():
                if key in EXTERNAL_PROVIDERS and provider[key] is not False:  # type: ignore[literal-required]
                    return True

    return False


def _get_config_via_back_compat(
    provider: Literal["tavily", "google", "exa"],
    num_results: int | None,
    max_provider_calls: int | None,
    max_connections: int | None,
    model: str | None,
) -> _NormalizedProviders:
    if (
        num_results is None
        and max_provider_calls is None
        and max_connections is None
        and model is None
    ):
        if provider == "google":
            return {"google": {}}
        elif provider == "exa":
            return {"exa": {}}
        else:
            return {"tavily": {}}

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
    elif provider == "exa":
        return {
            "exa": ExaOptions(max_connections=max_connections).model_dump(
                exclude_none=True
            )
        }
    else:
        return {
            "tavily": TavilyOptions(
                max_results=num_results, max_connections=max_connections
            ).model_dump(exclude_none=True)
        }


def _create_external_provider(
    providers: _NormalizedProviders,
) -> SearchProvider:
    if "tavily" in providers:
        return tavily_search_provider(providers.get("tavily"))

    if "exa" in providers:
        return exa_search_provider(providers.get("exa"))

    if "google" in providers:
        return google_search_provider(providers.get("google"))

    raise ValueError("No valid provider found.")
