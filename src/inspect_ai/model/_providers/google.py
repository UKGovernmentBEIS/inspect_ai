from copy import copy
from typing import Any, cast

from google.ai.generativelanguage import (
    Blob,
    Candidate,
    FunctionCall,
    FunctionResponse,
    Part,
)
from google.api_core.exceptions import TooManyRequests
from google.api_core.retry.retry_base import if_transient_error
from google.generativeai import (  # type: ignore
    GenerationConfig,
    GenerativeModel,
    configure,
)
from google.generativeai.types import (  # type: ignore
    AsyncGenerateContentResponse,
    ContentDict,
    ContentsType,
    FunctionDeclaration,
    HarmBlockThreshold,
    HarmCategory,
    PartDict,
    Tool,
)
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from typing_extensions import override

from inspect_ai._util.error import exception_message
from inspect_ai._util.images import image_as_data

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._content import Content, ContentImage, ContentText
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import ChatCompletionChoice, ModelOutput, StopReason
from .._tool import ToolCall, ToolChoice, ToolInfo
from .._util import chat_api_tool
from .util import model_base_url

VERTEX_SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}


class GoogleAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(model_name=model_name, base_url=base_url, config=config)

        # configure genai client
        base_url = model_base_url(base_url, "GOOGLE_BASE_URL")
        configure(
            client_options=dict(api_endpoint=base_url),
            **model_args,
        )

        # create model
        self.model = GenerativeModel(self.model_name)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        parameters = GenerationConfig(
            candidate_count=config.num_choices,
            temperature=config.temperature,
            top_p=config.top_p,
            top_k=config.top_k,
            max_output_tokens=config.max_tokens,
            stop_sequences=config.stop_seqs,
        )

        try:
            # google-native messages
            messages = await as_chat_messages(input)

            # cast to AsyncGenerateContentResponse since we passed stream=False
            response = cast(
                AsyncGenerateContentResponse,
                await self.model.generate_content_async(
                    contents=messages,
                    safety_settings=VERTEX_SAFETY_SETTINGS,
                    generation_config=parameters,
                    tools=chat_tools(tools) if len(tools) > 0 else None,
                    stream=False,
                ),
            )
            choices = completion_choices_from_candidates(response.candidates)
            choice = choices[0]
            return ModelOutput(model=self.model_name, choices=[choice])
        except ValueError as ex:
            # If a safety filter is triggered, the response will be empty and a ValueError will be raised
            return ModelOutput.from_content(
                self.model_name,
                "Sorry, but I can't assist with that",
                "content_filter",
                exception_message(ex),
            )

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        return isinstance(ex, TooManyRequests)

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return self.model_name


async def as_chat_messages(messages: list[ChatMessage]) -> list[ContentsType]:
    # google does not support system messages so filter them out to start with
    system_messages = [message for message in messages if message.role == "system"]
    supported_messages = [message for message in messages if message.role != "system"]

    # build google chat messages
    chat_messages = [await content_dict(message) for message in supported_messages]

    # we want the system messages to be prepended to the first user message
    # (if there is no first user message then prepend one)
    prepend_system_messages(chat_messages, system_messages)

    # return messages
    return chat_messages


async def content_dict(
    message: ChatMessageUser | ChatMessageAssistant | ChatMessageTool,
) -> ContentDict:
    if isinstance(message, ChatMessageUser):
        return ContentDict(
            role="user",
            parts=(
                [PartDict(text=message.content)]
                if isinstance(message.content, str)
                else [await content_part(content) for content in message.content]
            ),
        )
    elif isinstance(message, ChatMessageAssistant):
        if message.tool_calls is not None:
            content_parts = [
                Part(
                    function_call=FunctionCall(
                        name=tool_call.function,
                        args=ParseDict(js_dict=tool_call.arguments, message=Struct()),
                    )
                )
                for tool_call in message.tool_calls
            ]
            if message.content:
                content_parts.append(Part(text=message.content))
            return ContentDict(role="model", parts=content_parts)
        else:
            return ContentDict(role="model", parts=[Part(text=message.content)])
    elif isinstance(message, ChatMessageTool):
        response = FunctionResponse(
            name=message.tool_call_id,
            response=ParseDict(
                js_dict={
                    "content": (
                        message.tool_error
                        if message.tool_error is not None
                        else message.text
                    )
                },
                message=Struct(),
            ),
        )
        return ContentDict(role="function", parts=[Part(function_response=response)])


async def content_part(content: Content | str) -> PartDict:
    if isinstance(content, str):
        return PartDict(text=content)
    elif isinstance(content, ContentText):
        return PartDict(text=content.text)
    else:
        return PartDict(inline_data=await chat_content_image_to_blob(content))


async def chat_content_image_to_blob(image: ContentImage) -> Blob:
    image_url = image.image
    image_bytes, mime_type = await image_as_data(image_url)
    return Blob(mime_type=mime_type, data=image_bytes)


def prepend_system_messages(
    messages: list[ContentDict], system_messages: list[ChatMessageSystem]
) -> None:
    # create system_parts
    system_parts = [Part(text=message.content) for message in system_messages]

    # we want the system messages to be prepended to the first user message
    # (if there is no first user message then prepend one)
    if messages[0].get("role") == "user":
        messages[0]["parts"] = system_parts + messages[0].get("parts", [])
    else:
        messages.insert(0, ContentDict(role="user", parts=system_parts))


def chat_tools(tools: list[ToolInfo]) -> list[Tool]:
    chat_tools = [chat_api_tool(tool) for tool in tools]
    declarations = [
        FunctionDeclaration(
            name=tool["function"]["name"],
            description=tool["function"]["description"],
            parameters=tool["function"]["parameters"],
        )
        for tool in chat_tools
    ]
    return [Tool(declarations)]


def completion_choice_from_candidate(candidate: Candidate) -> ChatCompletionChoice:
    # check for completion text
    content = " ".join(
        [part.text for part in candidate.content.parts if part.text is not None]
    )

    # now tool calls
    tool_calls: list[ToolCall] = []
    for part in candidate.content.parts:
        if part.function_call:
            arguments: dict[str, Any] = {}
            for key in part.function_call.args:
                val = part.function_call.args[key]
                arguments[key] = val
            tool_calls.append(
                ToolCall(
                    type="function",
                    id=part.function_call.name,
                    function=part.function_call.name,
                    arguments=arguments,
                )
            )

    # stop reason
    stop_reason = candidate_stop_reason(candidate.finish_reason)

    return ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content,
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            source="generate",
        ),
        stop_reason=stop_reason,
    )


def completion_choices_from_candidates(
    candidates: list[Candidate],
) -> list[ChatCompletionChoice]:
    candidates = copy(candidates)
    candidates.sort(key=lambda c: c.index)
    return [completion_choice_from_candidate(candidate) for candidate in candidates]


# google doesn't export FinishReason (it's in a sub-namespace with a beta
# designation that seems destined to change, so we vendor the enum here)
class FinishReason:
    FINISH_REASON_UNSPECIFIED = 0
    STOP = 1
    MAX_TOKENS = 2
    SAFETY = 3
    RECITATION = 4
    OTHER = 5


def candidate_stop_reason(finish_reason: FinishReason) -> StopReason:
    match finish_reason:
        case FinishReason.STOP:
            return "stop"
        case FinishReason.MAX_TOKENS:
            return "length"
        case FinishReason.SAFETY | FinishReason.RECITATION:
            return "content_filter"
        case _:
            return "unknown"


def gapi_should_retry(ex: BaseException) -> bool:
    if isinstance(ex, Exception):
        return if_transient_error(ex)
    else:
        return False
