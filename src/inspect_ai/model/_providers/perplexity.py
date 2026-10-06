from typing import Any

from openai._types import NOT_GIVEN
from openai.types.responses import Response, ResponseOutputItem
from typing_extensions import override

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._openai_responses import responses_extra_body_fields
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.openai_responses import generate_responses
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._model_call import ModelCall

# Sonar models that Perplexity retired with Sonar Chat Completions. Only
# `sonar` is still served, through the Agent API as `perplexity/sonar`.
RETIRED_SONAR_MODELS = ["sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]

# Sonar search parameters. The Agent API's web_search tool ignores them, so
# passing one as a web_search option would silently drop it. (`search_type` is
# not listed: the tool takes it, and rejects Sonar's values for it.)
SONAR_SEARCH_OPTIONS = [
    "search_mode",
    "web_search_options",
    "search_domain_filter",
    "search_recency_filter",
    "search_after_date_filter",
    "search_before_date_filter",
    "last_updated_after_filter",
    "last_updated_before_filter",
    "num_search_results",
    "disable_search",
    "enable_search_classifier",
]


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
        if model_name in RETIRED_SONAR_MODELS:
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
                        raise ValueError(
                            f"Perplexity web_search options {sonar_options} are Sonar "
                            "parameters, which the Agent API does not accept. See "
                            "https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/how-to#parameter-reference"
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

        # generate_responses applies the Responses fields it knows from
        # extra_body; send the rest (Agent API fields) as given
        extra_body = {
            k: v
            for k, v in (config.extra_body or {}).items()
            if k not in responses_extra_body_fields() and k != "background"
        }
        if web_search is not None:
            extra_body["tools"] = [web_search]

        search_results: list[dict[str, Any]] = []

        def take_search_results(response: Response) -> Response:
            return _take_search_results(response, search_results)

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
            process_response=take_search_results,
        )
        assert isinstance(result, tuple)
        output, call = result

        if isinstance(output, ModelOutput) and search_results:
            _attach_citations(output, search_results)
            output.metadata = output.metadata or {}
            output.metadata["search_results"] = search_results

        return output, call


def _take_search_results(
    response: Response, search_results: list[dict[str, Any]]
) -> Response:
    """Move the Agent API's search results out of a response.

    The Agent API returns sources as `search_results` output items, which the
    OpenAI SDK does not know and the Responses conversion cannot read. Their
    results are appended to `search_results`, and the response is returned
    without them.

    Perplexity also reports prompt cache writes as `cache_creation_input_tokens`
    rather than `cache_write_tokens`; these are moved so that usage separates
    them from uncached input tokens.
    """
    output: list[ResponseOutputItem] = []
    for item in response.output:
        # the SDK parses an item type it does not know as an output message
        item_type: str = item.type
        if item_type == "search_results":
            results = (item.model_extra or {}).get("results")
            if isinstance(results, list):
                search_results.extend(r for r in results if isinstance(r, dict))
        else:
            output.append(item)
    response.output = output

    details = response.usage.input_tokens_details if response.usage else None
    if details is not None and details.cache_write_tokens is None:
        cache_creation = (details.model_extra or {}).get("cache_creation_input_tokens")
        if isinstance(cache_creation, int):
            details.cache_write_tokens = cache_creation

    return response


def _attach_citations(
    output: ModelOutput, search_results: list[dict[str, Any]]
) -> None:
    citations = [
        UrlCitation(title=sr.get("title"), url=sr["url"])
        for sr in search_results
        if isinstance(sr.get("url"), str)
    ]
    if not citations:
        return
    for choice in output.choices:
        msg = choice.message
        if isinstance(msg.content, str):
            msg.content = [ContentText(text=msg.content, citations=citations)]
        else:
            for content in msg.content:
                if isinstance(content, ContentText) and content.citations is None:
                    content.citations = citations
                    break
            else:
                msg.content.append(ContentText(text="", citations=citations))
