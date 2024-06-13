import json
import os
from typing import Any, cast

from openai import APIStatusError, AsyncAzureOpenAI, AsyncOpenAI, RateLimitError
from openai._types import NOT_GIVEN
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionNamedToolChoiceParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)
from openai.types.shared_params.function_definition import FunctionDefinition
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_RETRIES
from inspect_ai._util.images import image_as_data_uri
from inspect_ai._util.url import is_data_uri, is_http_url

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._content import Content
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ChatCompletionChoice,
    Logprobs,
    ModelOutput,
    ModelUsage,
)
from .._tool import ToolCall, ToolChoice, ToolFunction, ToolInfo
from .._util import chat_api_tool
from .util import (
    as_stop_reason,
    model_base_url,
    parse_tool_call,
)

OPENAI_API_KEY = "OPENAI_API_KEY"
AZURE_OPENAI_API_KEY = "AZURE_OPENAI_API_KEY"
AZUREAI_OPENAI_API_KEY = "AZUREAI_OPENAI_API_KEY"


class OpenAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        api_key: str | None = None,
        **model_args: Any,
    ) -> None:
        # call super
        super().__init__(model_name=model_name, base_url=base_url, config=config)

        # resolve api_key
        is_azure = False
        if not api_key:
            api_key = os.environ.get(
                AZUREAI_OPENAI_API_KEY, os.environ.get(AZURE_OPENAI_API_KEY, None)
            )
            if api_key:
                is_azure = True
            else:
                api_key = os.environ.get(OPENAI_API_KEY, None)
                if not api_key:
                    raise ValueError(
                        f"No {OPENAI_API_KEY} or {AZUREAI_OPENAI_API_KEY} found."
                    )

        # save api_key for connection_key
        self.api_key = api_key

        # azure client
        if is_azure:
            # resolve base_url
            base_url = model_base_url(
                base_url,
                [
                    "AZUREAI_OPENAI_BASE_URL",
                    "AZURE_OPENAI_BASE_URL",
                    "AZURE_OPENAI_ENDPOINT",
                ],
            )
            if not base_url:
                raise ValueError(
                    "You must provide a base URL when using OpenAI on Azure. Use the AZUREAI_OPENAI_BASE_URL "
                    + " environment variable or the --model-base-url CLI flag to set the base URL."
                )

            self.client: AsyncAzureOpenAI | AsyncOpenAI = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                azure_deployment=model_name,
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                **model_args,
            )
        else:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=model_base_url(base_url, "OPENAI_BASE_URL"),
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                **model_args,
            )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # resolve max tokens (ignore type check so NotGiven is valid)
        config.max_tokens = config.max_tokens if config.max_tokens else NOT_GIVEN  # type: ignore
        # unlike text models, vision models require a max_tokens (and set it to a very low
        # default, see https://community.openai.com/t/gpt-4-vision-preview-finish-details/475911/10)
        OPENAI_IMAGE_DEFAULT_TOKENS = 4096
        if "vision" in self.model_name:
            if isinstance(config.max_tokens, int):
                config.max_tokens = max(config.max_tokens, OPENAI_IMAGE_DEFAULT_TOKENS)
            else:
                config.max_tokens = OPENAI_IMAGE_DEFAULT_TOKENS

        # normalize to openai messages
        messages = await as_openai_chat_messages(input)
        try:
            # generate completion
            response: ChatCompletion = await self.client.chat.completions.create(
                messages=messages,
                tools=chat_tools(tools) if len(tools) > 0 else NOT_GIVEN,
                tool_choice=(
                    chat_tool_choice(tool_choice) if len(tools) > 0 else NOT_GIVEN
                ),
                **self.completion_params(config),
            )
            choices = self._chat_choices_from_response(response)
            return ModelOutput(
                model=response.model,
                choices=choices,
                usage=(
                    ModelUsage(
                        input_tokens=response.usage.prompt_tokens,
                        output_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                    )
                    if response.usage
                    else None
                ),
            )
        except APIStatusError as e:
            completion, error = handle_content_filter_error(e)
            return ModelOutput.from_content(
                model=self.model_name,
                content=completion,
                stop_reason="content_filter",
                error=str(error) if error else None,
            )

    def _chat_choices_from_response(
        self, response: ChatCompletion
    ) -> list[ChatCompletionChoice]:
        # adding this as a method so we can override from other classes (e.g together)
        return chat_choices_from_response(response)

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        if isinstance(ex, RateLimitError):
            # Do not retry on these rate limit errors
            if (
                "Request too large" not in ex.message
                and "You exceeded your current quota" not in ex.message
            ):
                return True
        return False

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return self.api_key

    def completion_params(self, config: GenerateConfig) -> dict[str, Any]:
        return dict(
            model=self.model_name,
            stream=False,  # Code below assumes this is not a streaming response
            frequency_penalty=(
                config.frequency_penalty
                if config.frequency_penalty is not None
                else NOT_GIVEN
            ),
            stop=config.stop_seqs if config.stop_seqs is not None else NOT_GIVEN,
            max_tokens=config.max_tokens,
            presence_penalty=(
                config.presence_penalty
                if config.presence_penalty is not None
                else NOT_GIVEN
            ),
            logit_bias=config.logit_bias if config.logit_bias else NOT_GIVEN,
            seed=config.seed if config.seed is not None else NOT_GIVEN,
            temperature=(
                config.temperature
                if config.temperature is not None
                else (
                    1  # TogetherAPI requires temperature w/ num_choices
                    if config.num_choices is not None
                    else NOT_GIVEN
                )
            ),
            top_p=config.top_p if config.top_p is not None else NOT_GIVEN,
            timeout=(
                float(config.timeout) if config.timeout is not None else NOT_GIVEN
            ),
            n=config.num_choices if config.num_choices is not None else NOT_GIVEN,
            logprobs=config.logprobs if config.logprobs is not None else NOT_GIVEN,
            top_logprobs=(
                config.top_logprobs if config.top_logprobs is not None else NOT_GIVEN
            ),
        )


async def as_openai_chat_messages(
    messages: list[ChatMessage],
) -> list[ChatCompletionMessageParam]:
    return [await openai_chat_message(message) for message in messages]


async def openai_chat_message(message: ChatMessage) -> ChatCompletionMessageParam:
    if message.role == "system":
        return ChatCompletionSystemMessageParam(role=message.role, content=message.text)
    elif message.role == "user":
        return ChatCompletionUserMessageParam(
            role=message.role,
            content=(
                message.content
                if isinstance(message.content, str)
                else [
                    await as_chat_completion_part(content)
                    for content in message.content
                ]
            ),
        )
    elif message.role == "assistant":
        if message.tool_calls:
            return ChatCompletionAssistantMessageParam(
                role=message.role,
                content=message.text,
                tool_calls=[chat_tool_call(call) for call in message.tool_calls],
            )
        else:
            return ChatCompletionAssistantMessageParam(
                role=message.role, content=message.text
            )
    elif message.role == "tool":
        return ChatCompletionToolMessageParam(
            role=message.role,
            content=(
                f"Error: {message.tool_error}" if message.tool_error else message.text
            ),
            tool_call_id=str(message.tool_call_id),
        )
    else:
        raise ValueError(f"Unexpected message role {message.role}")


def chat_tool_call(tool_call: ToolCall) -> ChatCompletionMessageToolCallParam:
    return ChatCompletionMessageToolCallParam(
        id=tool_call.id,
        function=dict(
            name=tool_call.function, arguments=json.dumps(tool_call.arguments)
        ),
        type=tool_call.type,
    )


def chat_tools(tools: list[ToolInfo]) -> list[ChatCompletionToolParam]:
    chat_tools = [chat_api_tool(tool) for tool in tools]
    return [
        ChatCompletionToolParam(
            type=tool["type"], function=cast(FunctionDefinition, tool["function"])
        )
        for tool in chat_tools
    ]


def chat_tool_choice(tool_choice: ToolChoice) -> ChatCompletionToolChoiceOptionParam:
    if isinstance(tool_choice, ToolFunction):
        return ChatCompletionNamedToolChoiceParam(
            type="function", function=dict(name=tool_choice.name)
        )
    # openai does not support 'any' so we force it to 'auto'
    elif tool_choice == "any":
        return "auto"
    else:
        return tool_choice


def chat_tool_calls(message: ChatCompletionMessage) -> list[ToolCall] | None:
    if message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments)
            for call in message.tool_calls
        ]
    else:
        return None


def chat_choices_from_response(response: ChatCompletion) -> list[ChatCompletionChoice]:
    choices = list(response.choices)
    choices.sort(key=lambda c: c.index)
    return [
        ChatCompletionChoice(
            message=chat_message_assistant(choice.message),
            stop_reason=as_stop_reason(choice.finish_reason),
            logprobs=(
                Logprobs(**choice.logprobs.model_dump())
                if choice.logprobs is not None
                else None
            ),
        )
        for choice in choices
    ]


def chat_message_assistant(message: ChatCompletionMessage) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content=message.content or "",
        source="generate",
        tool_calls=chat_tool_calls(message),
    )


async def as_chat_completion_part(
    content: Content,
) -> ChatCompletionContentPartParam:
    if content.type == "text":
        return ChatCompletionContentPartTextParam(type="text", text=content.text)
    else:
        # API takes URL or base64 encoded file. If it's a remote file or
        # data URL leave it alone, otherwise encode it
        image_url, detail = (
            (content.image, "auto")
            if isinstance(content.image, str)
            else (content.image, content.detail)
        )

        if not is_http_url(image_url) and not is_data_uri(image_url):
            image_url = await image_as_data_uri(image_url)

        return ChatCompletionContentPartImageParam(
            type="image_url",
            image_url=dict(url=image_url, detail=cast(Any, detail)),
        )


# Azure throws an APIStatusError (w/ status 400) when its content
# moderation policies are triggered, which invalidates the entire
# eval run with an error. In this case we'd rather not end the run
# entirely but rather return the error as the model "message" and
# then record the error in ModelOutput metadata. Note that OpenAI
# does not exhibit this behavior (it just returns the completion
# "Sorry, but I can't assist with that."
def handle_content_filter_error(e: APIStatusError) -> tuple[str, object | None]:
    CANT_ASSIST = "Sorry, but I can't assist with that."
    if e.status_code == 400:
        if isinstance(e.body, dict) and "message" in e.body.keys():
            message = str(e.body.get("message"))
            return message, e.body
        else:
            return CANT_ASSIST, e.body
    else:
        raise e
