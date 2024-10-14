import json
from copy import copy
from typing import Any, cast

import proto  # type: ignore
from google.ai.generativelanguage import (
    Blob,
    Candidate,
    FunctionCall,
    FunctionCallingConfig,
    FunctionDeclaration,
    FunctionResponse,
    Part,
    Schema,
    ToolConfig,
    Type,
)
from google.api_core.exceptions import (
    GatewayTimeout,
    InternalServerError,
    InvalidArgument,
    ServiceUnavailable,
    TooManyRequests,
)
from google.api_core.retry.retry_base import if_transient_error
from google.generativeai import (  # type: ignore
    GenerationConfig,
    GenerativeModel,
    configure,
)
from google.generativeai.types import (  # type: ignore
    AsyncGenerateContentResponse,
    ContentDict,
    HarmBlockThreshold,
    HarmCategory,
    PartDict,
    PartType,
    SafetySettingDict,
    Tool,
)
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.images import image_as_data
from inspect_ai.tool import ToolCall, ToolChoice, ToolInfo, ToolParam, ToolParams

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
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .util import model_base_url

SAFETY_SETTINGS = "safety_settings"

DEFAULT_SAFETY_SETTINGS: SafetySettingDict = {
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

GOOGLE_API_KEY = "GOOGLE_API_KEY"


class GoogleAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        api_key: str | None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GOOGLE_API_KEY],
            config=config,
        )

        # pick out vertex safety settings and merge against default
        self.safety_settings = DEFAULT_SAFETY_SETTINGS.copy()
        if SAFETY_SETTINGS in model_args:
            self.safety_settings.update(
                parse_safety_settings(model_args.get(SAFETY_SETTINGS))
            )
            del model_args[SAFETY_SETTINGS]

        # configure genai client
        base_url = model_base_url(base_url, "GOOGLE_BASE_URL")
        configure(
            api_key=self.api_key,
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
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        parameters = GenerationConfig(
            candidate_count=config.num_choices,
            temperature=config.temperature,
            top_p=config.top_p,
            top_k=config.top_k,
            max_output_tokens=config.max_tokens,
            stop_sequences=config.stop_seqs,
        )

        # google-native messages
        contents = await as_chat_messages(input)

        # tools
        gemini_tools = chat_tools(tools) if len(tools) > 0 else None
        gemini_tool_config = chat_tool_config(tool_choice) if len(tools) > 0 else None

        # cast to AsyncGenerateContentResponse since we passed stream=False
        try:
            response = cast(
                AsyncGenerateContentResponse,
                await self.model.generate_content_async(
                    contents=contents,
                    safety_settings=self.safety_settings,
                    generation_config=parameters,
                    tools=gemini_tools,
                    tool_config=gemini_tool_config,
                ),
            )
        except InvalidArgument as ex:
            return self.handle_invalid_argument(ex)

        # build output
        output = ModelOutput(
            model=self.model_name,
            choices=completion_choices_from_candidates(response.candidates),
            usage=ModelUsage(
                input_tokens=response.usage_metadata.prompt_token_count,
                output_tokens=response.usage_metadata.candidates_token_count,
                total_tokens=response.usage_metadata.total_token_count,
            ),
        )

        # build call
        call = model_call(
            contents=contents,
            safety_settings=self.safety_settings,
            generation_config=parameters,
            tools=gemini_tools,
            tool_config=gemini_tool_config,
            response=response,
        )

        # return
        return output, call

    def handle_invalid_argument(self, ex: InvalidArgument) -> ModelOutput:
        if "size exceeds the limit" in ex.message.lower():
            return ModelOutput.from_content(
                model=self.model_name, content=ex.message, stop_reason="model_length"
            )
        else:
            raise ex

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        return isinstance(
            ex,
            TooManyRequests | InternalServerError | ServiceUnavailable | GatewayTimeout,
        )

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return self.model_name


def model_call(
    contents: list[ContentDict],
    generation_config: GenerationConfig,
    safety_settings: SafetySettingDict,
    tools: list[Tool] | None,
    tool_config: ToolConfig | None,
    response: AsyncGenerateContentResponse,
) -> ModelCall:
    return ModelCall.create(
        request=dict(
            contents=[model_call_content(content) for content in contents],
            generation_config=generation_config,
            safety_settings=safety_settings,
            tools=[MessageToDict(tool._proto._pb) for tool in tools]
            if tools is not None
            else None,
            tool_config=MessageToDict(tool_config._pb)
            if tool_config is not None
            else None,
        ),
        response=response.to_dict(),
        filter=model_call_filter,
    )


def model_call_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove images from raw api call
    if key == "inline_data" and isinstance(value, dict) and "data" in value:
        value = copy(value)
        value.update(data=BASE_64_DATA_REMOVED)
    return value


def model_call_content(content: ContentDict) -> ContentDict:
    return ContentDict(
        role=content["role"], parts=[model_call_part(part) for part in content["parts"]]
    )


def model_call_part(part: PartType) -> PartType:
    if isinstance(part, proto.Message):
        return MessageToDict(part._pb)
    elif isinstance(part, dict):
        part = part.copy()
        keys = list(part.keys())
        for key in keys:
            part[key] = model_call_part(part[key])
        return part
    else:
        return part


async def as_chat_messages(messages: list[ChatMessage]) -> list[ContentDict]:
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
                        args=dict_to_struct(tool_call.arguments),
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
                        message.error.message
                        if message.error is not None
                        else message.text
                    )
                },
                message=Struct(),
            ),
        )
        return ContentDict(role="function", parts=[Part(function_response=response)])


def dict_to_struct(x: dict[str, Any]) -> Struct:
    struct = Struct()
    struct.update(x)
    return struct


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
    declarations = [
        FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=schema_from_param(tool.parameters),
        )
        for tool in tools
    ]
    return [Tool(function_declarations=declarations)]


# https://ai.google.dev/gemini-api/tutorials/extract_structured_data#define_the_schema


def schema_from_param(param: ToolParam | ToolParams) -> Schema:
    if isinstance(param, ToolParams):
        param = ToolParam(
            type=param.type, properties=param.properties, required=param.required
        )

    if param.type == "number":
        return Schema(type=Type.NUMBER, description=param.description)
    elif param.type == "integer":
        return Schema(type=Type.INTEGER, description=param.description)
    elif param.type == "boolean":
        return Schema(type=Type.BOOLEAN, description=param.description)
    elif param.type == "string":
        return Schema(type=Type.STRING, description=param.description)
    elif param.type == "array":
        return Schema(
            type=Type.ARRAY,
            description=param.description,
            items=schema_from_param(param.items) if param.items else None,
        )
    elif param.type == "object":
        return Schema(
            type=Type.OBJECT,
            description=param.description,
            properties={k: schema_from_param(v) for k, v in param.properties.items()}
            if param.properties is not None
            else None,
            required=param.required,
        )
    else:
        return Schema(type=Type.TYPE_UNSPECIFIED)


def chat_tool_config(tool_choice: ToolChoice) -> ToolConfig:
    # NOTE: Google seems to sporadically return errors when being
    # passed a FunctionCallingConfig with mode="ANY". therefore,
    # we 'correct' this to "AUTO" to prevent the errors
    mode = "AUTO"
    if tool_choice == "none":
        mode = "NONE"
    return ToolConfig(function_calling_config=FunctionCallingConfig(mode=mode))

    # This is the 'correct' implementation if Google wasn't returning
    # errors for mode="ANY". we can test whether this is working properly
    # by commenting this back in and running pytest -k google_tools
    #
    # if isinstance(tool_choice, ToolFunction):
    #     return ToolConfig(
    #         function_calling_config=FunctionCallingConfig(
    #             mode="ANY", allowed_function_names=[tool_choice.name]
    #         )
    #     )
    # else:
    #     return ToolConfig(
    #         function_calling_config=FunctionCallingConfig(mode=tool_choice.upper())
    #     )


def completion_choice_from_candidate(candidate: Candidate) -> ChatCompletionChoice:
    # check for completion text
    content = " ".join(
        [part.text for part in candidate.content.parts if part.text is not None]
    )

    # now tool calls
    tool_calls: list[ToolCall] = []
    for part in candidate.content.parts:
        if part.function_call:
            function_call = MessageToDict(getattr(part.function_call, "_pb"))
            tool_calls.append(
                ToolCall(
                    type="function",
                    id=function_call["name"],
                    function=function_call["name"],
                    arguments=function_call["args"],
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
            return "max_tokens"
        case FinishReason.SAFETY | FinishReason.RECITATION:
            return "content_filter"
        case _:
            return "unknown"


def gapi_should_retry(ex: BaseException) -> bool:
    if isinstance(ex, Exception):
        return if_transient_error(ex)
    else:
        return False


def parse_safety_settings(
    safety_settings: Any,
) -> dict[HarmCategory, HarmBlockThreshold]:
    # ensure we have a dict
    if isinstance(safety_settings, str):
        safety_settings = json.loads(safety_settings)
    if not isinstance(safety_settings, dict):
        raise ValueError(f"{SAFETY_SETTINGS} must be dictionary.")

    parsed_settings: dict[HarmCategory, HarmBlockThreshold] = {}
    for key, value in safety_settings.items():
        if isinstance(key, str):
            key = str_to_harm_category(key)
        if not isinstance(key, HarmCategory):
            raise ValueError(f"Unexpected type for harm category: {key}")
        if isinstance(value, str):
            value = str_to_harm_block_threshold(value)
        if not isinstance(value, HarmBlockThreshold):
            raise ValueError(f"Unexpected type for harm block threshold: {value}")

        parsed_settings[key] = value

    return parsed_settings


def str_to_harm_category(category: str) -> HarmCategory:
    category = category.upper()
    if "HARASSMENT" in category:
        return HarmCategory.HARM_CATEGORY_HARASSMENT
    elif "HATE_SPEECH" in category:
        return HarmCategory.HARM_CATEGORY_HATE_SPEECH
    elif "SEXUALLY_EXPLICIT" in category:
        return HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT
    elif "DANGEROUS_CONTENT" in category:
        return HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT
    else:
        # NOTE: Although there is an "UNSPECIFIED" category, in the
        # documentation, the API does not accept it.
        raise ValueError(f"Unknown HarmCategory: {category}")


def str_to_harm_block_threshold(threshold: str) -> HarmBlockThreshold:
    threshold = threshold.upper()
    if "LOW" in threshold:
        return HarmBlockThreshold.BLOCK_LOW_AND_ABOVE
    elif "MEDIUM" in threshold:
        return HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
    elif "HIGH" in threshold:
        return HarmBlockThreshold.BLOCK_ONLY_HIGH
    elif "NONE" in threshold:
        return HarmBlockThreshold.BLOCK_NONE
    else:
        raise ValueError(f"Unknown HarmBlockThreshold: {threshold}")
