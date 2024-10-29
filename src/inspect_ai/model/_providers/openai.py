import json
import os
from copy import copy
from typing import Any, cast

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
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
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, DEFAULT_MAX_RETRIES
from inspect_ai._util.content import Content
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.images import image_as_data_uri
from inspect_ai._util.url import is_data_uri, is_http_url
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    Logprobs,
    ModelOutput,
    ModelUsage,
)
from .openai_o1 import generate_o1
from .util import (
    as_stop_reason,
    environment_prerequisite_error,
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
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[OPENAI_API_KEY, AZURE_OPENAI_API_KEY, AZUREAI_OPENAI_API_KEY],
            config=config,
        )

        # pull out azure model_arg
        AZURE_MODEL_ARG = "azure"
        is_azure = False
        if AZURE_MODEL_ARG in model_args:
            is_azure = model_args.get(AZURE_MODEL_ARG, False)
            del model_args[AZURE_MODEL_ARG]

        # resolve api_key
        if not self.api_key:
            self.api_key = os.environ.get(
                AZUREAI_OPENAI_API_KEY, os.environ.get(AZURE_OPENAI_API_KEY, None)
            )
            if self.api_key:
                is_azure = True
            else:
                self.api_key = os.environ.get(OPENAI_API_KEY, None)
                if not self.api_key:
                    raise environment_prerequisite_error(
                        "OpenAI",
                        [
                            OPENAI_API_KEY,
                            AZUREAI_OPENAI_API_KEY,
                        ],
                    )

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
                raise PrerequisiteError(
                    "ERROR: You must provide a base URL when using OpenAI on Azure. Use the AZUREAI_OPENAI_BASE_URL "
                    + "environment variable or the --model-base-url CLI flag to set the base URL."
                )

            self.client: AsyncAzureOpenAI | AsyncOpenAI = AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=base_url,
                azure_deployment=model_name,
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                **model_args,
            )
        else:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
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
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        # short-circuit to call o1- model
        if self.model_name.startswith("o1-"):
            return await generate_o1(
                client=self.client,
                input=input,
                tools=tools,
                **self.completion_params(config, False),
            )

        # unlike text models, vision models require a max_tokens (and set it to a very low
        # default, see https://community.openai.com/t/gpt-4-vision-preview-finish-details/475911/10)
        OPENAI_IMAGE_DEFAULT_TOKENS = 4096
        if "vision" in self.model_name:
            if isinstance(config.max_tokens, int):
                config.max_tokens = max(config.max_tokens, OPENAI_IMAGE_DEFAULT_TOKENS)
            else:
                config.max_tokens = OPENAI_IMAGE_DEFAULT_TOKENS

        # prepare request (we do this so we can log the ModelCall)
        request = dict(
            messages=await as_openai_chat_messages(input),
            tools=chat_tools(tools) if len(tools) > 0 else NOT_GIVEN,
            tool_choice=chat_tool_choice(tool_choice) if len(tools) > 0 else NOT_GIVEN,
            **self.completion_params(config, len(tools) > 0),
        )

        try:
            # generate completion
            response: ChatCompletion = await self.client.chat.completions.create(
                **request
            )

            # parse out choices
            choices = self._chat_choices_from_response(response, tools)

            # return output and call
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
            ), ModelCall.create(
                request=request,
                response=response.model_dump(),
                filter=model_call_filter,
            )
        except BadRequestError as e:
            return self.handle_bad_request(e)

    def _chat_choices_from_response(
        self, response: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        # adding this as a method so we can override from other classes (e.g together)
        return chat_choices_from_response(response, tools)

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        if isinstance(ex, RateLimitError):
            # Do not retry on these rate limit errors
            if (
                "Request too large" not in ex.message
                and "You exceeded your current quota" not in ex.message
            ):
                return True
        elif isinstance(
            ex, (APIConnectionError | APITimeoutError | InternalServerError)
        ):
            return True
        return False

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return str(self.api_key)

    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params: dict[str, Any] = dict(
            model=self.model_name,
        )
        if config.max_tokens is not None:
            params["max_tokens"] = config.max_tokens
        if config.frequency_penalty is not None:
            params["frequency_penalty"] = config.frequency_penalty
        if config.stop_seqs is not None:
            params["stop"] = config.stop_seqs
        if config.presence_penalty is not None:
            params["presence_penalty"] = config.presence_penalty
        if config.logit_bias is not None:
            params["logit_bias"] = config.logit_bias
        if config.seed is not None:
            params["seed"] = config.seed
        if config.temperature is not None:
            params["temperature"] = config.temperature
        # TogetherAPI requires temperature w/ num_choices
        elif config.num_choices is not None:
            params["temperature"] = 1
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.timeout is not None:
            params["timeout"] = float(config.timeout)
        if config.num_choices is not None:
            params["n"] = config.num_choices
        if config.logprobs is not None:
            params["logprobs"] = config.logprobs
        if config.top_logprobs is not None:
            params["top_logprobs"] = config.top_logprobs
        if tools and config.parallel_tool_calls is not None:
            params["parallel_tool_calls"] = config.parallel_tool_calls

        return params

    # convert some well known bad request errors into ModelOutput
    def handle_bad_request(self, e: BadRequestError) -> ModelOutput:
        if e.status_code == 400 and e.code == "context_length_exceeded":
            if isinstance(e.body, dict) and "message" in e.body.keys():
                content = str(e.body.get("message"))
            else:
                content = e.message
            return ModelOutput.from_content(
                model=self.model_name, content=content, stop_reason="model_length"
            )
        else:
            raise e


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
                f"Error: {message.error.message}" if message.error else message.text
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
    return [chat_tool_param(tool) for tool in tools]


def chat_tool_param(tool: ToolInfo) -> ChatCompletionToolParam:
    function = FunctionDefinition(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters.model_dump(exclude_none=True),
    )
    return ChatCompletionToolParam(type="function", function=function)


def chat_tool_choice(tool_choice: ToolChoice) -> ChatCompletionToolChoiceOptionParam:
    if isinstance(tool_choice, ToolFunction):
        return ChatCompletionNamedToolChoiceParam(
            type="function", function=dict(name=tool_choice.name)
        )
    # openai supports 'any' via the 'required' keyword
    elif tool_choice == "any":
        return "required"
    else:
        return tool_choice


def chat_tool_calls(
    message: ChatCompletionMessage, tools: list[ToolInfo]
) -> list[ToolCall] | None:
    if message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments, tools)
            for call in message.tool_calls
        ]
    else:
        return None


def chat_choices_from_response(
    response: ChatCompletion, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    choices = list(response.choices)
    choices.sort(key=lambda c: c.index)
    return [
        ChatCompletionChoice(
            message=chat_message_assistant(choice.message, tools),
            stop_reason=as_stop_reason(choice.finish_reason),
            logprobs=(
                Logprobs(**choice.logprobs.model_dump())
                if choice.logprobs is not None
                else None
            ),
        )
        for choice in choices
    ]


def chat_message_assistant(
    message: ChatCompletionMessage, tools: list[ToolInfo]
) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content=message.content or "",
        source="generate",
        tool_calls=chat_tool_calls(message, tools),
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


def model_call_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove images from raw api call
    if key == "image_url" and isinstance(value, dict) and "url" in value:
        url = str(value.get("url"))
        if url.startswith("data:"):
            value = copy(value)
            value.update(url=BASE_64_DATA_REMOVED)
    return value
