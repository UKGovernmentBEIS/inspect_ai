import uuid
from typing import Any, Literal, Self, Type

from pydantic import BaseModel, Field, JsonValue, model_validator

from inspect_ai._util.content import Content
from inspect_ai.tool._tool_call import ToolCall

from ._chat_message import ChatMessageAssistant


class ModelUsage(BaseModel):
    """Token usage for completion."""

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

    reasoning_tokens: int | None = Field(default=None)
    """Number of tokens used for reasoning."""

    def __add__(self, other: Self) -> Self:
        def optional_sum(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return type(self)(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            input_tokens_cache_write=optional_sum(
                self.input_tokens_cache_write, other.input_tokens_cache_write
            ),
            input_tokens_cache_read=optional_sum(
                self.input_tokens_cache_read, other.input_tokens_cache_read
            ),
            reasoning_tokens=optional_sum(
                self.reasoning_tokens, other.reasoning_tokens
            ),
        )


class IdealizedModelUsage(ModelUsage):
    """
    Theoretical model usage, tracked as if a provider perfectly cached all inputs.

    IdealizedModelUsage counts reads from the local inspect cache as contributing to
    the tracked usage.

    NOTE only a subset of ModelUsage fields are used in this class:
    * input_tokens_cache_write stores the total number of unique tokens
    * input_tokens stores the total input tokens used
    * output tokens stores the total output tokens produced

    Unique tokens are defined as unique suffixes when looking across all prior inputs
    sent to a given model. When each prompt is sent to the model it will be matched
    against the longest previous prefix sent to that model, and only the new text since
    the match (or all text in the case of no match) will be counted as unique tokens.

    Partial matches will not be counted, only entire prefixes (e.g., a turn based agent);
    we assume caching happens at a prompt granularity. This assumption allows us to
    use provider-reported token usage stats to understand the number of tokens (as defined
    by any provider) in the suffix.

    For example, consider the following sequence of prompts (one prompt per line). Underlined
    text is considered unique:

        part1
        _____

        part1part2
             _____

        part1part3
             _____

        part1part2part4
                  _____

        part5
        _____
    """

    pass


StopReason = Literal[
    "stop",
    "max_tokens",
    "model_length",
    "tool_calls",
    "content_filter",
    "unknown",
]
"""Reason that the model stopped or failed to generate."""


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
    """Choice generated for completion."""

    message: ChatMessageAssistant
    """Assistant message."""

    stop_reason: StopReason = Field(default="unknown")
    """Reason that the model stopped generating."""

    logprobs: Logprobs | None = Field(default=None)
    """Logprobs."""

    @model_validator(mode="before")
    @classmethod
    def migrate_stop_reason(
        cls: Type["ChatCompletionChoice"], values: dict[str, Any]
    ) -> dict[str, Any]:
        if "stop_reason" in values:
            stop_reason = values["stop_reason"]
            if stop_reason == "length":
                values["stop_reason"] = "max_tokens"

        return values


class ModelOutput(BaseModel):
    """Output from model generation."""

    model: str = Field(default_factory=str)
    """Model used for generation."""

    choices: list[ChatCompletionChoice] = Field(default=[])
    """Completion choices."""

    usage: ModelUsage | None = Field(default=None)
    """Model token usage"""

    time: float | None = Field(default=None)
    """Time elapsed (in seconds) for call to generate."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional metadata associated with model output."""

    error: str | None = Field(default=None)
    """Error message in the case of content moderation refusals."""

    @property
    def empty(self) -> bool:
        return len(self.choices) == 0

    @property
    def stop_reason(self) -> StopReason:
        """First message stop reason."""
        return self.choices[0].stop_reason

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
                    message=ChatMessageAssistant(content=completion, model=self.model),
                    stop_reason="stop",
                )
            )

    @staticmethod
    def from_content(
        model: str,
        content: str | list[Content],
        stop_reason: StopReason = "stop",
        error: str | None = None,
    ) -> "ModelOutput":
        """Create ModelOutput from simple text content.

        Args:
           model: Model name.
           content: Text content from generation.
           stop_reason: Stop reason for generation.
           error: Error message.
        """
        return ModelOutput(
            model=model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=content, model=model, source="generate"
                    ),
                    stop_reason=stop_reason,
                )
            ],
            error=error,
        )

    @staticmethod
    def for_tool_call(
        model: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
        internal: JsonValue | None = None,
        tool_call_id: str | None = None,
        content: str | None = None,
    ) -> "ModelOutput":
        """
        Returns a ModelOutput for requesting a tool call.

        Args:
            model: model name
            tool_name: The name of the tool.
            internal: The model's internal info for the tool (if any).
            tool_arguments: The arguments passed to the tool.
            tool_call_id: Optional ID for the tool call. Defaults to a random UUID.
            content: Optional content to include in the message. Defaults to "tool call for tool {tool_name}".

        Returns:
            A ModelOutput corresponding to the tool call
        """
        if content is None:
            content = f"tool call for tool {tool_name}"

        if tool_call_id is None:
            tool_call_id = f"for_tool_call_{uuid.uuid4()}"

        return ModelOutput(
            model=model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=content,
                        model=model,
                        source="generate",
                        tool_calls=[
                            ToolCall(
                                id=tool_call_id,
                                function=tool_name,
                                internal=internal,
                                arguments=tool_arguments,
                            )
                        ],
                    ),
                    stop_reason="tool_calls",
                )
            ],
        )


def as_stop_reason(reason: str | None) -> StopReason:
    """Encode common reason strings into standard StopReason."""
    match reason:
        case "stop" | "eos":
            return "stop"
        case "length":
            return "max_tokens"
        case "tool_calls" | "function_call":
            return "tool_calls"
        case "content_filter" | "model_length" | "max_tokens":
            return reason
        case _:
            return "unknown"
