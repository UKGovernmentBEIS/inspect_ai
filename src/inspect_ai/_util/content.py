import mimetypes
from pathlib import Path
from typing import Any, Literal, Sequence, Union

from pydantic import BaseModel, Field, JsonValue, model_validator

from inspect_ai._util.citation import Citation
from inspect_ai._util.url import data_uri_mime_type


class ContentBase(BaseModel):
    internal: JsonValue | None = Field(default=None)
    """Model provider specific payload - typically used to aid transformation back to model types."""


class ContentText(ContentBase):
    """Text content."""

    type: Literal["text"] = Field(default="text")
    """Type."""

    text: str
    """Text content."""

    refusal: bool | None = Field(default=None)
    """Was this a refusal message?"""

    citations: Sequence[Citation] | None = Field(default=None)
    """Citations supporting the text block."""


class ContentReasoning(ContentBase):
    """Reasoning content.

    See the specification for [thinking blocks](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking#understanding-thinking-blocks) for Claude models.
    """

    type: Literal["reasoning"] = Field(default="reasoning")
    """Type."""

    reasoning: str
    """Reasoning content."""

    signature: str | None = Field(default=None)
    """Signature for reasoning content (used by some models to ensure that reasoning content is not modified for replay)"""

    redacted: bool = Field(default=False)
    """Indicates that the explicit content of this reasoning block has been redacted."""


class ContentToolUse(ContentBase):
    """Server side tool use."""

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


class ContentImage(ContentBase):
    """Image content."""

    type: Literal["image"] = Field(default="image")
    """Type."""

    image: str
    """Either a URL of the image or the base64 encoded image data."""

    detail: Literal["auto", "low", "high"] = Field(default="auto")
    """Specifies the detail level of the image.

    Currently only supported for OpenAI. Learn more in the    [Vision guide](https://platform.openai.com/docs/guides/vision/low-or-high-fidelity-image-understanding).
    """


class ContentAudio(ContentBase):
    """Audio content."""

    type: Literal["audio"] = Field(default="audio")
    """Type."""

    audio: str
    """Audio file path or base64 encoded data URL."""

    format: Literal["wav", "mp3"]
    """Format of audio data ('mp3' or 'wav')"""


class ContentVideo(ContentBase):
    """Video content."""

    type: Literal["video"] = Field(default="video")
    """Type."""

    video: str
    """Video file path or base64 encoded data URL."""

    format: Literal["mp4", "mpeg", "mov"]
    """Format of video data ('mp4', 'mpeg', or 'mov')"""


class ContentDocument(ContentBase):
    """Document content (e.g. a PDF)."""

    type: Literal["document"] = Field(default="document")
    """Type."""

    document: str
    """Document file path or base64 encoded data URL."""

    filename: str = Field(default_factory=str)
    """Document filename (automatically determined from 'document' if not specified)."""

    mime_type: str = Field(default_factory=str)
    """Document mime type (automatically determined from 'document' if not specified)."""

    @model_validator(mode="before")
    @classmethod
    def set_name_and_mime_type(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Automatically set name and mime_type if not provided."""
        document: str | None = data.get("document")
        filename: str | None = data.get("filename")
        mime_type: str | None = data.get("mime_type")

        if not document:
            # Let Pydantic handle the missing required field
            return data

        if document.startswith("data:"):
            if not mime_type:
                mime_type = data_uri_mime_type(document) or "application/octet-stream"
            if not filename:
                extension = mime_type.split("/")[-1]
                filename = f"document.{extension}"

        else:
            path = Path(document)
            if not filename:
                filename = path.name

            if not mime_type:
                guessed_type, _ = mimetypes.guess_type(str(path))
                mime_type = guessed_type or "application/octet-stream"

        data["filename"] = filename
        data["mime_type"] = mime_type

        return data


class ContentData(ContentBase):
    """Model internal."""

    type: Literal["data"] = Field(default="data")
    """Type."""

    data: dict[str, JsonValue]
    """Model provider specific payload - required for internal content."""


Content = Union[
    ContentText,
    ContentReasoning,
    ContentImage,
    ContentAudio,
    ContentVideo,
    ContentData,
    ContentToolUse,
    ContentDocument,
]
"""Content sent to or received from a model."""
