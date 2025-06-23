from typing import Literal, Sequence, Union

from pydantic import BaseModel, Field, JsonValue

from inspect_ai._util.citation import Citation


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
    """Audio file path or base64 encoded data URL."""

    format: Literal["mp4", "mpeg", "mov"]
    """Format of video data ('mp4', 'mpeg', or 'mov')"""


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
]
"""Content sent to or received from a model."""
