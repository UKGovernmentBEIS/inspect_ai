from typing import Any, Literal, Union

from pydantic import BaseModel, Field

# Model for Bedrock Converse API (Response)
# generated from: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html#converse

Role = Literal["user", "assistant"]
ImageFormat = Literal["png", "jpeg", "gif", "webp"]
DocumentFormat = Literal[
    "pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"
]
ToolResultStatus = Literal["success", "error"]
StopReason = Literal[
    "end_turn",
    "tool_use",
    "max_tokens",
    "stop_sequence",
    "guardrail_intervened",
    "content_filtered",
]
GuardContentQualifier = Literal["grounding_source", "query", "guard_content"]
FilterType = Literal[
    "INSULTS", "HATE", "SEXUAL", "VIOLENCE", "MISCONDUCT", "PROMPT_ATTACK"
]
FilterConfidence = Literal["NONE", "LOW", "MEDIUM", "HIGH"]
FilterStrength = Literal["NONE", "LOW", "MEDIUM", "HIGH"]


class ImageSource(BaseModel):
    bytes: bytes


class DocumentSource(BaseModel):
    bytes: bytes


class Image(BaseModel):
    format: ImageFormat
    source: ImageSource


class Document(BaseModel):
    format: DocumentFormat
    name: str
    source: DocumentSource


class ToolUse(BaseModel):
    toolUseId: str
    name: str
    input: Union[dict[str, Any], list[Any], int, float, str, bool, None]


class ToolResultContent(BaseModel):
    json_content: Union[dict[str, Any], list[Any], int, float, str, bool, None] = Field(
        default=None, alias="json"
    )
    text: str | None = None
    image: Image | None = None
    document: Document | None = None


class ToolResult(BaseModel):
    toolUseId: str
    content: list[ToolResultContent]
    status: ToolResultStatus


class GuardContentText(BaseModel):
    text: str
    qualifiers: list[GuardContentQualifier]


class GuardContent(BaseModel):
    text: GuardContentText


class MessageContent(BaseModel):
    text: str | None = None
    image: Image | None = None
    document: Document | None = None
    toolUse: ToolUse | None = None
    toolResult: ToolResult | None = None
    guardContent: GuardContent | None = None


class Message(BaseModel):
    role: Role
    content: list[MessageContent]


class Output(BaseModel):
    message: Message


class Usage(BaseModel):
    inputTokens: int
    outputTokens: int
    totalTokens: int


class Metrics(BaseModel):
    latencyMs: int


class TraceGuardrailFilter(BaseModel):
    type: FilterType
    confidence: FilterConfidence
    filterStrength: FilterStrength
    action: str


class AdditionalModelResponseFields(BaseModel):
    value: Union[dict[str, Any], list[Any], int, float, str, bool, None]


class Response(BaseModel):
    output: Output
    stopReason: StopReason
    usage: Usage
    metrics: Metrics
    additionalModelResponseFields: AdditionalModelResponseFields | None = None
    trace: dict[str, Any] | None = None


# Model for Bedrock Converse API (Request)
# generated from: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html#converse
class Source(BaseModel):
    bytes: bytes


class Content(BaseModel):
    text: str | None = None
    image: Image | None = None
    document: Document | None = None
    toolUse: ToolUse | None = None
    toolResult: ToolResult | None = None
    guardContent: GuardContent | None = None


class SystemContent(BaseModel):
    text: str | None = None
    guardContent: GuardContent | None = None


class InferenceConfig(BaseModel):
    maxTokens: int | None = None
    temperature: float | None = None
    topP: float | None = None
    stopSequences: list[str] | None = None


class ToolSpec(BaseModel):
    name: str
    description: str | None = None
    inputSchema: (
        Union[dict[str, Any], list[Any], int, float, str, bool, None] | None
    ) = None


class Tool(BaseModel):
    toolSpec: ToolSpec


class ToolChoice(BaseModel):
    auto: dict[str, Any] | None = None
    any: dict[str, Any] | None = None
    tool: dict[str, str] | None = None


class ToolConfig(BaseModel):
    tools: list[Tool] | None = None
    toolChoice: ToolChoice | None = None


class GuardrailConfig(BaseModel):
    guardrailIdentifier: str | None = None
    guardrailVersion: str | None = None
    trace: str | None = None


class PromptVariable(BaseModel):
    text: str


class ClientConverseRequest(BaseModel):
    modelId: str
    messages: list[Message]
    system: list[SystemContent] | None = None
    inferenceConfig: InferenceConfig | None = None
    toolConfig: ToolConfig | None = None
    guardrailConfig: GuardrailConfig | None = None
    additionalModelRequestFields: (
        Union[dict[str, Any], list[Any], int, float, str, bool, None] | None
    ) = None
    additionalModelResponseFieldPaths: list[str] = []
