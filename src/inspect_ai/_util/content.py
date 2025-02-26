from typing import Literal, Union

from pydantic import BaseModel, Field


class ContentText(BaseModel):
    """Text content."""

    type: Literal["text"] = Field(default="text")
    """Type."""

    text: str
    """Text content."""


class ContentReasoning(BaseModel):
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


class ContentImage(BaseModel):
    """Image content."""

    type: Literal["image"] = Field(default="image")
    """Type."""

    image: str
    """Either a URL of the image or the base64 encoded image data."""

    detail: Literal["auto", "low", "high"] = Field(default="auto")
    """Specifies the detail level of the image.

    Currently only supported for OpenAI. Learn more in the    [Vision guide](https://platform.openai.com/docs/guides/vision/low-or-high-fidelity-image-understanding).
    """


class ContentAudio(BaseModel):
    """Audio content."""

    type: Literal["audio"] = Field(default="audio")
    """Type."""

    audio: str
    """Audio file path or base64 encoded data URL."""

    format: Literal["wav", "mp3"]
    """Format of audio data ('mp3' or 'wav')"""


class ContentVideo(BaseModel):
    """Video content."""

    type: Literal["video"] = Field(default="video")
    """Type."""

    video: str
    """Audio file path or base64 encoded data URL."""

    format: Literal["mp4", "mpeg", "mov"]
    """Format of video data ('mp4', 'mpeg', or 'mov')"""


Content = Union[ContentText, ContentReasoning, ContentImage, ContentAudio, ContentVideo]
"""Content sent to or received from a model."""
