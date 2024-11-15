import abc
import base64
import json
from typing import Any, Literal, cast

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
from inspect_ai.model._providers.util.converse_model import (
    ClientConverseRequest,
    Image,
    ImageFormat,
    ImageSource,
    InferenceConfig,
    Message,
    MessageContent,
    Response,
    StopReason,
    SystemContent,
    Tool,
    ToolConfig,
    ToolResult,
    ToolResultContent,
    ToolSpec,
    ToolUse,
)
from inspect_ai.model._providers.util.converse_model import (
    ToolChoice as ConverseToolChoice,
)
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
    ChatAPIHandler,
    ChatAPIMessage,
    as_stop_reason,
    chat_api_input,
    model_base_url,
)


class BedrockAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            # api_key_vars=[ANTHROPIC_API_KEY],
            config=config,
        )

        # import aioboto3 on demand
        try:
            import aioboto3

            verify_required_version("Bedrock API", "aioboto3", "13.0.0")

            # properties for the client
            self.model_name = model_name
            self.base_url = model_base_url(base_url, "BEDROCK_BASE_URL")
            self.config = config

            # Create a shared session to be used by the handler
            self.session = aioboto3.Session()

        except ImportError:
            raise pip_dependency_error("Bedrock API", ["aioboto3"])

    @override
    def connection_key(self) -> str:
        return self.model_name

    @override
    def max_tokens(self) -> int | None:
        if "llama3" in self.model_name or "claude3" in self.model_name:
            return 4096

        elif "mistral-large" in self.model_name:
            return 8192

        # Not sure what do to about other model types... (there aren't currently any others)
        else:
            return DEFAULT_MAX_TOKENS

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        from botocore.exceptions import ClientError

        if isinstance(ex, ClientError):
            if ex.response["Error"]["Code"] == "ThrottlingException":
                return True

        return super().is_rate_limit(ex)

    @override
    def collapse_user_messages(self) -> bool:
        """Collapse consecutive user messages into a single message."""
        return True

    @override
    def collapse_assistant_messages(self) -> bool:
        """Collapse consecutive assistant messages into a single message."""
        return True

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        from botocore.config import Config

        async with self.session.client(
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
        ) as client:
            # TODO test with various models
            # TODO cleanup
            # TODO Talk to JJ about max_tokens (when passing a value larger than their max of 4096, they throw)

            # Split up system messages and input messages
            system_messages: list[ChatMessage] = []
            non_system_messages: list[ChatMessage] = []
            for message in input:
                if message.role == "system":
                    system_messages.append(message)
                else:
                    non_system_messages.append(message)

            # input messages
            messages: list[Message] = await as_converse_chat_messages(
                non_system_messages
            )

            # system messages
            system: list[SystemContent] = as_converse_system_messages(system_messages)

            # tools
            resolved_tools = converse_tools(tools)
            tool_config = None
            if resolved_tools is not None:
                choice = converse_tool_choice(tool_choice)
                tool_config = ToolConfig(tools=resolved_tools, toolChoice=choice)

            request = ClientConverseRequest(
                modelId=self.model_name,
                messages=messages,
                system=system,
                inferenceConfig=InferenceConfig(
                    maxTokens=config.max_tokens,
                    temperature=config.temperature,
                    topP=config.top_p,
                    stopSequences=config.stop_seqs,
                ),
                additionalModelRequestFields={"top_k": config.top_k},
                toolConfig=tool_config,
            )

            # make the request
            response = await client.converse(**request.model_dump(exclude_none=True))
            converse_response = Response(**response)

        # process the response
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


def model_output_from_response(
    model: str, response: Response, tools: list[ToolInfo]
) -> ModelOutput:
    # extract content and tool calls
    content: list[Content] = []
    tool_calls: list[ToolCall] = []

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
    reason: StopReason,
) -> Literal["stop", "tool_calls", "max_tokens", "unknown"]:
    match reason:
        case "end_turn" | "stop_sequence":
            return "stop"
        case "tool_use":
            return "tool_calls"
        case "max_tokens":
            return reason
        case _:
            return "unknown"


def as_converse_system_messages(messages: list[ChatMessage]) -> list[SystemContent]:
    return [SystemContent(text=message.text) for message in messages]


async def as_converse_chat_messages(
    messages: list[ChatMessage],
) -> list[Message]:
    result: list[Message] = []
    for message in messages:
        converse_message = await converse_chat_message(message)
        if converse_message is not None:
            result.extend(converse_message)
    return result


async def converse_chat_message(
    message: ChatMessage,
) -> list[Message] | None:
    if isinstance(message, ChatMessageSystem):
        raise ValueError("System messages should be processed separately for Converse")
    if isinstance(message, ChatMessageUser):
        content = await converse_contents(message.content)
        if len(content) == 0:
            return None
        return [Message(role="user", content=content)]
    elif isinstance(message, ChatMessageAssistant):
        if message.tool_calls:
            results: list[Message] = []
            for tool_call in message.tool_calls:
                tool_use = ToolUse(
                    toolUseId=tool_call.id,
                    name=tool_call.function,
                    input=tool_call.arguments,
                )
                m = Message(
                    role="assistant", content=[MessageContent(toolUse=tool_use)]
                )
                results.append(m)
            return results
        else:
            content = await converse_contents(message.content)
            if len(content) == 0:
                return None
            return [Message(role="assistant", content=content)]
    elif isinstance(message, ChatMessageTool):
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

        tool_result_content: list[ToolResultContent] = []
        if isinstance(message.content, str):
            tool_result_content.append(ToolResultContent(text=message.content))
        else:
            for c in message.content:
                if c.type == "text":
                    tool_result_content.append(ToolResultContent(text=c.text))
                elif c.type == "image":
                    image_data, image_type = await image_as_data(c.image)
                    tool_result_content.append(
                        ToolResultContent(
                            image=Image(
                                format=converse_image_type(image_type),
                                source=ImageSource(bytes=image_data),
                            )
                        )
                    )
                else:
                    raise ValueError(
                        "Unsupported tool content type in Bedrock provider."
                    )

        tool_result = ToolResult(
            toolUseId=message.tool_call_id,
            status=status,
            content=tool_result_content,
        )
        return [
            Message(
                role="user",
                content=[MessageContent(toolResult=tool_result)],
            )
        ]
    else:
        raise ValueError(f"Unexpected message role {message.role}")


async def converse_contents(content: list[Content] | str) -> list[MessageContent]:
    if isinstance(content, str):
        return [MessageContent(text=content)]
    else:
        result: list[MessageContent] = []
        for c in content:
            if c.type == "image":
                image_data, image_type = await image_as_data(c.image)
                result.append(
                    MessageContent(
                        image=Image(
                            format=converse_image_type(image_type),
                            source=ImageSource(bytes=image_data),
                        )
                    )
                )
            elif c.type == "text":
                result.append(MessageContent(text=c.text))
            else:
                raise RuntimeError(f"Unsupported content type {c.type}")
        return result


def converse_image_type(type: str) -> ImageFormat:
    match type:
        case "image/png":
            return "png"
        case "image/gif":
            return "gif"
        case "image/png":
            return "png"
        case "image/webp":
            return "webp"
        case _:
            raise ValueError(
                f"Image mime type {type} is not supported for Bedrock Converse models."
            )


def converse_tools(tools: list[ToolInfo]) -> list[Tool] | None:
    if len(tools) == 0:
        return None

    result = []
    for tool in tools:
        tool_spec = ToolSpec(
            name=tool.name,
            description=tool.description,
            inputSchema={"json": tool.parameters.model_dump(exclude_none=True)},
        )
        result.append(Tool(toolSpec=tool_spec))
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
