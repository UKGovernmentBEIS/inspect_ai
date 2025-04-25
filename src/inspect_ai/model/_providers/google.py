import functools
import hashlib
import json
import os
from copy import copy
from io import BytesIO
from logging import getLogger
from typing import Any, cast

# SDK Docs: https://googleapis.github.io/python-genai/
import anyio
from google.genai import Client
from google.genai.errors import APIError, ClientError
from google.genai.types import (
    Candidate,
    Content,
    ContentListUnion,
    ContentListUnionDict,
    File,
    FinishReason,
    FunctionCallingConfig,
    FunctionCallingConfigMode,
    FunctionDeclaration,
    FunctionResponse,
    GenerateContentConfig,
    GenerateContentResponse,
    GenerateContentResponsePromptFeedback,
    GenerateContentResponseUsageMetadata,
    HarmBlockThreshold,
    HarmCategory,
    HttpOptions,
    Part,
    SafetySetting,
    SafetySettingDict,
    Schema,
    ThinkingConfig,
    Tool,
    ToolConfig,
    ToolListUnion,
    Type,
)
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, NO_CONTENT
from inspect_ai._util.content import (
    Content as InspectContent,
)
from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import file_as_data
from inspect_ai._util.kvstore import inspect_kvstore
from inspect_ai._util.trace import trace_message
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Logprob,
    Logprobs,
    ModelAPI,
    ModelOutput,
    ModelUsage,
    StopReason,
    TopLogprob,
)
from inspect_ai.model._model_call import ModelCall
from inspect_ai.tool import (
    ToolCall,
    ToolChoice,
    ToolFunction,
    ToolInfo,
    ToolParam,
    ToolParams,
)

from .util import model_base_url
from .util.hooks import HttpHooks, HttpxHooks

logger = getLogger(__name__)


GOOGLE_API_KEY = "GOOGLE_API_KEY"
VERTEX_API_KEY = "VERTEX_API_KEY"

SAFETY_SETTINGS = "safety_settings"
DEFAULT_SAFETY_SETTINGS: list[SafetySettingDict] = [
    {
        "category": HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_HARASSMENT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
]


class GoogleGenAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        api_key: str | None,
        config: GenerateConfig = GenerateConfig(),
        api_version: str | None = None,
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GOOGLE_API_KEY, VERTEX_API_KEY],
            config=config,
        )

        # record api version
        self.api_version = api_version

        # pick out user-provided safety settings and merge against default
        self.safety_settings: list[SafetySettingDict] = DEFAULT_SAFETY_SETTINGS.copy()
        if SAFETY_SETTINGS in model_args:

            def update_safety_setting(
                category: HarmCategory, threshold: HarmBlockThreshold
            ) -> None:
                for setting in self.safety_settings:
                    if setting["category"] == category:
                        setting["threshold"] = threshold
                        break

            user_safety_settings = parse_safety_settings(
                model_args.get(SAFETY_SETTINGS)
            )
            for safety_setting in user_safety_settings:
                if safety_setting["category"] and safety_setting["threshold"]:
                    update_safety_setting(
                        safety_setting["category"], safety_setting["threshold"]
                    )

            del model_args[SAFETY_SETTINGS]

        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            self.service: str | None = parts[0]
        else:
            self.service = None

        # vertex can also be forced by the GOOGLE_GENAI_USE_VERTEX_AI flag
        if self.service is None:
            if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
                self.service = "vertex"

        # ensure we haven't specified an invalid service
        if self.service is not None and self.service != "vertex":
            raise RuntimeError(
                f"Invalid service name for google: {self.service}. "
                + "Currently 'vertex' is the only supported service."
            )

        # handle auth (vertex or standard google api key)
        if self.is_vertex():
            # see if we are running in express mode (propagate api key if we are)
            # https://cloud.google.com/vertex-ai/generative-ai/docs/start/express-mode/overview
            vertex_api_key = os.environ.get(VERTEX_API_KEY, None)
            if vertex_api_key and not self.api_key:
                self.api_key = vertex_api_key

            # When not using express mode the GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION
            # environment variables should be set, OR the 'project' and 'location' should be
            # passed within the model_args.
            # https://cloud.google.com/vertex-ai/generative-ai/docs/gemini-v2
            if not vertex_api_key:
                if not os.environ.get(
                    "GOOGLE_CLOUD_PROJECT", None
                ) and not model_args.get("project", None):
                    raise PrerequisiteError(
                        "Google provider requires either the GOOGLE_CLOUD_PROJECT environment variable "
                        + "or the 'project' custom model arg (-M) when running against vertex."
                    )
                if not os.environ.get(
                    "GOOGLE_CLOUD_LOCATION", None
                ) and not model_args.get("location", None):
                    raise PrerequisiteError(
                        "Google provider requires either the GOOGLE_CLOUD_LOCATION environment variable "
                        + "or the 'location' custom model arg (-M) when running against vertex."
                    )

        # normal google endpoint
        else:
            # read api key from env
            if not self.api_key:
                self.api_key = os.environ.get(GOOGLE_API_KEY, None)

            # custom base_url
            self.base_url = model_base_url(self.base_url, "GOOGLE_BASE_URL")

        # save model args
        self.model_args = model_args

    def is_vertex(self) -> bool:
        return self.service == "vertex"

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # create client
        client = Client(
            vertexai=self.is_vertex(),
            api_key=self.api_key,
            http_options={
                "base_url": self.base_url,
                "api_version": self.api_version,
            },
            **self.model_args,
        )

        # create hooks and allocate request
        http_hooks = HttpxHooks(client._api_client._async_httpx_client)
        request_id = http_hooks.start_request()

        # Create google-genai types.
        gemini_contents = await as_chat_messages(client, input)
        gemini_tools = chat_tools(tools) if len(tools) > 0 else None
        gemini_tool_config = chat_tool_config(tool_choice) if len(tools) > 0 else None
        parameters = GenerateContentConfig(
            http_options=HttpOptions(headers={HttpHooks.REQUEST_ID_HEADER: request_id}),
            temperature=config.temperature,
            top_p=config.top_p,
            top_k=config.top_k,
            max_output_tokens=config.max_tokens,
            stop_sequences=config.stop_seqs,
            candidate_count=config.num_choices,
            presence_penalty=config.presence_penalty,
            frequency_penalty=config.frequency_penalty,
            safety_settings=safety_settings_to_list(self.safety_settings),
            tools=gemini_tools,
            tool_config=gemini_tool_config,
            system_instruction=await extract_system_message_as_parts(client, input),  # type: ignore[arg-type]
            thinking_config=self.chat_thinking_config(config),
        )
        if config.response_schema is not None:
            parameters.response_mime_type = "application/json"
            parameters.response_schema = schema_from_param(
                config.response_schema.json_schema, nullable=None
            )

        response: GenerateContentResponse | None = None

        def model_call() -> ModelCall:
            return build_model_call(
                contents=gemini_contents,  # type: ignore[arg-type]
                safety_settings=self.safety_settings,
                generation_config=parameters,
                tools=gemini_tools,
                tool_config=gemini_tool_config,
                response=response,
                time=http_hooks.end_request(request_id),
            )

        try:
            response = await client.aio.models.generate_content(
                model=self.service_model_name(),
                contents=gemini_contents,  # type: ignore[arg-type]
                config=parameters,
            )
        except ClientError as ex:
            return self.handle_client_error(ex), model_call()

        model_name = response.model_version or self.service_model_name()
        output = ModelOutput(
            model=model_name,
            choices=completion_choices_from_candidates(model_name, response),
            usage=usage_metadata_to_model_usage(response.usage_metadata),
        )

        return output, model_call()

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    def is_gemini(self) -> bool:
        return "gemini-" in self.service_model_name()

    def is_gemini_1_5(self) -> bool:
        return "gemini-1.5" in self.service_model_name()

    def is_gemini_2_0(self) -> bool:
        return "gemini-2.0" in self.service_model_name()

    @override
    def should_retry(self, ex: Exception) -> bool:
        if isinstance(ex, APIError) and ex.code is not None:
            return is_retryable_http_status(ex.code)
        else:
            return False

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections."""
        return str(self.api_key)

    def handle_client_error(self, ex: ClientError) -> ModelOutput | Exception:
        if (
            ex.code == 400
            and ex.message
            and (
                "maximum number of tokens" in ex.message
                or "size exceeds the limit" in ex.message
            )
        ):
            return ModelOutput.from_content(
                self.service_model_name(),
                content=ex.message,
                stop_reason="model_length",
            )
        else:
            raise ex

    def chat_thinking_config(self, config: GenerateConfig) -> ThinkingConfig | None:
        # thinking_config is only supported for gemini 2.5 above
        has_thinking_config = (
            self.is_gemini() and not self.is_gemini_1_5() and not self.is_gemini_2_0()
        )
        if has_thinking_config:
            return ThinkingConfig(
                include_thoughts=True, thinking_budget=config.reasoning_tokens
            )
        else:
            return None


def safety_settings_to_list(
    safety_settings: list[SafetySettingDict],
) -> list[SafetySetting]:
    settings: list[SafetySetting] = []
    for setting in safety_settings:
        settings.append(
            SafetySetting(category=setting["category"], threshold=setting["threshold"])
        )
    return settings


def build_model_call(
    contents: ContentListUnion | ContentListUnionDict,
    generation_config: GenerateContentConfig,
    safety_settings: list[SafetySettingDict],
    tools: ToolListUnion | None,
    tool_config: ToolConfig | None,
    response: GenerateContentResponse | None,
    time: float | None,
) -> ModelCall:
    return ModelCall.create(
        request=dict(
            contents=contents,
            generation_config=generation_config,
            safety_settings=safety_settings,
            tools=tools if tools is not None else None,
            tool_config=tool_config if tool_config is not None else None,
        ),
        response=response if response is not None else {},
        filter=model_call_filter,
        time=time,
    )


def model_call_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    if key == "inline_data" and isinstance(value, dict) and "data" in value:
        value = copy(value)
        value.update(data=BASE_64_DATA_REMOVED)
    return value


async def as_chat_messages(
    client: Client, messages: list[ChatMessage]
) -> list[Content]:
    # There is no "system" role in the `google-genai` package. Instead, system messages
    # are included in the `GenerateContentConfig` as a `system_instruction`. Strip any
    # system messages out.
    supported_messages = [message for message in messages if message.role != "system"]

    # build google chat messages
    chat_messages = [await content(client, message) for message in supported_messages]

    # combine consecutive tool messages
    chat_messages = functools.reduce(
        consecutive_tool_message_reducer, chat_messages, []
    )

    # return messages
    return chat_messages


def consecutive_tool_message_reducer(
    messages: list[Content],
    message: Content,
) -> list[Content]:
    if (
        message.role == "function"
        and len(messages) > 0
        and messages[-1].role == "function"
    ):
        messages[-1] = Content(
            role="function", parts=(messages[-1].parts or []) + (message.parts or [])
        )
    else:
        messages.append(message)
    return messages


async def content(
    client: Client,
    message: ChatMessageUser | ChatMessageAssistant | ChatMessageTool,
) -> Content:
    if isinstance(message, ChatMessageUser):
        if isinstance(message.content, str):
            return Content(
                role="user", parts=[await content_part(client, message.content)]
            )
        return Content(
            role="user",
            parts=(
                [await content_part(client, content) for content in message.content]
            ),
        )
    elif isinstance(message, ChatMessageAssistant):
        content_parts: list[Part] = []
        # tool call parts
        if message.tool_calls is not None:
            content_parts.extend(
                [
                    Part.from_function_call(
                        name=tool_call.function,
                        args=tool_call.arguments,
                    )
                    for tool_call in message.tool_calls
                ]
            )

        # content parts
        if isinstance(message.content, str):
            content_parts.append(Part(text=message.content or NO_CONTENT))
        else:
            content_parts.extend(
                [await content_part(client, content) for content in message.content]
            )

        # return parts
        return Content(role="model", parts=content_parts)

    elif isinstance(message, ChatMessageTool):
        response = FunctionResponse(
            name=message.tool_call_id,
            response={
                "content": (
                    message.error.message if message.error is not None else message.text
                )
            },
        )
        return Content(role="function", parts=[Part(function_response=response)])


async def content_part(client: Client, content: InspectContent | str) -> Part:
    if isinstance(content, str):
        return Part.from_text(text=content or NO_CONTENT)
    elif isinstance(content, ContentText):
        return Part.from_text(text=content.text or NO_CONTENT)
    elif isinstance(content, ContentReasoning):
        return Part.from_text(text=content.reasoning or NO_CONTENT)
    else:
        return await chat_content_to_part(client, content)


async def chat_content_to_part(
    client: Client,
    content: ContentImage | ContentAudio | ContentVideo,
) -> Part:
    if isinstance(content, ContentImage):
        content_bytes, mime_type = await file_as_data(content.image)
        return Part.from_bytes(mime_type=mime_type, data=content_bytes)
    else:
        file = await file_for_content(client, content)
        if file.uri is None:
            raise RuntimeError(f"Failed to get URI for file: {file.display_name}")
        return Part.from_uri(file_uri=file.uri, mime_type=file.mime_type)


async def extract_system_message_as_parts(
    client: Client,
    messages: list[ChatMessage],
) -> list[File | Part | str] | None:
    system_parts: list[File | Part | str] = []
    for message in messages:
        if message.role == "system":
            content = message.content
            if isinstance(content, str):
                system_parts.append(Part.from_text(text=content))
            elif isinstance(content, list):  # list[InspectContent]
                system_parts.extend(
                    [await content_part(client, content) for content in content]
                )
            else:
                raise ValueError(f"Unsupported system message content: {content}")
    # google-genai raises "ValueError: content is required." if the list is empty.
    return system_parts or None


def chat_tools(tools: list[ToolInfo]) -> ToolListUnion:
    declarations = [
        FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=schema_from_param(tool.parameters)
            if len(tool.parameters.properties) > 0
            else None,
        )
        for tool in tools
    ]
    return [Tool(function_declarations=declarations)]


# https://ai.google.dev/gemini-api/tutorials/extract_structured_data#define_the_schema
def schema_from_param(
    param: ToolParam | ToolParams, nullable: bool | None = False
) -> Schema:
    if isinstance(param, ToolParams):
        param = ToolParam(
            type=param.type, properties=param.properties, required=param.required
        )

    if param.type == "number":
        return Schema(
            type=Type.NUMBER, description=param.description, nullable=nullable
        )
    elif param.type == "integer":
        return Schema(
            type=Type.INTEGER, description=param.description, nullable=nullable
        )
    elif param.type == "boolean":
        return Schema(
            type=Type.BOOLEAN, description=param.description, nullable=nullable
        )
    elif param.type == "string":
        if param.format == "date-time":
            return Schema(
                type=Type.STRING,
                description=param.description,
                format="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
                nullable=nullable,
            )
        elif param.format == "date":
            return Schema(
                type=Type.STRING,
                description=param.description,
                format="^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                nullable=nullable,
            )
        elif param.format == "time":
            return Schema(
                type=Type.STRING,
                description=param.description,
                format="^[0-9]{2}:[0-9]{2}:[0-9]{2}$",
                nullable=nullable,
            )
        return Schema(
            type=Type.STRING, description=param.description, nullable=nullable
        )
    elif param.type == "array":
        return Schema(
            type=Type.ARRAY,
            description=param.description,
            items=schema_from_param(param.items) if param.items else None,
            nullable=nullable,
        )
    elif param.type == "object":
        return Schema(
            type=Type.OBJECT,
            description=param.description,
            properties={k: schema_from_param(v) for k, v in param.properties.items()}
            if param.properties is not None
            else {},
            required=param.required,
            nullable=nullable,
        )
    # convert unions to optional params if the second type is 'null'
    elif param.anyOf:
        if len(param.anyOf) == 2 and param.anyOf[1].type == "null":
            return schema_from_param(param.anyOf[0], nullable=True)
        else:
            return Schema(type=Type.TYPE_UNSPECIFIED)
    elif param.enum:
        return Schema(type=Type.STRING, format="enum", enum=param.enum)
    else:
        return Schema(type=Type.TYPE_UNSPECIFIED)


def chat_tool_config(tool_choice: ToolChoice) -> ToolConfig:
    if isinstance(tool_choice, ToolFunction):
        return ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=FunctionCallingConfigMode.ANY,
                allowed_function_names=[tool_choice.name],
            )
        )
    else:
        return ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=cast(FunctionCallingConfigMode, tool_choice.upper())
            )
        )


def completion_choice_from_candidate(
    model: str, candidate: Candidate
) -> ChatCompletionChoice:
    # content can be None when the finish_reason is SAFETY
    if candidate.content is None:
        content: (
            str
            | list[
                ContentText
                | ContentReasoning
                | ContentImage
                | ContentAudio
                | ContentVideo
            ]
        ) = ""
    # content.parts can be None when the finish_reason is MALFORMED_FUNCTION_CALL
    elif candidate.content.parts is None:
        content = ""
    else:
        content = []
        for part in candidate.content.parts:
            if part.text is not None:
                if part.thought is True:
                    content.append(ContentReasoning(reasoning=part.text))
                else:
                    content.append(ContentText(text=part.text))

    # now tool calls
    tool_calls: list[ToolCall] = []
    if candidate.content is not None and candidate.content.parts is not None:
        for part in candidate.content.parts:
            if part.function_call:
                if (
                    part.function_call is not None
                    and part.function_call.name is not None
                    and part.function_call.args is not None
                ):
                    tool_calls.append(
                        ToolCall(
                            id=part.function_call.name,
                            function=part.function_call.name,
                            arguments=part.function_call.args,
                        )
                    )
                else:
                    raise ValueError(f"Incomplete function call: {part.function_call}")

    # stop reason
    stop_reason = finish_reason_to_stop_reason(
        candidate.finish_reason or FinishReason.STOP
    )

    # build choice
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content,
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            model=model,
            source="generate",
        ),
        stop_reason=stop_reason,
    )

    # add logprobs if provided
    if candidate.logprobs_result:
        logprobs: list[Logprob] = []
        if (
            candidate.logprobs_result.chosen_candidates
            and candidate.logprobs_result.top_candidates
        ):
            for chosen, top in zip(
                candidate.logprobs_result.chosen_candidates,
                candidate.logprobs_result.top_candidates,
            ):
                if chosen.token and chosen.log_probability:
                    logprobs.append(
                        Logprob(
                            token=chosen.token,
                            logprob=chosen.log_probability,
                            top_logprobs=[
                                TopLogprob(token=c.token, logprob=c.log_probability)
                                for c in (top.candidates or [])
                                if c.token and c.log_probability
                            ],
                        )
                    )
            choice.logprobs = Logprobs(content=logprobs)

    return choice


def completion_choices_from_candidates(
    model: str,
    response: GenerateContentResponse,
) -> list[ChatCompletionChoice]:
    candidates = response.candidates
    if candidates:
        candidates_list = sorted(candidates, key=lambda c: c.index or 0)
        return [
            completion_choice_from_candidate(model, candidate)
            for candidate in candidates_list
        ]
    elif response.prompt_feedback:
        return [
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=prompt_feedback_to_content(response.prompt_feedback),
                    model=model,
                    source="generate",
                ),
                stop_reason="content_filter",
            )
        ]
    else:
        return [
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=NO_CONTENT,
                    model=model,
                    source="generate",
                ),
                stop_reason="stop",
            )
        ]


def prompt_feedback_to_content(
    feedback: GenerateContentResponsePromptFeedback,
) -> str:
    content: list[str] = []
    block_reason = str(feedback.block_reason) if feedback.block_reason else "UNKNOWN"
    content.append(f"BLOCKED: {block_reason}")

    if feedback.block_reason_message is not None:
        content.append(feedback.block_reason_message)
    if feedback.safety_ratings is not None:
        content.extend(
            [rating.model_dump_json(indent=2) for rating in feedback.safety_ratings]
        )
    return "\n".join(content)


def usage_metadata_to_model_usage(
    metadata: GenerateContentResponseUsageMetadata | None,
) -> ModelUsage | None:
    if metadata is None:
        return None
    return ModelUsage(
        input_tokens=metadata.prompt_token_count or 0,
        output_tokens=metadata.candidates_token_count or 0,
        total_tokens=metadata.total_token_count or 0,
        reasoning_tokens=metadata.thoughts_token_count or 0,
    )


def finish_reason_to_stop_reason(finish_reason: FinishReason) -> StopReason:
    match finish_reason:
        case FinishReason.STOP:
            return "stop"
        case FinishReason.MAX_TOKENS:
            return "max_tokens"
        case (
            FinishReason.SAFETY
            | FinishReason.RECITATION
            | FinishReason.BLOCKLIST
            | FinishReason.PROHIBITED_CONTENT
            | FinishReason.SPII
        ):
            return "content_filter"
        case _:
            # Note: to avoid adding another option to StopReason,
            # this includes FinishReason.MALFORMED_FUNCTION_CALL
            return "unknown"


def parse_safety_settings(
    safety_settings: Any,
) -> list[SafetySettingDict]:
    # ensure we have a dict
    if isinstance(safety_settings, str):
        safety_settings = json.loads(safety_settings)
    if not isinstance(safety_settings, dict):
        raise ValueError(f"{SAFETY_SETTINGS} must be dictionary.")

    parsed_settings: list[SafetySettingDict] = []
    for key, value in safety_settings.items():
        if not isinstance(key, str):
            raise ValueError(f"Unexpected type for harm category: {key}")
        if not isinstance(value, str):
            raise ValueError(f"Unexpected type for harm block threshold: {value}")
        key = str_to_harm_category(key)
        value = str_to_harm_block_threshold(value)
        parsed_settings.append({"category": key, "threshold": value})
    return parsed_settings


def str_to_harm_category(category: str) -> HarmCategory:
    category = category.upper()
    # `in` instead of `==` to allow users to pass in short version e.g. "HARASSMENT" or
    # long version e.g. "HARM_CATEGORY_HARASSMENT" strings.
    if "CIVIC_INTEGRITY" in category:
        return HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY
    if "DANGEROUS_CONTENT" in category:
        return HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT
    if "HATE_SPEECH" in category:
        return HarmCategory.HARM_CATEGORY_HATE_SPEECH
    if "HARASSMENT" in category:
        return HarmCategory.HARM_CATEGORY_HARASSMENT
    if "SEXUALLY_EXPLICIT" in category:
        return HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT
    if "UNSPECIFIED" in category:
        return HarmCategory.HARM_CATEGORY_UNSPECIFIED
    raise ValueError(f"Unknown HarmCategory: {category}")


def str_to_harm_block_threshold(threshold: str) -> HarmBlockThreshold:
    threshold = threshold.upper()
    if "LOW" in threshold:
        return HarmBlockThreshold.BLOCK_LOW_AND_ABOVE
    if "MEDIUM" in threshold:
        return HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
    if "HIGH" in threshold:
        return HarmBlockThreshold.BLOCK_ONLY_HIGH
    if "NONE" in threshold:
        return HarmBlockThreshold.BLOCK_NONE
    if "OFF" in threshold:
        return HarmBlockThreshold.OFF
    raise ValueError(f"Unknown HarmBlockThreshold: {threshold}")


async def file_for_content(
    client: Client, content: ContentAudio | ContentVideo
) -> File:
    # helper to write trace messages
    def trace(message: str) -> None:
        trace_message(logger, "Google Files", message)

    # get the file bytes and compute sha256 hash
    if isinstance(content, ContentAudio):
        file = content.audio
    else:
        file = content.video
    content_bytes, mime_type = await file_as_data(file)
    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    # we cache uploads for re-use, open the db where we track that
    # (track up to 1 million previous uploads)
    with inspect_kvstore("google_files", 1000000) as files_db:
        # can we serve from existing uploads?
        uploaded_file = files_db.get(content_sha256)
        if uploaded_file:
            try:
                upload: File = client.files.get(name=uploaded_file)
                assert upload.state
                if upload.state.name == "ACTIVE":
                    trace(f"Using uploaded file: {uploaded_file}")
                    return upload
                else:
                    trace(
                        f"Not using uploaded file '{uploaded_file} (state was {upload.state})"
                    )
            except Exception as ex:
                trace(f"Error attempting to access uploaded file: {ex}")
                files_db.delete(content_sha256)
        # do the upload (and record it)
        upload = client.files.upload(
            file=BytesIO(content_bytes), config=dict(mime_type=mime_type)
        )
        while upload.state.name == "PROCESSING":  # type: ignore[union-attr]
            await anyio.sleep(3)
            assert upload.name
            upload = client.files.get(name=upload.name)
        if upload.state.name == "FAILED":  # type: ignore[union-attr]
            trace(f"Failed to upload file '{upload.name}: {upload.error}")
            raise ValueError(f"Google file upload failed: {upload.error}")
        # trace and record it
        trace(f"Uploaded file: {upload.name}")
        files_db.put(content_sha256, str(upload.name))
        # return the file
        return upload
