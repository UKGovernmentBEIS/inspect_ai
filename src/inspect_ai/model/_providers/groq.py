import json
import os
from typing import Any, Dict, List, Optional

from groq import (
    AsyncGroq,
    RateLimitError,
)
from groq.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_RETRIES, DEFAULT_MAX_TOKENS
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage
from .util import (
    as_stop_reason,
    environment_prerequisite_error,
    model_base_url,
    parse_tool_call,
)

GROQ_API_KEY = "GROQ_API_KEY"


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
            raise environment_prerequisite_error("Groq", GROQ_API_KEY)

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
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput, ModelCall]:
        messages = await as_groq_chat_messages(input)

        params = self.completion_params(config)
        if tools:
            params["tools"] = chat_tools(tools)
            params["tool_choice"] = (
                chat_tool_choice(tool_choice) if tool_choice else "auto"
            )
            if config.parallel_tool_calls is not None:
                params["parallel_tool_calls"] = config.parallel_tool_calls

        response: ChatCompletion = await self.client.chat.completions.create(
            messages=messages,
            model=self.model_name,
            **params,
        )

        # extract output
        choices = self._chat_choices_from_response(response, tools)
        output = ModelOutput(
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

        # record call
        call = ModelCall.create(
            request=dict(messages=messages, model=self.model_name, **params),
            response=response.model_dump(),
        )

        # return
        return output, call

    def completion_params(self, config: GenerateConfig) -> Dict[str, Any]:
        params: dict[str, Any] = {}
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

    def _chat_choices_from_response(
        self, response: Any, tools: list[ToolInfo]
    ) -> List[ChatCompletionChoice]:
        choices = list(response.choices)
        choices.sort(key=lambda c: c.index)
        return [
            ChatCompletionChoice(
                message=chat_message_assistant(choice.message, tools),
                stop_reason=as_stop_reason(choice.finish_reason),
            )
            for choice in choices
        ]

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
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


async def as_groq_chat_messages(
    messages: list[ChatMessage],
) -> list[ChatCompletionMessageParam]:
    return [await groq_chat_message(message) for message in messages]


async def groq_chat_message(message: ChatMessage) -> ChatCompletionMessageParam:
    if isinstance(message, ChatMessageSystem):
        return ChatCompletionSystemMessageParam(role="system", content=message.text)

    elif isinstance(message, ChatMessageUser):
        return ChatCompletionUserMessageParam(role="user", content=message.text)

    elif isinstance(message, ChatMessageAssistant):
        return ChatCompletionAssistantMessageParam(
            role="assistant",
            content=message.text,
            tool_calls=[
                ChatCompletionMessageToolCallParam(
                    id=call.id,
                    type="function",
                    function={
                        "name": call.function,
                        "arguments": json.dumps(call.arguments),
                    },
                )
                for call in (message.tool_calls or [])
            ],
        )
    elif isinstance(message, ChatMessageTool):
        return ChatCompletionToolMessageParam(
            role="tool",
            content=message.text,
            tool_call_id=str(message.tool_call_id),
        )


def chat_tools(tools: List[ToolInfo]) -> List[Dict[str, Any]]:
    return [
        {"type": "function", "function": tool.model_dump(exclude_none=True)}
        for tool in tools
    ]


def chat_tool_choice(tool_choice: ToolChoice) -> str | Dict[str, Any]:
    if isinstance(tool_choice, ToolFunction):
        return {"type": "function", "function": {"name": tool_choice.name}}
    elif tool_choice == "any":
        return "auto"
    else:
        return tool_choice


def chat_tool_calls(message: Any, tools: list[ToolInfo]) -> Optional[List[ToolCall]]:
    if hasattr(message, "tool_calls") and message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments, tools)
            for call in message.tool_calls
        ]
    return None


def chat_message_assistant(message: Any, tools: list[ToolInfo]) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content=message.content or "",
        source="generate",
        tool_calls=chat_tool_calls(message, tools),
    )
