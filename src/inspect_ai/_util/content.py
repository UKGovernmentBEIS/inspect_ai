from typing import Literal, Union

from pydantic import BaseModel, Field


class ContentText(BaseModel):
    type: Literal["text"] = Field(default="text")
    """Type."""

    text: str
    """Text content."""


class ContentImage(BaseModel):
    type: Literal["image"] = Field(default="image")
    """Type."""

    image: str
    """Either a URL of the image or the base64 encoded image data."""

    detail: Literal["auto", "low", "high"] = Field(default="auto")
    """Specifies the detail level of the image.

    Currently only supported for OpenAI. Learn more in the    [Vision guide](https://platform.openai.com/docs/guides/vision/low-or-high-fidelity-image-understanding).
    """


Content = Union[ContentText, ContentImage]
"""Content sent to or received from a model."""
