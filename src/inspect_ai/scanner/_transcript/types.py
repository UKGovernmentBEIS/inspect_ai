from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Iterator, Literal, Protocol, TypeAlias, Union

from pydantic import BaseModel, Field, JsonValue
from shortuuid import uuid

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage

from .metadata import Condition

MessageType = Literal["system", "user", "assistant", "tool"]
EventType = Literal[
    "sample_init",
    "sample_limit",
    "sandbox",
    "state",
    "store",
    "model",
    "tool",
    "approval",
    "input",
    "score",
    "error",
    "logger",
    "info",
    "span_begin",
    "span_end",
]

MessageFilter: TypeAlias = Literal["all"] | list[MessageType] | None
EventFilter: TypeAlias = Literal["all"] | list[EventType] | None


class TextItem(BaseModel):
    """Text item."""

    type: Literal["text"] = Field(default="text")
    """Type."""

    text: str
    """Text content."""


class ReasoningItem(BaseModel):
    """Reasoning item."""

    type: Literal["reasoning"] = Field(default="reasoning")
    """Type."""

    reasoning: str
    """Reasoning content."""

    redacted: bool = Field(default=False)
    """Indicates that the explicit content of this reasoning block has been redacted."""


class ToolUseItem(BaseModel):
    """Tool use item."""

    type: Literal["tool_use"] = Field(default="tool_use")
    """Type."""

    tool_type: Literal["web_search", "mcp_call"]
    """The type of the tool call."""

    id: str
    """The unique ID of the tool call."""

    name: str
    """Name of the tool."""

    context: str | None = Field(default=None)
    """Tool context (e.g. MCP Server)"""

    arguments: str
    """Arguments passed to the tool."""

    result: str
    """Result from the tool call."""

    error: str | None = Field(default=None)
    """The error from the tool call (if any)."""


class ImageItem(BaseModel):
    type: Literal["image"] = Field(default="image")
    """Type."""

    image: str
    """Either a URL of the image or the base64 encoded image data."""


class BaseMessage(BaseModel):
    id: str = Field(default_factory=uuid)
    """Unique identifer for message."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional message metadata."""


class UserMessage(BaseMessage):
    role: Literal["user"] = Field(default="user")
    """Conversation role."""

    content: list[Annotated[Union[TextItem, ImageItem], Field(discriminator="type")]]
    """Message content."""


class SystemMessage(BaseMessage):
    role: Literal["system"] = Field(default="system")
    """Conversation role."""

    content: list[TextItem]
    """Message content."""


class ToolMessage(BaseMessage):
    role: Literal["tool"] = Field(default="tool")
    """Conversation role."""

    tool_call_id: str | None = Field(default=None)
    """ID of tool call."""

    function: str | None = Field(default=None)
    """Name of function called."""

    content: list[Annotated[Union[TextItem, ImageItem], Field(discriminator="type")]]
    """Tool call result."""

    error: str | None = Field(default=None)
    """Error which occurred during tool call."""


class ToolCallInfo(BaseModel):
    id: str
    """Unique identifier for call."""

    function: str
    """Function called."""

    arguments: dict[str, Any]
    """Arguments to function."""


class AssistantMessage(BaseMessage):
    role: Literal["assistant"] = Field(default="assistant")
    """Conversation role."""

    content: list[
        Annotated[
            Union[TextItem, ReasoningItem, ToolUseItem, ImageItem],
            Field(discriminator="type"),
        ]
    ]
    """Message content."""

    tool_calls: list[ToolCallInfo] | None = Field(default=None)
    """Tool calls made by the model."""

    model: str | None = Field(default=None)
    """Model used to generate assistant message."""


class BaseEvent(BaseModel):
    id: str | None = Field(default=None)
    """Unique identifer for event."""

    span_id: str | None = Field(default=None)
    """Span the event occurred within."""

    timestamp: datetime = Field(default_factory=datetime.now)
    """Clock time at which event occurred."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional event metadata."""


class ModelCallEvent(BaseEvent):
    pass


class ToolCallEvent(BaseEvent):
    pass


class SpanBeginEvent(BaseEvent):
    pass


@dataclass
class TranscriptContent:
    messages: MessageFilter = field(default=None)
    events: EventFilter = field(default=None)


class TranscriptInfo(BaseModel):
    """Transcript identifier, location, and metadata."""

    id: str
    """Globally unique id for transcript (e.g. sample uuid)."""

    source_id: str
    """Globally unique ID for transcript source (e.g. eval_id)."""

    source_uri: str
    """URI for source data (e.g. log file path)"""

    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    """e.g. eval config (model, scores, task params, etc.)."""


class Transcript(TranscriptInfo):
    """Transcript info and transcript content (messages and events)."""

    messages: list[ChatMessage] = Field(default_factory=list)
    """Main message thread."""

    events: list[Event] = Field(default_factory=list)
    """Events from transcript."""


class TranscriptDB(Protocol):
    async def connect(self) -> None: ...
    async def count(
        self,
        where: list[Condition],
        limit: int | None = None,
    ) -> int: ...
    async def query(
        self,
        where: list[Condition],
        limit: int | None = None,
        shuffle: bool | int = False,
    ) -> Iterator[TranscriptInfo]: ...
    async def read(
        self, t: TranscriptInfo, content: TranscriptContent
    ) -> Transcript: ...
    async def disconnect(self) -> None: ...
