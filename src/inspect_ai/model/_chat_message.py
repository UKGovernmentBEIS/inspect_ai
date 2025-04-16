from logging import getLogger
from typing import Any, Literal, Type, Union

from pydantic import BaseModel, Field, JsonValue, model_validator
from shortuuid import uuid

from inspect_ai._util.constants import DESERIALIZING
from inspect_ai._util.content import Content, ContentReasoning, ContentText
from inspect_ai.tool import ToolCall
from inspect_ai.tool._tool_call import ToolCallError

from ._reasoning import parse_content_with_reasoning

logger = getLogger(__name__)


class ChatMessageBase(BaseModel):
    """Base class for chat messages."""

    id: str | None = Field(default=None)
    """Unique identifer for message."""

    content: str | list[Content]
    """Content (simple string or list of content objects)"""

    source: Literal["input", "generate"] | None = Field(default=None)
    """Source of message."""

    internal: JsonValue | None = Field(default=None)
    """Model provider specific payload - typically used to aid transformation back to model types."""

    def model_post_init(self, __context: Any) -> None:
        # check if deserializing
        is_deserializing = isinstance(__context, dict) and __context.get(
            DESERIALIZING, False
        )

        # Generate ID if needed and not deserializing
        if self.id is None and not is_deserializing:
            self.id = uuid()

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
            all_other = [content for content in self.content if content.type != "text"]
            self.content = all_other + [ContentText(text=text)]


class ChatMessageSystem(ChatMessageBase):
    """System chat message."""

    role: Literal["system"] = Field(default="system")
    """Conversation role."""


class ChatMessageUser(ChatMessageBase):
    """User chat message."""

    role: Literal["user"] = Field(default="user")
    """Conversation role."""

    tool_call_id: list[str] | None = Field(default=None)
    """ID(s) of tool call(s) this message has the content payload for."""


class ChatMessageAssistant(ChatMessageBase):
    """Assistant chat message."""

    role: Literal["assistant"] = Field(default="assistant")
    """Conversation role."""

    tool_calls: list[ToolCall] | None = Field(default=None)
    """Tool calls made by the model."""

    model: str | None = Field(default=None)
    """Model used to generate assistant message."""

    # Some OpenAI compatible REST endpoints include reasoning as a field alongside
    # content, however since this field doesn't exist in the OpenAI interface,
    # hosting providers (so far we've seen this with Together and Groq) may
    # include the reasoning in a <think></think> tag before the main response.
    # We expect this pattern to be repeated elsewhere, so include this hook to
    # automatically extract the reasoning content when the response is prefaced
    # with a <think> block. If this ends up being an overeach we can fall back
    # to each provider manually parsing out <think> using a helper function.
    # The implementation isn't important here, the critical thing to establish
    # is that Inspect makes reasoning content available separately.
    @model_validator(mode="before")
    @classmethod
    def extract_reasoning(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # cleave apart <think> blocks
            content = data.get("content", None)
            if isinstance(content, str):
                parsed = parse_content_with_reasoning(content)
                if parsed:
                    data["content"] = [
                        ContentReasoning(reasoning=parsed.reasoning),
                        ContentText(text=parsed.content),
                    ]
            # migrate messages that has explicit 'reasoning' field
            # (which was our original representation of reasoning)
            reasoning = data.get("reasoning", None)
            if isinstance(reasoning, str):
                # ensure that content is a list
                content = data.get("content", None)
                if content is None:
                    data["content"] = []
                elif isinstance(content, str):
                    data["content"] = [ContentText(text=content)]
                elif not isinstance(content, list):
                    data["content"] = []
                data["content"].insert(0, ContentReasoning(reasoning=reasoning))

                del data["reasoning"]
        return data


class ChatMessageTool(ChatMessageBase):
    """Tool chat message."""

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
