from typing import cast

from openai import APIStatusError
from openai.types.chat import ChatCompletion
from typing_extensions import override

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import Content, ContentText
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo

from .._generate_config import GenerateConfig
from .._model_output import ChatCompletionChoice
from .openai_compatible import OpenAICompatibleAPI


class GrokAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Grok",
            service_base_url="https://api.x.ai/v1",
        )

    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 400:
            # extract message
            if isinstance(ex.body, dict) and "message" in ex.body.keys():
                content = str(ex.body.get("message"))
            else:
                content = ex.message

            if "prompt length" in content:
                return ModelOutput.from_content(
                    model=self.model_name, content=content, stop_reason="model_length"
                )
            else:
                return ex
        else:
            return ex

    @override
    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        result = super().chat_choices_from_completion(completion, tools)

        return (
            [_add_citations(choice, citations) for choice in result]
            if (citations := _get_citations(completion))
            else result
        )

    @override
    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        tools, tool_choice, config = super().resolve_tools(tools, tool_choice, config)

        new_config = config.model_copy()
        if new_config.extra_body is None:
            new_config.extra_body = {}

        grok_search_options, new_tools = _extract_web_search_options(
            self.model_name, tools
        )

        force_web_search = (
            isinstance(tool_choice, ToolFunction) and tool_choice.name == "web_search"
        )

        new_config.extra_body["search_parameters"] = (
            {"mode": "off"}
            if grok_search_options is None
            else {
                "mode": "on" if force_web_search else "auto",
                **grok_search_options,
            }
        )

        return (
            new_tools,
            "none" if force_web_search else tool_choice,
            new_config,
        )


def _get_citations(completion: ChatCompletion) -> list[UrlCitation] | None:
    """Extract citations from ChatCompletion model_extra."""
    model_extra = completion.model_extra
    grok_citations = model_extra.get("citations") if model_extra else None

    return (
        [
            UrlCitation(url=url)
            for url in [url for url in grok_citations if isinstance(url, str)]
        ]
        if grok_citations and isinstance(grok_citations, list)
        else None
    )


def _extract_web_search_options(
    model_name: str,
    tools: list[ToolInfo],
) -> tuple[dict[str, object] | None, list[ToolInfo]]:
    """Extract Grok web search options from tools and return filtered tools.

    Returns:
        A tuple of (web_search_options, filtered_tools) where:
        - web_search_options: The Grok options if a web_search tool is found, None otherwise
        - filtered_tools: All tools except the web_search tool with Grok options
    """
    filtered_tools = []
    web_search_options = None

    for tool in tools:
        if (options := _get_grok_web_search_options(model_name, tool)) is not None:
            web_search_options = options
        else:
            filtered_tools.append(tool)

    return web_search_options, filtered_tools


def _get_grok_web_search_options(
    model_name: str, tool: ToolInfo
) -> dict[str, object] | None:
    """Check if a tool is a Grok web search tool and return its options."""
    return (
        cast(dict[str, object], grok_options)
        if (
            not model_name.startswith("grok-2")
            and tool.name == "web_search"
            and tool.options is not None
            and (grok_options := tool.options.get("grok", None)) is not None
        )
        else None
    )


def _add_citations(
    choice: ChatCompletionChoice, citations: list[UrlCitation] | None
) -> ChatCompletionChoice:
    if not choice.message.content:
        return choice

    # Grok citations are in no way correlated to any subset of a ChatCompletionChoice.
    # Because of this, we don't have any clue what cited text is relevant. This
    # code simply adds the citations to the last non-empty text content in the message

    updated_choice = choice.model_copy(deep=True)
    content_list: list[Content] = (
        [ContentText(text=updated_choice.message.content)]
        if isinstance(updated_choice.message.content, str)
        else updated_choice.message.content
    )
    updated_choice.message.content = content_list

    # Find the last non-empty ContentText entry
    last_text_content = next(
        (
            content
            for content in reversed(content_list)
            if isinstance(content, ContentText) and content.text.strip()
        ),
        None,
    )

    if last_text_content:
        last_text_content.citations = citations

    return updated_choice
