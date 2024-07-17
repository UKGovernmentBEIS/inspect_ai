import os
from typing import Any, List, Dict, Optional, Union, Literal

from groq import AsyncGroq
from groq import (
    APIConnectionError,
    APIStatusError,
    RateLimitError,
    BadRequestError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    UnprocessableEntityError,
    InternalServerError,
    APITimeoutError,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_RETRIES, DEFAULT_MAX_TOKENS
from inspect_ai.tool import ToolCall, ToolFunction, ToolInfo

from .._chat_message import ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage
from .._util import chat_api_tool
from .util import as_stop_reason, model_base_url, parse_tool_call

GROQ_API_KEY = "GROQ_API_KEY"


# Define a type for ChatMessage
class ChatMessage:
    role: str
    text: str
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None


# Define a type for ToolChoice
ToolChoice = Union[ToolFunction, Literal["any", "none"]]


class GroqAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GROQ_API_KEY],
            config=config,
        )

        if not self.api_key:
            self.api_key = os.environ.get(GROQ_API_KEY)
        if not self.api_key:
            raise ValueError(f"{GROQ_API_KEY} environment variable not found.")

        self.client = AsyncGroq(
            api_key=self.api_key,
            base_url=model_base_url(base_url, "GROQ_BASE_URL"),
            max_retries=(
                config.max_retries
                if config.max_retries is not None
                else DEFAULT_MAX_RETRIES
            ),
            timeout=config.timeout if config.timeout is not None else 60.0,
            **model_args,
        )

    async def generate(
        self,
        input: List[ChatMessage],
        tools: Optional[List[ToolInfo]] = None,
        tool_choice: Optional[ToolChoice] = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> ModelOutput:
        messages = await as_groq_chat_messages(input)

        try:
            params = self.completion_params(config)
            if tools:
                params["tools"] = chat_tools(tools)
                params["tool_choice"] = (
                    chat_tool_choice(tool_choice) if tool_choice else "auto"
                )

            response = await self.client.chat.completions.create(
                messages=messages,
                model=self.model_name,
                **params,
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
        except (
            APIConnectionError,
            APIStatusError,
            RateLimitError,
            BadRequestError,
            AuthenticationError,
            PermissionDeniedError,
            NotFoundError,
            UnprocessableEntityError,
            InternalServerError,
            APITimeoutError,
        ) as e:
            raise

    def completion_params(self, config: GenerateConfig) -> Dict[str, Any]:
        params = {}
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.max_tokens is not None:
            params["max_tokens"] = config.max_tokens
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.stop_seqs:
            params["stop"] = config.stop_seqs
        if config.presence_penalty is not None:
            params["presence_penalty"] = config.presence_penalty
        if config.frequency_penalty is not None:
            params["frequency_penalty"] = config.frequency_penalty
        if config.seed is not None:
            params["seed"] = config.seed
        if config.num_choices is not None:
            params["n"] = config.num_choices
        return params

    def _chat_choices_from_response(self, response: Any) -> List[ChatCompletionChoice]:
        choices = list(response.choices)
        choices.sort(key=lambda c: c.index)
        return [
            ChatCompletionChoice(
                message=chat_message_assistant(choice.message),
                stop_reason=as_stop_reason(choice.finish_reason),
            )
            for choice in choices
        ]

    @override
    def is_rate_limit(self, ex: Exception) -> bool:
        return isinstance(ex, RateLimitError)

    @override
    def connection_key(self) -> str:
        return str(self.api_key)

    @override
    def collapse_user_messages(self) -> bool:
        return False

    @override
    def collapse_assistant_messages(self) -> bool:
        return False

    @override
    def max_tokens(self) -> Optional[int]:
        return DEFAULT_MAX_TOKENS


async def as_groq_chat_messages(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
    return [await groq_chat_message(message) for message in messages]


async def groq_chat_message(message: ChatMessage) -> Dict[str, Any]:
    groq_message: Dict[str, Any] = {"role": message.role, "content": message.text}

    if hasattr(message, "tool_calls") and message.tool_calls:
        groq_message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]

    if hasattr(message, "tool_call_id") and message.tool_call_id:
        groq_message["tool_call_id"] = message.tool_call_id

    if message.role == "tool":
        groq_message["name"] = message.tool_call_id

    return groq_message


def chat_tools(tools: List[ToolInfo]) -> List[Dict[str, Any]]:
    return [
        {"type": "function", "function": chat_api_tool(tool)["function"]}
        for tool in tools
    ]


def chat_tool_choice(tool_choice: ToolChoice) -> str | Dict[str, Any]:
    if isinstance(tool_choice, ToolFunction):
        return {"type": "function", "function": {"name": tool_choice.name}}
    elif tool_choice == "any":
        return "auto"
    else:
        return tool_choice


def chat_tool_calls(message: Any) -> Optional[List[ToolCall]]:
    if hasattr(message, "tool_calls") and message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments)
            for call in message.tool_calls
        ]
    return None


def chat_message_assistant(message: Any) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content=message.content or "",
        source="generate",
        tool_calls=chat_tool_calls(message),
    )