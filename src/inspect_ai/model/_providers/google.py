import asyncio
import functools
import hashlib
import json
import os
from copy import copy
from io import BytesIO
from logging import getLogger
from typing import Any

# SDK Docs: https://googleapis.github.io/python-genai/
from google.genai import Client  # type: ignore
from google.genai.errors import APIError, ClientError  # type: ignore
from google.genai.types import (  # type: ignore
    Candidate,
    Content,
    File,
    FinishReason,
    FunctionCallingConfig,
    FunctionDeclaration,
    FunctionResponse,
    GenerateContentConfig,
    GenerateContentResponse,
    GenerateContentResponsePromptFeedback,
    GenerateContentResponseUsageMetadata,
    GenerationConfig,
    HarmBlockThreshold,
    HarmCategory,
    Part,
    SafetySetting,
    SafetySettingDict,
    Schema,
    Tool,
    ToolConfig,
    Type,
)
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, NO_CONTENT
from inspect_ai._util.content import Content as InspectContent
from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.error import PrerequisiteError
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
from inspect_ai.model._providers.util import model_base_url
from inspect_ai.tool import (
    ToolCall,
    ToolChoice,
    ToolFunction,
    ToolInfo,
    ToolParam,
    ToolParams,
)

logger = getLogger(__name__)


GOOGLE_API_KEY = "GOOGLE_API_KEY"
VERTEX_API_KEY = "VERTEX_API_KEY"

SAFETY_SETTINGS = "safety_settings"
DEFAULT_SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
}


class GoogleGenAIAPI(ModelAPI):
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
            api_key_vars=[GOOGLE_API_KEY, VERTEX_API_KEY],
            config=config,
        )

        # pick out user-provided safety settings and merge against default
        self.safety_settings = DEFAULT_SAFETY_SETTINGS.copy()
        if SAFETY_SETTINGS in model_args:
            self.safety_settings.update(
                parse_safety_settings(model_args.get(SAFETY_SETTINGS))
            )
            del model_args[SAFETY_SETTINGS]

        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            self.service: str | None = parts[0]
            model_name = "/".join(parts[1:])
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
            base_url = model_base_url(base_url, "GOOGLE_BASE_URL")

        # create client
        self.client = Client(
            vertexai=self.is_vertex(),
            api_key=self.api_key,
            http_options={"base_url": base_url},
            **model_args,
        )

    @override
    async def close(self) -> None:
        # GenerativeModel uses a cached/shared client so there is no 'close'
        pass

    def is_vertex(self) -> bool:
        return self.service == "vertex"

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # Create google-genai types.
        gemini_contents = await as_chat_messages(self.client, input)
        gemini_tools = chat_tools(tools) if len(tools) > 0 else None
        gemini_tool_config = chat_tool_config(tool_choice) if len(tools) > 0 else None
        parameters = GenerateContentConfig(
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
            system_instruction=await extract_system_message_as_parts(
                self.client, input
            ),
        )

        response: GenerateContentResponse | None = None

        def model_call() -> ModelCall:
            return build_model_call(
                contents=gemini_contents,
                safety_settings=self.safety_settings,
                generation_config=parameters,
                tools=gemini_tools,
                tool_config=gemini_tool_config,
                response=response,
            )

        # TODO: would need to monkey patch AuthorizedSession.request

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=gemini_contents,
                config=parameters,
            )
        except ClientError as ex:
            return self.handle_client_error(ex), model_call()

        output = ModelOutput(
            model=self.model_name,
            choices=completion_choices_from_candidates(response),
            usage=usage_metadata_to_model_usage(response.usage_metadata),
        )

        return output, model_call()

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        return isinstance(ex, APIError) and ex.code in (429, 500, 503, 504)

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return self.model_name

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
                self.model_name, content=ex.message, stop_reason="model_length"
            )
        else:
            raise ex


def safety_settings_to_list(safety_settings: SafetySettingDict) -> list[SafetySetting]:
    return [
        SafetySetting(
            category=category,
            threshold=threshold,
        )
        for category, threshold in safety_settings.items()
    ]


def build_model_call(
    contents: list[Content],
    generation_config: GenerationConfig,
    safety_settings: SafetySettingDict,
    tools: list[Tool] | None,
    tool_config: ToolConfig | None,
    response: GenerateContentResponse | None,
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
            role="function", parts=messages[-1].parts + message.parts
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
        return await file_for_content(client, content)


async def extract_system_message_as_parts(
    client: Client,
    messages: list[ChatMessage],
) -> list[Part] | None:
    system_parts: list[Part] = []
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


def chat_tools(tools: list[ToolInfo]) -> list[Tool]:
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
def schema_from_param(param: ToolParam | ToolParams, nullable: bool = False) -> Schema:
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
                mode="ANY", allowed_function_names=[tool_choice.name]
            )
        )
    else:
        return ToolConfig(
            function_calling_config=FunctionCallingConfig(mode=tool_choice.upper())
        )


def completion_choice_from_candidate(candidate: Candidate) -> ChatCompletionChoice:
    # check for completion text
    content = ""
    # content can be None when the finish_reason is SAFETY
    if candidate.content is not None:
        content = " ".join(
            [
                part.text
                for part in candidate.content.parts
                if part.text is not None and candidate.content is not None
            ]
        )

    # split reasoning
    reasoning, content = split_reasoning(content)

    # now tool calls
    tool_calls: list[ToolCall] = []
    if candidate.content is not None and candidate.content.parts is not None:
        for part in candidate.content.parts:
            if part.function_call:
                tool_calls.append(
                    ToolCall(
                        type="function",
                        id=part.function_call.name,
                        function=part.function_call.name,
                        arguments=part.function_call.args,
                    )
                )

    # stop reason
    stop_reason = finish_reason_to_stop_reason(candidate.finish_reason)

    # build choice
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            source="generate",
        ),
        stop_reason=stop_reason,
    )

    # add logprobs if provided
    if candidate.logprobs_result:
        logprobs: list[Logprob] = []
        for chosen, top in zip(
            candidate.logprobs_result.chosen_candidates,
            candidate.logprobs_result.top_candidates,
        ):
            logprobs.append(
                Logprob(
                    token=chosen.token,
                    logprob=chosen.log_probability,
                    top_logprobs=[
                        TopLogprob(token=c.token, logprob=c.log_probability)
                        for c in top.candidates
                    ],
                )
            )
        choice.logprobs = Logprobs(content=logprobs)

    return choice


def completion_choices_from_candidates(
    response: GenerateContentResponse,
) -> list[ChatCompletionChoice]:
    candidates = response.candidates
    if candidates:
        candidates_list = sorted(candidates, key=lambda c: c.index)
        return [
            completion_choice_from_candidate(candidate) for candidate in candidates_list
        ]
    elif response.prompt_feedback:
        return [
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=prompt_feedback_to_content(response.prompt_feedback),
                    source="generate",
                ),
                stop_reason="content_filter",
            )
        ]
    else:
        raise RuntimeError(
            "Google response includes no completion candidates and no block reason: "
            + f"{response.model_dump_json(indent=2)}"
        )


def split_reasoning(content: str) -> tuple[str | None, str]:
    separator = "\nFinal Answer: "
    if separator in content:
        parts = content.split(separator, 1)  # dplit only on first occurrence
        return parts[0].strip(), separator.lstrip() + parts[1].strip()
    else:
        return None, content.strip()


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
    metadata: GenerateContentResponseUsageMetadata,
) -> ModelUsage | None:
    if metadata is None:
        return None
    return ModelUsage(
        input_tokens=metadata.prompt_token_count or 0,
        output_tokens=metadata.candidates_token_count or 0,
        total_tokens=metadata.total_token_count or 0,
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
            return "unknown"


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
        if not isinstance(key, str):
            raise ValueError(f"Unexpected type for harm category: {key}")
        if not isinstance(value, str):
            raise ValueError(f"Unexpected type for harm block threshold: {value}")
        key = str_to_harm_category(key)
        value = str_to_harm_block_threshold(value)
        parsed_settings[key] = value
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
                upload: File = client.files.get(uploaded_file)
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
        upload = client.files.upload(BytesIO(content_bytes), mime_type=mime_type)
        while upload.state.name == "PROCESSING":
            await asyncio.sleep(3)
            upload = client.files.get(upload.name)
        if upload.state.name == "FAILED":
            trace(f"Failed to upload file '{upload.name}: {upload.error}")
            raise ValueError(f"Google file upload failed: {upload.error}")
        # trace and record it
        trace(f"Uploaded file: {upload.name}")
        files_db.put(content_sha256, upload.name)
        # return the file
        return upload
