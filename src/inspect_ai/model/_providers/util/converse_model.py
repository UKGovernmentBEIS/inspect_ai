from typing import Any, Literal, Union

from pydantic import BaseModel, Field

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
