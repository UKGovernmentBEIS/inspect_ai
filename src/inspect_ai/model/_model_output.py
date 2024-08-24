import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

from inspect_ai._util.json import jsonable_python
from inspect_ai.tool._tool_call import ToolCall

from ._chat_message import ChatMessageAssistant


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0)
    """Total input tokens used."""

    output_tokens: int = Field(default=0)
    """Total output tokens used."""

    total_tokens: int = Field(default=0)
    """Total tokens used."""

    input_tokens_cache_write: int | None = Field(default=None)
    """Number of tokens written to the cache."""

    input_tokens_cache_read: int | None = Field(default=None)
    """Number of tokens retrieved from the cache."""


StopReason = Literal["stop", "length", "tool_calls", "content_filter", "unknown"]
"""Reason that the model stopped generating."""


class TopLogprob(BaseModel):
    """List of the most likely tokens and their log probability, at this token position."""

    token: str
    """The top-kth token represented as a string."""

    logprob: float
    """The log probability value of the model for the top-kth token."""

    bytes: list[int] | None = Field(default=None)
    """The top-kth token represented as a byte array (a list of integers)."""


class Logprob(BaseModel):
    """Log probability for a token."""

    token: str
    """The predicted token represented as a string."""

    logprob: float
    """The log probability value of the model for the predicted token."""

    bytes: list[int] | None = Field(default=None)
    """The predicted token represented as a byte array (a list of integers)."""

    top_logprobs: list[TopLogprob] | None = Field(default=None)
    """If the `top_logprobs` argument is greater than 0, this will contain an ordered list of the top K most likely tokens and their log probabilities."""


class Logprobs(BaseModel):
    """Log probability information for a completion choice."""

    content: list[Logprob]
    """a (num_generated_tokens,) length list containing the individual log probabilities for each generated token."""


class ChatCompletionChoice(BaseModel):
    message: ChatMessageAssistant
    """Assistant message."""

    stop_reason: StopReason = Field(default="unknown")
    """Reason that the model stopped generating."""

    logprobs: Logprobs | None = Field(default=None)
    """Logprobs."""


class ModelOutput(BaseModel):
    model: str = Field(default="")
    """Model used for generation."""

    choices: list[ChatCompletionChoice] = Field(default=[])
    """Completion choices."""

    usage: ModelUsage | None = Field(default=None)
    """Model token usage"""

    error: str | None = Field(default=None)
    """Error message in the case of content moderation refusals."""

    @property
    def message(self) -> ChatMessageAssistant:
        """First message choice."""
        return self.choices[0].message

    @property
    def completion(self) -> str:
        """Text of first message choice text."""
        if len(self.choices) > 0:
            return self.choices[0].message.text
        else:
            return ""

    @completion.setter
    def completion(self, completion: str) -> None:
        """Set the text of the first message choice.

        Args:
          completion (str): Text for first message.
        """
        if len(self.choices) > 0:
            self.choices[0].message.text = completion
        else:
            self.choices.append(
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content=completion), stop_reason="stop"
                )
            )

    @staticmethod
    def from_content(
        model: str,
        content: str,
        stop_reason: StopReason = "stop",
        error: str | None = None,
    ) -> "ModelOutput":
        """Convenient method to create ModelOutput from simple text content."""
        return ModelOutput(
            model=model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content=content, source="generate"),
                    stop_reason=stop_reason,
                )
            ],
            error=error,
        )

    @staticmethod
    def for_tool_call(
        model: str, tool_name: str, tool_arguments: dict[str, str]
    ) -> "ModelOutput":
        """
        Returns a ModelOutput for requesting a tool call.

        Args:
            model: model name
            tool_name: The name of the tool.
            tool_arguments: The arguments passed to the tool.

        Returns:
            A ModelOutput corresponding to the tool call
        """
        return ModelOutput(
            model=model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=f"tool call for tool {tool_name}",
                        source="generate",
                        tool_calls=[
                            ToolCall(
                                id=f"for_tool_call_{uuid.uuid4()}",
                                function=tool_name,
                                arguments=tool_arguments,
                                type="function",
                            )
                        ],
                    ),
                    stop_reason="tool_calls",
                )
            ],
        )


class ModelCall(BaseModel):
    """Model call (raw request/response data)."""

    request: dict[str, JsonValue]
    """Raw data posted to model."""

    response: dict[str, JsonValue]
    """Raw response data from model."""

    @staticmethod
    def create(request: Any, response: Any) -> "ModelCall":
        """Create a ModelCall object.

        Create a ModelCall from arbitrary request and response objects (they might
        be dataclasses, Pydandic objects, dicts, etc.). Converts all values to
        JSON serialiable (exluding those that can't be)

        Args:
           request (Any): Request object (dict, dataclass, BaseModel, etc.)
           response (Any): Response object (dict, dataclass, BaseModel, etc.)
        """
        return ModelCall(
            request=jsonable_python(request), response=jsonable_python(response)
        )
