import json
import os
from typing import Any

from mistralai import (
    FunctionCall,
    FunctionName,
    Mistral,
)
from mistralai.models import (
    AssistantMessage as MistralAssistantMessage,
)
from mistralai.models import (
    ChatCompletionChoice as MistralChatCompletionChoice,
)
from mistralai.models import Function as MistralFunction
from mistralai.models import SDKError
from mistralai.models import SystemMessage as MistralSystemMessage
from mistralai.models import Tool as MistralTool
from mistralai.models import ToolCall as MistralToolCall
from mistralai.models import (
    ToolChoice as MistralToolChoice,
)
from mistralai.models import ToolMessage as MistralToolMessage
from mistralai.models import UserMessage as MistralUserMessage
from mistralai.models.chatcompletionresponse import (
    ChatCompletionResponse as MistralChatCompletionResponse,
)
from typing_extensions import override

# TODO: Migration guide:
# https://github.com/mistralai/client-python/blob/main/MIGRATION.md
from inspect_ai._util.constants import (
    DEFAULT_TIMEOUT,
)
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .util import environment_prerequisite_error, model_base_url, parse_tool_call

AZURE_MISTRAL_API_KEY = "AZURE_MISTRAL_API_KEY"
AZUREAI_MISTRAL_API_KEY = "AZUREAI_MISTRAL_API_KEY"
MISTRAL_API_KEY = "MISTRAL_API_KEY"


class MistralAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[
                MISTRAL_API_KEY,
                AZURE_MISTRAL_API_KEY,
                AZUREAI_MISTRAL_API_KEY,
            ],
            config=config,
        )

        # resolve api_key -- look for mistral then azure
        if not self.api_key:
            self.api_key = os.environ.get(MISTRAL_API_KEY, None)
            if self.api_key:
                base_url = model_base_url(base_url, "MISTRAL_BASE_URL")
            else:
                self.api_key = os.environ.get(
                    AZUREAI_MISTRAL_API_KEY, os.environ.get(AZURE_MISTRAL_API_KEY, None)
                )
                if not self.api_key:
                    raise environment_prerequisite_error(
                        "Mistral", [MISTRAL_API_KEY, AZUREAI_MISTRAL_API_KEY]
                    )
                base_url = model_base_url(base_url, "AZUREAI_MISTRAL_BASE_URL")
                if not base_url:
                    raise ValueError(
                        "You must provide a base URL when using Mistral on Azure. Use the AZUREAI_MISTRAL_BASE_URL "
                        + " environment variable or the --model-base-url CLI flag to set the base URL."
                    )

        if base_url:
            model_args["server_url"] = base_url

        # create client
        self.client = Mistral(
            api_key=self.api_key,
            timeout_ms=(config.timeout if config.timeout else DEFAULT_TIMEOUT) * 1000,
            **model_args,
        )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        # build request
        request: dict[str, Any] = dict(
            model=self.model_name,
            messages=[mistral_chat_message(message) for message in input],
            tools=mistral_chat_tools(tools) if len(tools) > 0 else None,
            tool_choice=(
                mistral_chat_tool_choice(tool_choice) if len(tools) > 0 else None
            ),
        )
        if config.temperature is not None:
            request["temperature"] = config.temperature
        if config.top_p is not None:
            request["top_p"] = config.top_p
        if config.max_tokens is not None:
            request["max_tokens"] = config.max_tokens
        if config.seed is not None:
            request["random_seed"] = config.seed

        # send request
        try:
            response = await self.client.chat.complete_async(**request)
        except SDKError as ex:
            if ex.status_code == 400:
                return self.handle_bad_request(ex)
            else:
                raise ex

        if response is None:
            raise RuntimeError("Mistral model did not return a response from generate.")

        # return model output (w/ tool calls if they exist)
        choices = completion_choices_from_response(response, tools)
        return ModelOutput(
            model=response.model,
            choices=choices,
            usage=ModelUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=(
                    response.usage.completion_tokens
                    if response.usage.completion_tokens
                    else response.usage.total_tokens - response.usage.prompt_tokens
                ),
                total_tokens=response.usage.total_tokens,
            ),
        ), mistral_model_call(request, response)

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        return isinstance(ex, SDKError) and ex.status_code == 429

    @override
    def connection_key(self) -> str:
        return str(self.api_key)

    def handle_bad_request(self, ex: SDKError) -> ModelOutput:
        if "maximum context length" in ex.body:
            body = json.loads(ex.body)
            content = body.get("message", ex.body)
            return ModelOutput.from_content(
                model=self.model_name, content=content, stop_reason="model_length"
            )
        else:
            raise ex


def mistral_model_call(
    request: dict[str, Any], response: MistralChatCompletionResponse
) -> ModelCall:
    request = request.copy()
    request.update(messages=[message.model_dump() for message in request["messages"]])
    if request.get("tools", None) is not None:
        request["tools"] = [tool.model_dump() for tool in request["tools"]]
    return ModelCall(request=request, response=response.model_dump())


def mistral_chat_tools(tools: list[ToolInfo]) -> list[MistralTool]:
    return [
        MistralTool(function=MistralFunction(**tool.model_dump(exclude_none=True)))
        for tool in tools
    ]


def mistral_chat_tool_choice(
    tool_choice: ToolChoice,
) -> str | dict[str, Any]:
    if isinstance(tool_choice, ToolFunction):
        return MistralToolChoice(
            type="function", function=FunctionName(name=tool_choice.name)
        ).model_dump()
    elif tool_choice == "any":
        return "any"
    elif tool_choice == "auto":
        return "auto"
    elif tool_choice == "none":
        return "none"


def mistral_chat_message(
    message: ChatMessage,
) -> (
    MistralSystemMessage
    | MistralUserMessage
    | MistralAssistantMessage
    | MistralToolMessage
):
    if message.role == "assistant" and message.tool_calls:
        return MistralAssistantMessage(
            role=message.role,
            content=message.text,
            tool_calls=[mistral_tool_call(call) for call in message.tool_calls],
        )
    elif message.role == "tool":
        return MistralToolMessage(
            role=message.role,
            name=message.tool_call_id,
            content=(
                f"Error: {message.error.message}" if message.error else message.text
            ),
        )
    elif message.role == "user":
        return MistralUserMessage(content=message.text)
    elif message.role == "system":
        return MistralSystemMessage(content=message.text)
    elif message.role == "assistant":
        return MistralAssistantMessage(content=message.text)


def mistral_tool_call(tool_call: ToolCall) -> MistralToolCall:
    return MistralToolCall(
        id=tool_call.id,
        function=mistral_function_call(tool_call),
    )


def mistral_function_call(tool_call: ToolCall) -> FunctionCall:
    return FunctionCall(
        name=tool_call.function, arguments=json.dumps(tool_call.arguments)
    )


def chat_tool_calls(
    tool_calls: list[MistralToolCall], tools: list[ToolInfo]
) -> list[ToolCall]:
    return [chat_tool_call(tool, tools) for tool in tool_calls]


def chat_tool_call(tool_call: MistralToolCall, tools: list[ToolInfo]) -> ToolCall:
    id = tool_call.id or tool_call.function.name
    if isinstance(tool_call.function.arguments, str):
        return parse_tool_call(
            id, tool_call.function.name, tool_call.function.arguments, tools
        )
    else:
        return ToolCall(
            id, tool_call.function.name, tool_call.function.arguments, type="function"
        )


def completion_choice(
    choice: MistralChatCompletionChoice, tools: list[ToolInfo]
) -> ChatCompletionChoice:
    message = choice.message
    if message:
        completion = message.content or ""
        if isinstance(completion, list):
            completion = " ".join(completion)
        return ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=completion,
                tool_calls=chat_tool_calls(message.tool_calls, tools)
                if message.tool_calls
                else None,
                source="generate",
            ),
            stop_reason=(
                choice_stop_reason(choice)
                if choice.finish_reason is not None
                else "unknown"
            ),
        )
    else:
        raise ValueError(
            f"Mistral did not return a message in Completion Choice: {choice.model_dump_json(indent=2, exclude_none=True)}"
        )


def completion_choices_from_response(
    response: MistralChatCompletionResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    if response.choices is None:
        return []
    else:
        return [completion_choice(choice, tools) for choice in response.choices]


def choice_stop_reason(choice: MistralChatCompletionChoice) -> StopReason:
    match choice.finish_reason:
        case "stop":
            return "stop"
        case "length":
            return "max_tokens"
        case "model_length" | "tool_calls":
            return choice.finish_reason
        case _:
            return "unknown"
