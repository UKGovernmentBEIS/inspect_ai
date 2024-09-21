from logging import getLogger
from typing import Any, Literal, Type, Union

from pydantic import BaseModel, Field, model_validator

from inspect_ai._util.content import Content, ContentText
from inspect_ai.tool import ToolCall
from inspect_ai.tool._tool_call import ToolCallError

logger = getLogger(__name__)


class ChatMessageBase(BaseModel):
    content: str | list[Content]
    """Content (simple string or list of string|image content)"""

    source: Literal["input", "generate"] | None = Field(default=None)
    """Source of message."""

    @property
    def text(self) -> str:
        """Get the text content of this message.

        ChatMessage content is very general and can contain either
        a simple text value or a list of content parts (each of which
        can either be text or an image). Solvers (e.g. for prompt
        engineering) often need to interact with chat messages with
        the assumption that they are a simple string. The text
        property returns either the plain str content, or if the
        content is a list of text and images, the text items
        concatenated together (separated by newline)

        Returns: Text content of `ChatMessage` If this message does
          not have text content then "" is returned.
        """
        if isinstance(self.content, str):
            return self.content
        else:
            all_text = [
                content.text for content in self.content if content.type == "text"
            ]
            return "\n".join(all_text)

    @text.setter
    def text(self, text: str) -> None:
        """Set the primary text content for this message.

        ChatMessage content is very general and can contain either
        a simple text value or a list of content parts (each of which
        can either be text or an image). Solvers (e.g. for prompt
        engineering) often need to interact with chat messages with
        the assumption that they are a simple string. The text property
        sets text either to content directly (if it is a `str`) or to
        the first text content item in the message (inserting one at
        the beginning if necessary). If there are multiple text content
        items in the message then after the set there will be only
        one remaining (image content will remain).
        """
        if isinstance(self.content, str):
            self.content = text
        else:
            all_images = [
                content for content in self.content if content.type == "image"
            ]
            self.content = [ContentText(text=text)] + all_images


class ChatMessageSystem(ChatMessageBase):
    role: Literal["system"] = Field(default="system")
    """Conversation role."""


class ChatMessageUser(ChatMessageBase):
    role: Literal["user"] = Field(default="user")
    """Conversation role."""


class ChatMessageAssistant(ChatMessageBase):
    role: Literal["assistant"] = Field(default="assistant")
    """Conversation role."""

    tool_calls: list[ToolCall] | None = Field(default=None)
    """Tool calls made by the model."""


class ChatMessageTool(ChatMessageBase):
    role: Literal["tool"] = Field(default="tool")
    """Conversation role."""

    tool_call_id: str | None = Field(default=None)
    """ID of tool call."""

    function: str | None = Field(default=None)
    """Name of function called."""

    error: ToolCallError | None = Field(default=None)
    """Error which occurred during tool call."""

    @property
    def tool_error(self) -> str | None:
        """Tool error (deprecated)."""
        from inspect_ai._util.logger import warn_once

        warn_once(
            logger,
            "The 'tool_error' field is deprecated. Access error information via 'error' instead.",
        )
        if self.error:
            return self.error.message
        else:
            return None

    @model_validator(mode="before")
    @classmethod
    def convert_tool_error_to_error(
        cls: Type["ChatMessageTool"], values: dict[str, Any]
    ) -> dict[str, Any]:
        tool_error = values.get("tool_error", None)
        if tool_error:
            values["error"] = ToolCallError("unknown", tool_error)
        return values


ChatMessage = Union[
    ChatMessageSystem, ChatMessageUser, ChatMessageAssistant, ChatMessageTool
]
"""Message in a chat conversation"""
