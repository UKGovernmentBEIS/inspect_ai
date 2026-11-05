from typing import Any

from openai._types import NOT_GIVEN
from openai.types.responses import (
    Response,
    ResponseOutputItem,
    ResponseOutputMessage,
)
from typing_extensions import override

from inspect_ai._util.citation import Citation, UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.openai_responses import generate_responses
from inspect_ai.tool import ToolChoice, ToolFunction, ToolInfo

from .._chat_message import ChatMessage
from .._model_call import ModelCall

# Sonar models that Perplexity retired with Sonar Chat Completions. Only
# `sonar` is still served, through the Agent API as `perplexity/sonar`.
RETIRED_SONAR_MODELS = ["sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]

# Agent API tool result items that Inspect reads, with the field holding
# their sources. Each is kept in `ModelOutput.metadata` under its type.
TOOL_RESULT_ITEMS = {"search_results": "results", "fetch_url_results": "contents"}

# Sonar request parameters, with what to use instead where Inspect supports
# it. The Agent API's web_search tool ignores them, so passing one as a
# web_search option would silently drop it. (`search_type` is not listed: the
# tool takes it, and rejects Sonar's values for it.)
_IMAGES = "Images need Perplexity's image_search tool, which Inspect does not support."
SONAR_SEARCH_OPTIONS: dict[str, str | None] = {
    "search_mode": None,
    "web_search_options": None,
    "search_context_size": (
        "Use the token budgets max_tokens and max_tokens_per_page in place of "
        "search_context_size."
    ),
    "search_domain_filter": None,
    "search_recency_filter": None,
    "search_after_date_filter": None,
    "search_before_date_filter": None,
    "last_updated_after_filter": None,
    "last_updated_before_filter": None,
    "search_language_filter": None,
    "num_search_results": None,
    "disable_search": None,
    "enable_search_classifier": None,
    "reasoning_effort": "Use the reasoning_effort generation config option.",
    "return_images": _IMAGES,
    "num_images": _IMAGES,
    "image_domain_filter": _IMAGES,
    "image_format_filter": _IMAGES,
    "return_videos": None,
    "num_videos": None,
    "media_response": None,
    "return_related_questions": None,
    "stream_mode": None,
}


class PerplexityAPI(OpenAICompatibleAPI):
    """Model provider for Perplexity AI (Agent API)."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        # Perplexity's own models can also be named with their provider
        if model_name.removeprefix("perplexity/") in RETIRED_SONAR_MODELS:
            raise ValueError(
                f"Perplexity retired the '{model_name}' model along with Sonar Chat "
                "Completions. Use 'perplexity/sonar' or another Agent API model, "
                "named 'perplexity/<provider>/<model>' (for example "
                "'perplexity/openai/gpt-5.6-luna'). See "
                "https://docs.perplexity.ai/docs/agent-api/models"
            )

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Perplexity",
            service_base_url="https://api.perplexity.ai/v1",
            **model_args,
        )

    @override
    def service_model_name(self) -> str:
        """Agent API model id.

        Agent API ids name the model's provider (`openai/gpt-5.6-luna`). A name
        without one (`sonar`) is one of Perplexity's own models.
        """
        return (
            self.model_name
            if "/" in self.model_name
            else f"perplexity/{self.model_name}"
        )

    @override
    def uses_responses_api(self, tools: list[ToolInfo], config: GenerateConfig) -> bool:
        # every request goes to the Agent API's /v1/responses
        return True

    @override
    def supports_max_reasoning_effort(self) -> bool:
        # the Agent API accepts `max` for every model
        return True

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput | Exception, ModelCall]:
        # the Agent API searches only when the request includes its web_search
        # tool, which is sent only for Inspect's web_search() tool
        web_search: dict[str, Any] | None = None
        for tool in tools:
            if (
                tool.name == "web_search"
                and tool.options
                and "perplexity" in tool.options
            ):
                maybe_opts = tool.options["perplexity"]
                if isinstance(maybe_opts, dict):
                    sonar_options = [k for k in maybe_opts if k in SONAR_SEARCH_OPTIONS]
                    if sonar_options:
                        hints = dict.fromkeys(
                            hint
                            for k in sonar_options
                            if (hint := SONAR_SEARCH_OPTIONS[k]) is not None
                        )
                        raise ValueError(
                            f"Perplexity web_search options {sonar_options} are Sonar "
                            "parameters, which the Agent API does not accept. "
                            + "".join(f"{hint} " for hint in hints)
                            + "See https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/how-to#parameter-reference"
                        )
                    web_search = {"type": "web_search", **maybe_opts}
                elif maybe_opts is True:
                    web_search = {"type": "web_search"}
                elif maybe_opts is not None:
                    raise TypeError(
                        f"Expected a dictionary or True for perplexity_options, got {type(maybe_opts)}"
                    )
            else:
                raise ValueError(
                    "Perplexity does not support tools other than web_search with perplexity options"
                )

        # generate_responses sends the Agent API fields as given
        extra_body = dict(config.extra_body or {})
        if web_search is not None:
            extra_body["tools"] = _with_web_search(extra_body.get("tools"), web_search)
            # generate_responses sends no tool choice, as it sends no tools
            forced: dict[str, str] | None = None
            # web_search is the only Inspect tool, so "any" forces it too
            # ("required" could be met by a tool in extra_body instead)
            if tool_choice == "any" or isinstance(tool_choice, ToolFunction):
                forced = {"type": "web_search"}
            if forced is not None:
                raw_choice = extra_body.get("tool_choice", forced)
                if raw_choice != forced:
                    raise ValueError(
                        f"tool_choice {tool_choice!r} forces a web search, which "
                        f"conflicts with tool_choice {raw_choice!r} in extra_body."
                    )
                extra_body["tool_choice"] = forced

        tool_results: dict[str, list[dict[str, Any]]] = {}
        usage_metadata: dict[str, Any] = {}

        def take_tool_results(response: Response) -> Response:
            return _take_tool_results(response, tool_results, usage_metadata)

        result = await generate_responses(
            client=self.client,
            http_hooks=self._http_hooks,
            model_name=self.service_model_name(),
            model_family=self.model_family(),
            input=input,
            tools=[],
            tool_choice=tool_choice,
            config=config,
            background=None,
            service_tier=None,
            prompt_cache_key=NOT_GIVEN,
            prompt_cache_retention=NOT_GIVEN,
            safety_identifier=NOT_GIVEN,
            responses_store=self.responses_store,
            synthesize_phase=self.responses_phase,
            model_info=self.responses_model_info(),
            batcher=None,
            handle_bad_request=self.handle_bad_request,
            handle_stream_error=self.handle_stream_error,
            streaming=self.resolve_stream(config),
            extra_body=extra_body,
            process_response=take_tool_results,
        )
        assert isinstance(result, tuple)
        output, call = result

        if isinstance(output, ModelOutput) and tool_results:
            _attach_citations(output, [r for rs in tool_results.values() for r in rs])
            output.metadata = output.metadata or {}
            output.metadata.update(tool_results)
        if isinstance(output, ModelOutput) and usage_metadata:
            output.metadata = output.metadata or {}
            output.metadata.update(usage_metadata)

        return output, call


def _take_tool_results(
    response: Response,
    tool_results: dict[str, list[dict[str, Any]]],
    usage_metadata: dict[str, Any],
) -> Response:
    """Move the Agent API's tool results out of a response.

    The Agent API returns the sources its tools found as output items
    (`search_results`, `fetch_url_results`), which the OpenAI SDK does not
    know and the Responses conversion cannot read. Their sources are added to
    `tool_results` by item type, and the response is returned without them.
    Other result items (from Agent API tools such as `image_search` passed in
    `extra_body`) raise an error, as Inspect cannot read them.

    Perplexity also reports prompt cache writes as `cache_creation_input_tokens`
    rather than `cache_write_tokens`; these are moved so that usage separates
    them from uncached input tokens. The number of searches, which Perplexity
    bills per search, is added to `usage_metadata` as `num_search_queries`.
    """
    output: list[ResponseOutputItem] = []
    for item in response.output:
        # the SDK parses an item type it does not know as an output message
        item_type: str = item.type
        if item_type in TOOL_RESULT_ITEMS:
            results = (item.model_extra or {}).get(TOOL_RESULT_ITEMS[item_type])
            if isinstance(results, list):
                tool_results.setdefault(item_type, []).extend(
                    r for r in results if isinstance(r, dict)
                )
        elif isinstance(item, ResponseOutputMessage) and item_type != "message":
            raise ValueError(
                f"Perplexity returned a '{item_type}' item, which Inspect does not "
                "support. Inspect reads the results of the web_search and fetch_url "
                "tools only; remove other Agent API tools from extra_body."
            )
        else:
            output.append(item)
    response.output = output

    details = response.usage.input_tokens_details if response.usage else None
    if details is not None and details.cache_write_tokens is None:
        cache_creation = (details.model_extra or {}).get("cache_creation_input_tokens")
        if isinstance(cache_creation, int):
            details.cache_write_tokens = cache_creation

    usage_extra = (response.usage.model_extra or {}) if response.usage else {}
    tool_calls = usage_extra.get("tool_calls_details")
    search_web = tool_calls.get("search_web") if isinstance(tool_calls, dict) else None
    searches = search_web.get("invocation") if isinstance(search_web, dict) else None
    if isinstance(searches, int):
        usage_metadata["num_search_queries"] = searches

    return response


def _with_web_search(tools: Any, web_search: dict[str, Any]) -> list[Any]:
    """Add the web_search tool to the Agent API tools passed in `extra_body`."""
    if tools is None:
        return [web_search]
    if not isinstance(tools, list):
        raise TypeError(f"Expected a list for extra_body['tools'], got {type(tools)}")
    if any(
        isinstance(tool, dict) and tool.get("type") == "web_search" for tool in tools
    ):
        raise ValueError(
            "extra_body['tools'] already has a web_search tool. Pass Perplexity's "
            "web search either with the web_search() tool or in extra_body, not both."
        )
    return [*tools, web_search]


def _attach_citations(output: ModelOutput, sources: list[dict[str, Any]]) -> None:
    """Add the tool results to the last text part of each message as citations.

    Results whose URL is already cited in the message (for example from a
    `url_citation` annotation) are left out. A message with no text gets none.
    """
    for choice in output.choices:
        # the Responses conversion gives list content
        texts = [p for p in choice.message.content if isinstance(p, ContentText)]
        if not texts:
            continue
        cited = {
            citation.url
            for part in texts
            for citation in part.citations or []
            if isinstance(citation, UrlCitation)
        }
        citations: list[Citation] = []
        for sr in sources:
            url = sr.get("url")
            if isinstance(url, str) and url not in cited:
                cited.add(url)
                citations.append(UrlCitation(title=sr.get("title"), url=url))
        if citations:
            texts[-1].citations = [*(texts[-1].citations or []), *citations]
