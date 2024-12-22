import base64
from typing import Any, Literal, Tuple, Union, cast

from pydantic import BaseModel, Field
from typing_extensions import override

from inspect_ai._util.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
)
from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.images import image_as_data
from inspect_ai._util.version import verify_required_version
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolFunction

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
)
from .util import (
    model_base_url,
)

# Model for Bedrock Converse API (Response)
# generated from: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html#converse

ConverseRole = Literal["user", "assistant"]
ConverseImageFormat = Literal["png", "jpeg", "gif", "webp"]
ConverseDocumentFormat = Literal[
    "pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"
]
ConverseToolResultStatus = Literal["success", "error"]
ConverseStopReason = Literal[
    "end_turn",
    "tool_use",
    "max_tokens",
    "stop_sequence",
    "guardrail_intervened",
    "content_filtered",
]
ConverseGuardContentQualifier = Literal["grounding_source", "query", "guard_content"]
ConverseFilterType = Literal[
    "INSULTS", "HATE", "SEXUAL", "VIOLENCE", "MISCONDUCT", "PROMPT_ATTACK"
]
ConverseFilterConfidence = Literal["NONE", "LOW", "MEDIUM", "HIGH"]
ConverseFilterStrength = Literal["NONE", "LOW", "MEDIUM", "HIGH"]


class ConverseImageSource(BaseModel):
    bytes: bytes


class ConverseDocumentSource(BaseModel):
    bytes: bytes


class ConverseImage(BaseModel):
    format: ConverseImageFormat
    source: ConverseImageSource


class ConverseDocument(BaseModel):
    format: ConverseDocumentFormat
    name: str
    source: ConverseDocumentSource


class ConverseToolUse(BaseModel):
    toolUseId: str
    name: str
    input: Union[dict[str, Any], list[Any], int, float, str, bool, None]


class ConverseToolResultContent(BaseModel):
    json_content: Union[dict[str, Any], list[Any], int, float, str, bool, None] = Field(
        default=None, alias="json"
    )
    text: str | None = None
    image: ConverseImage | None = None
    document: ConverseDocument | None = None


class ConverseToolResult(BaseModel):
    toolUseId: str
    content: list[ConverseToolResultContent]
    status: ConverseToolResultStatus


class ConverseGuardContentText(BaseModel):
    text: str
    qualifiers: list[ConverseGuardContentQualifier]


class ConverseGuardContent(BaseModel):
    text: ConverseGuardContentText


class ConverseMessageContent(BaseModel):
    text: str | None = None
    image: ConverseImage | None = None
    document: ConverseDocument | None = None
    toolUse: ConverseToolUse | None = None
    toolResult: ConverseToolResult | None = None
    guardContent: ConverseGuardContent | None = None


class ConverseMessage(BaseModel):
    role: ConverseRole
    content: list[ConverseMessageContent]


class ConverseOutput(BaseModel):
    message: ConverseMessage


class ConverseUsage(BaseModel):
    inputTokens: int
    outputTokens: int
    totalTokens: int


class ConverseMetrics(BaseModel):
    latencyMs: int


class ConverseTraceGuardrailFilter(BaseModel):
    type: ConverseFilterType
    confidence: ConverseFilterConfidence
    filterStrength: ConverseFilterStrength
    action: str


class ConverseAdditionalModelResponseFields(BaseModel):
    value: Union[dict[str, Any], list[Any], int, float, str, bool, None]


class ConverseResponse(BaseModel):
    output: ConverseOutput
    stopReason: ConverseStopReason
    usage: ConverseUsage
    metrics: ConverseMetrics
    additionalModelResponseFields: ConverseAdditionalModelResponseFields | None = None
    trace: dict[str, Any] | None = None


# Model for Bedrock Converse API (Request)
# generated from: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html#converse
class ConverseSource(BaseModel):
    bytes: bytes


class ConverseContent(BaseModel):
    text: str | None = None
    image: ConverseImage | None = None
    document: ConverseDocument | None = None
    toolUse: ConverseToolUse | None = None
    toolResult: ConverseToolResult | None = None
    guardContent: ConverseGuardContent | None = None


class ConverseSystemContent(BaseModel):
    text: str | None = None
    guardContent: ConverseGuardContent | None = None


class ConverseInferenceConfig(BaseModel):
    maxTokens: int | None = None
    temperature: float | None = None
    topP: float | None = None
    stopSequences: list[str] | None = None


class ConverseToolSpec(BaseModel):
    name: str
    description: str | None = None
    inputSchema: (
        Union[dict[str, Any], list[Any], int, float, str, bool, None] | None
    ) = None


class ConverseTool(BaseModel):
    toolSpec: ConverseToolSpec


class ConverseToolChoice(BaseModel):
    auto: dict[str, Any] | None = None
    any: dict[str, Any] | None = None
    tool: dict[str, str] | None = None


class ConverseToolConfig(BaseModel):
    tools: list[ConverseTool] | None = None
    toolChoice: ConverseToolChoice | None = None


class ConverseGuardrailConfig(BaseModel):
    guardrailIdentifier: str | None = None
    guardrailVersion: str | None = None
    trace: str | None = None


class ConversePromptVariable(BaseModel):
    text: str


class ConverseClientConverseRequest(BaseModel):
    modelId: str
    messages: list[ConverseMessage]
    system: list[ConverseSystemContent] | None = None
    inferenceConfig: ConverseInferenceConfig | None = None
    toolConfig: ConverseToolConfig | None = None
    guardrailConfig: ConverseGuardrailConfig | None = None
    additionalModelRequestFields: (
        Union[dict[str, Any], list[Any], int, float, str, bool, None] | None
    ) = None
    additionalModelResponseFieldPaths: list[str] = []


class BedrockAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=model_base_url(base_url, "BEDROCK_BASE_URL"),
            api_key=api_key,
            api_key_vars=[],
            config=config,
        )

        # save model_args
        self.model_args = model_args

        # import aioboto3 on demand
        try:
            import aioboto3

            verify_required_version("Bedrock API", "aioboto3", "13.0.0")

            # Create a shared session to be used when generating
            self.session = aioboto3.Session()

        except ImportError:
            raise pip_dependency_error("Bedrock API", ["aioboto3"])

    @override
    def connection_key(self) -> str:
        return self.model_name

    @override
    def max_tokens(self) -> int | None:
        if "llama3-70" in self.model_name or "llama3-8" in self.model_name:
            return 2048

        if "llama3" in self.model_name or "claude3" in self.model_name:
            return 4096

        elif "mistral-large" in self.model_name:
            return 8192

        # Other models will just the default
        else:
            return DEFAULT_MAX_TOKENS

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        from botocore.exceptions import ClientError

        # Look for an explicit throttle exception
        if isinstance(ex, ClientError):
            if ex.response["Error"]["Code"] == "ThrottlingException":
                return True

        return super().is_rate_limit(ex)

    @override
    def collapse_user_messages(self) -> bool:
        return True

    @override
    def collapse_assistant_messages(self) -> bool:
        return True

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        from botocore.config import Config
        from botocore.exceptions import ClientError

        # The bedrock client
        async with self.session.client(  # type: ignore[call-overload]
            service_name="bedrock-runtime",
            endpoint_url=self.base_url,
            config=Config(
                connect_timeout=config.timeout if config.timeout else DEFAULT_TIMEOUT,
                read_timeout=config.timeout if config.timeout else DEFAULT_TIMEOUT,
                retries=dict(
                    max_attempts=config.max_retries
                    if config.max_retries
                    else DEFAULT_MAX_RETRIES,
                    mode="adaptive",
                ),
            ),
            **self.model_args,
        ) as client:
            # Process the tools
            resolved_tools = converse_tools(tools)
            tool_config = None
            if resolved_tools is not None:
                choice = converse_tool_choice(tool_choice)
                tool_config = ConverseToolConfig(
                    tools=resolved_tools, toolChoice=choice
                )

            # Resolve the input messages into converse messages
            system, messages = await converse_messages(input)

            try:
                # Make the request
                request = ConverseClientConverseRequest(
                    modelId=self.model_name,
                    messages=messages,
                    system=system,
                    inferenceConfig=ConverseInferenceConfig(
                        maxTokens=config.max_tokens,
                        temperature=config.temperature,
                        topP=config.top_p,
                        stopSequences=config.stop_seqs,
                    ),
                    additionalModelRequestFields={
                        "top_k": config.top_k,
                        **config.model_config,
                    },
                    toolConfig=tool_config,
                )

                # Process the reponse
                response = await client.converse(
                    **request.model_dump(exclude_none=True)
                )
                converse_response = ConverseResponse(**response)

            except ClientError as ex:
                # Look for an explicit validation exception
                if (
                    ex.response["Error"]["Code"] == "ValidationException"
                    and "Too many input tokens" in ex.response["Error"]["Message"]
                ):
                    response = ex.response["Error"]["Message"]
                    return ModelOutput.from_content(
                        model=self.model_name,
                        content=response,
                        stop_reason="model_length",
                    )
                else:
                    raise ex

        # create a model output from the response
        output = model_output_from_response(self.model_name, converse_response, tools)

        # record call
        call = ModelCall.create(
            request=replace_bytes_with_placeholder(
                request.model_dump(exclude_none=True)
            ),
            response=response,
        )

        # return
        return output, call


async def converse_messages(
    messages: list[ChatMessage],
) -> Tuple[list[ConverseSystemContent] | None, list[ConverseMessage]]:
    # Split up system messages and input messages
    system_messages: list[ChatMessage] = []
    non_system_messages: list[ChatMessage] = []
    for message in messages:
        if message.role == "system":
            system_messages.append(message)
        else:
            non_system_messages.append(message)

    # input messages
    non_system: list[ConverseMessage] = await as_converse_chat_messages(
        non_system_messages
    )

    # system messages
    system: list[ConverseSystemContent] = as_converse_system_messages(system_messages)

    return system if len(system) > 0 else None, non_system


def model_output_from_response(
    model: str, response: ConverseResponse, tools: list[ToolInfo]
) -> ModelOutput:
    # extract content and tool calls
    content: list[Content] = []
    tool_calls: list[ToolCall] = []

    # process the content in the response message
    for c in response.output.message.content:
        if c.text is not None:
            content.append(ContentText(type="text", text=c.text))
        elif c.image is not None:
            base64_image = base64.b64encode(c.image.source.bytes).decode("utf-8")
            content.append(ContentImage(image=base64_image))
        elif c.toolUse is not None:
            tool_calls.append(
                ToolCall(
                    id=c.toolUse.toolUseId,
                    type="function",
                    function=c.toolUse.name,
                    arguments=cast(dict[str, Any], c.toolUse.input or {}),
                )
            )
        else:
            raise ValueError("Unexpected message response in Bedrock provider")

    # resolve choice
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content, tool_calls=tool_calls, source="generate"
        ),
        stop_reason=message_stop_reason(response.stopReason),
    )

    # Compute usage
    input_tokens = response.usage.inputTokens
    output_tokens = response.usage.outputTokens
    total_tokens = input_tokens + output_tokens

    # return ModelOutput
    return ModelOutput(
        model=model,
        choices=[choice],
        usage=ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
    )


def message_stop_reason(
    reason: ConverseStopReason,
) -> Literal[
    "stop", "max_tokens", "model_length", "tool_calls", "content_filter", "unknown"
]:
    match reason:
        case "end_turn" | "stop_sequence":
            return "stop"
        case "tool_use":
            return "tool_calls"
        case "max_tokens":
            return reason
        case "content_filtered":
            return "content_filter"
        case "guardrail_intervened":
            return "content_filter"
        case _:
            return "unknown"


def as_converse_system_messages(
    messages: list[ChatMessage],
) -> list[ConverseSystemContent]:
    return [
        ConverseSystemContent(text=message.text) for message in messages if message.text
    ]


async def as_converse_chat_messages(
    messages: list[ChatMessage],
) -> list[ConverseMessage]:
    result: list[ConverseMessage] = []
    for message in messages:
        converse_message = await converse_chat_message(message)
        if converse_message is not None:
            result.extend(converse_message)
    return collapse_consecutive_messages(result)


async def converse_chat_message(
    message: ChatMessage,
) -> list[ConverseMessage] | None:
    if isinstance(message, ChatMessageSystem):
        raise ValueError("System messages should be processed separately for Converse")
    if isinstance(message, ChatMessageUser):
        # Simple user message
        return [
            ConverseMessage(
                role="user", content=await converse_contents(message.content)
            )
        ]
    elif isinstance(message, ChatMessageAssistant):
        if message.tool_calls:
            # The assistant is calling tools, process those
            results: list[ConverseMessage] = []
            for tool_call in message.tool_calls:
                tool_use = ConverseToolUse(
                    toolUseId=tool_call.id,
                    name=tool_call.function,
                    input=tool_call.arguments,
                )
                m = ConverseMessage(
                    role="assistant", content=[ConverseMessageContent(toolUse=tool_use)]
                )
                results.append(m)
            return results
        else:
            # Simple assistant message
            return [
                ConverseMessage(
                    role="assistant", content=await converse_contents(message.content)
                )
            ]
    elif isinstance(message, ChatMessageTool):
        # Process tool message
        if message.tool_call_id is None:
            raise ValueError(
                "Tool call is missing a tool call id, which is required for Converse API"
            )
        if message.function is None:
            raise ValueError(
                "Tool call is missing a function, which is required for Converse API"
            )

        status: Literal["success", "error"] = (
            "success" if message.error is None else "error"
        )

        # process the tool response content
        tool_result_content: list[ConverseToolResultContent] = []
        if isinstance(message.content, str):
            tool_result_content.append(ConverseToolResultContent(text=message.content))
        else:
            for c in message.content:
                if c.type == "text":
                    tool_result_content.append(ConverseToolResultContent(text=c.text))
                elif c.type == "image":
                    image_data, image_type = await image_as_data(c.image)
                    tool_result_content.append(
                        ConverseToolResultContent(
                            image=ConverseImage(
                                format=converse_image_type(image_type),
                                source=ConverseImageSource(bytes=image_data),
                            )
                        )
                    )
                else:
                    raise ValueError(
                        "Unsupported tool content type in Bedrock provider."
                    )

        # return the tool result
        tool_result = ConverseToolResult(
            toolUseId=message.tool_call_id,
            status=status,
            content=tool_result_content,
        )
        return [
            ConverseMessage(
                role="user",
                content=[ConverseMessageContent(toolResult=tool_result)],
            )
        ]
    else:
        raise ValueError(f"Unexpected message role {message.role}")


async def converse_contents(
    content: list[Content] | str,
) -> list[ConverseMessageContent]:
    if isinstance(content, str):
        return [ConverseMessageContent(text=content)]
    else:
        result: list[ConverseMessageContent] = []
        for c in content:
            if c.type == "image":
                image_data, image_type = await image_as_data(c.image)
                result.append(
                    ConverseMessageContent(
                        image=ConverseImage(
                            format=converse_image_type(image_type),
                            source=ConverseImageSource(bytes=image_data),
                        )
                    )
                )
            elif c.type == "text":
                result.append(ConverseMessageContent(text=c.text))
            else:
                raise RuntimeError(f"Unsupported content type {c.type}")
        return result


def collapse_consecutive_messages(
    messages: list[ConverseMessage],
) -> list[ConverseMessage]:
    if not messages:
        return []

    collapsed_messages = [messages[0]]

    for message in messages[1:]:
        last_message = collapsed_messages[-1]
        if message.role == last_message.role:
            last_content = last_message.content[-1]
            if last_content.toolResult is not None:
                # Special case tool results since conversation blocks and tool result
                # blocks cannot be provided in the same turn. If the last block was a
                # tool result, we'll need to merge the subsequent blocks into the content
                # itself
                for c in message.content:
                    if (
                        c.text is not None
                        or c.image is not None
                        or c.document is not None
                    ):
                        last_content.toolResult.content.append(
                            ConverseToolResultContent(
                                text=c.text, image=c.image, document=c.document
                            )
                        )
                    else:
                        last_message.content.extend(message.content)
            else:
                last_message.content.extend(message.content)
        else:
            collapsed_messages.append(message)

    return collapsed_messages


def converse_image_type(type: str) -> ConverseImageFormat:
    match type:
        case "image/png":
            return "png"
        case "image/gif":
            return "gif"
        case "image/png":
            return "png"
        case "image/webp":
            return "webp"
        case "image/jpeg":
            return "jpeg"
        case _:
            raise ValueError(
                f"Image mime type {type} is not supported for Bedrock Converse models."
            )


def converse_tools(tools: list[ToolInfo]) -> list[ConverseTool] | None:
    if len(tools) == 0:
        return None

    result = []
    for tool in tools:
        tool_spec = ConverseToolSpec(
            name=tool.name,
            description=tool.description,
            inputSchema={
                "json": tool.parameters.model_dump(
                    exclude_none=True, exclude={"additionalProperties"}
                )
            },
        )
        result.append(ConverseTool(toolSpec=tool_spec))
    return result


def converse_tool_choice(
    tool_choice: ToolChoice,
) -> ConverseToolChoice | None:
    match tool_choice:
        case "auto":
            return ConverseToolChoice(auto={})
        case "any":
            return ConverseToolChoice(any={})
        case "none":
            return ConverseToolChoice(auto={})
        case ToolFunction(name=name):
            return ConverseToolChoice(tool={"name": name})
        case _:
            raise ValueError(
                f"Tool choice {tool_choice} is not supported for Bedrock Converse models."
            )


def replace_bytes_with_placeholder(data: Any, placeholder: Any = "<bytes>") -> Any:
    if isinstance(data, bytes):
        return placeholder
    elif isinstance(data, dict):
        return {
            k: replace_bytes_with_placeholder(v, placeholder) for k, v in data.items()
        }
    elif isinstance(data, list):
        return [replace_bytes_with_placeholder(item, placeholder) for item in data]
    elif isinstance(data, tuple):
        return tuple(replace_bytes_with_placeholder(item, placeholder) for item in data)
    return data
