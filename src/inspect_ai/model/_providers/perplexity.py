from typing import Any, cast

from openai.types.chat import ChatCompletion

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.model._openai import chat_choices_from_openai
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice


class PerplexityAPI(OpenAICompatibleAPI):
    """Model provider for Perplexity AI."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Perplexity",
            service_base_url="https://api.perplexity.ai",
            **model_args,
        )

        self._response: dict[str, Any] | None = None

    def on_response(self, response: dict[str, Any]) -> None:
        """Capture the raw response for post-processing."""
        self._response = response

    async def generate(
        self,
        input: list["ChatMessage"],
        tools: list["ToolInfo"],
        tool_choice: "ToolChoice",
        config: GenerateConfig,
    ) -> tuple[ModelOutput | Exception, "ModelCall"]:
        search_options: dict[str, Any] | None = None
        for tool in tools:
            if (
                tool.name == "web_search"
                and tool.options
                and "perplexity" in tool.options
            ):
                maybe_opts = tool.options["perplexity"]
                if maybe_opts is not None:
                    if maybe_opts is True:
                        search_options = {}
                    elif isinstance(maybe_opts, dict):
                        search_options = maybe_opts
                    else:
                        raise TypeError(
                            f"Expected a dictionary or True for perplexity_options, got {type(maybe_opts)}"
                        )
            else:
                raise ValueError(
                    "Perplexity does not support tools other than web_search with perplexity options"
                )

        if search_options:
            extra_body = {**(config.extra_body or {}), **search_options}
            config = config.merge(GenerateConfig(extra_body=extra_body))

        result = await super().generate(input, [], tool_choice, config)
        output, call = cast(tuple[ModelOutput, "ModelCall"], result)

        if self._response:
            response = self._response

            # attach citations if search results are returned
            search_results = response.get("search_results")
            if isinstance(search_results, list):
                citations = [
                    UrlCitation(title=sr.get("title"), url=sr.get("url", ""))
                    for sr in search_results
                    if isinstance(sr, dict) and sr.get("url") is not None
                ]
                if citations:
                    for choice in output.choices:
                        msg = choice.message
                        if isinstance(msg.content, str):
                            msg.content = [
                                ContentText(text=msg.content, citations=citations)
                            ]
                        else:
                            added = False
                            for content in msg.content:
                                if (
                                    isinstance(content, ContentText)
                                    and getattr(content, "citations", None) is None
                                ):
                                    content.citations = citations
                                    added = True
                                    break
                            if not added:
                                msg.content.append(
                                    ContentText(text="", citations=citations)
                                )

            # update usage with additional metrics
            usage_data = response.get("usage")
            if isinstance(usage_data, dict):
                extra_usage = {
                    k: usage_data.get(k)
                    for k in [
                        "search_context_size",
                        "citation_tokens",
                        "num_search_queries",
                    ]
                    if k in usage_data
                }
                if output.usage:
                    output.usage.reasoning_tokens = usage_data.get("reasoning_tokens")
                else:
                    output.usage = ModelUsage(
                        input_tokens=usage_data.get("prompt_tokens", 0),
                        output_tokens=usage_data.get("completion_tokens", 0),
                        total_tokens=usage_data.get("total_tokens", 0),
                        reasoning_tokens=usage_data.get("reasoning_tokens"),
                    )
                if extra_usage:
                    output.metadata = output.metadata or {}
                    output.metadata.update(extra_usage)

            # keep search_results for reference
            if search_results:
                output.metadata = output.metadata or {}
                output.metadata["search_results"] = search_results

        return output, call

    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        return chat_choices_from_openai(completion, tools)
