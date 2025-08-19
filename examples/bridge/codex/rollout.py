"""Pydantic v2 models corresponding to the Rust serde types in models.rs (https://github.com/openai/codex/blob/1930ee720ac4c8873d68c1b046de055755369332/codex-rs/core/src/models.rs) and in rollout log files (https://github.com/openai/codex/blob/1930ee720ac4c8873d68c1b046de055755369332/codex-rs/core/src/rollout.rs)"""

import json
from logging import getLogger
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field, JsonValue, TypeAdapter

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ContentImage,
    ContentText,
)
from inspect_ai.tool import ToolCall

logger = getLogger(__file__)


class LocalShellStatus(BaseModel):
    value: Literal["completed", "in_progress", "incomplete"]


class ContentItemInputText(BaseModel):
    type: Literal["input_text"] = Field(default="input_text")
    text: str


class ContentItemInputImage(BaseModel):
    type: Literal["input_image"] = Field(default="input_image")
    image_url: str


class ContentItemOutputText(BaseModel):
    type: Literal["output_text"] = Field(default="output_text")
    text: str


ContentItem: TypeAlias = (
    ContentItemInputText | ContentItemInputImage | ContentItemOutputText
)


class ReasoningItemReasoningSummary(BaseModel):
    type: Literal["summary_text"] = Field(default="summary_text")
    text: str


class ReasoningItemContentReasoningText(BaseModel):
    type: Literal["reasoning_text"] = Field(default="reasoning_text")
    text: str


class ReasoningItemContentText(BaseModel):
    type: Literal["text"] = Field(default="text")
    text: str


ReasoningItemContent: TypeAlias = (
    ReasoningItemContentReasoningText | ReasoningItemContentText
)


class ResponseItemBase(BaseModel):
    type: Literal[
        "message",
        "function_call",
        "function_call_output",
        "reasoning",
        "local_shell_call",
        "other",
    ]


class ResponseItemMessage(ResponseItemBase):
    type: Literal["message"] = Field(default="message")
    id: str | None = Field(default=None)
    role: str
    content: list[ContentItem]


class ResponseItemReasoning(ResponseItemBase):
    type: Literal["reasoning"] = Field(default="reasoning")
    id: str
    summary: list[ReasoningItemReasoningSummary]
    content: list[ReasoningItemContent] | None = Field(default=None)
    encrypted_content: str | None = Field(default=None)


class LocalShellAction(BaseModel):
    type: Literal["exec"] = Field(default="exec")
    command: list[str]
    timeout_ms: int | None = Field(default=None)
    working_directory: str | None = Field(default=None)
    env: dict[str, str] | None = Field(default=None)
    user: str | None = Field(default=None)


class ResponseItemLocalShellCall(ResponseItemBase):
    type: Literal["local_shell_call"] = Field(default="local_shell_call")
    id: str | None = Field(default=None)
    call_id: str | None = Field(default=None)
    status: LocalShellStatus
    action: LocalShellAction


class ResponseItemFunctionCall(ResponseItemBase):
    type: Literal["function_call"] = Field(default="function_call")
    id: str | None = Field(default=None)
    name: str
    arguments: str
    call_id: str


class ResponseItemFunctionCallOutput(ResponseItemBase):
    type: Literal["function_call_output"] = Field(default="function_call_output")
    call_id: str
    output: str


class ResponseItemOther(ResponseItemBase):
    type: Literal["other"] = Field(default="other")


ResponseItem: TypeAlias = (
    ResponseItemMessage
    | ResponseItemReasoning
    | ResponseItemLocalShellCall
    | ResponseItemFunctionCall
    | ResponseItemFunctionCallOutput
    | ResponseItemOther
)


def rollout_log_to_messages(rollout_log: str) -> list[ChatMessage]:
    # read the jsonl as a list of dicts
    records: list[dict[str, Any]] = [
        json.loads(line) for line in rollout_log.splitlines() if len(line) > 0
    ]

    # track some state so we can deal w/ order of response items in the log
    messages: list[ChatMessage] = []
    function_names: dict[str, str] = dict()
    pending_function_calls: list[ResponseItemFunctionCall] = []
    pending_function_call_outputs: list[ResponseItemFunctionCallOutput] = []

    for record in records:
        if "type" not in record:
            continue

        item = parse_response_item(record)

        match item:
            case ResponseItemMessage():
                content = [as_content(c) for c in item.content]
                if item.role == "user":
                    messages.append(ChatMessageUser(content=content))
                elif item.role == "assistant":
                    messages.append(
                        ChatMessageAssistant(
                            content=content,
                            tool_calls=[
                                as_tool_call(call) for call in pending_function_calls
                            ]
                            if len(pending_function_calls) > 0
                            else None,
                        )
                    )

                for function_output in pending_function_call_outputs:
                    messages.append(
                        ChatMessageTool(
                            function=function_names[function_output.call_id],
                            tool_call_id=function_output.call_id,
                            content=function_output.output,
                        )
                    )

                pending_function_calls.clear()
                pending_function_call_outputs.clear()
            case ResponseItemFunctionCall():
                pending_function_calls.append(item)
                function_names[item.call_id] = item.name
            case ResponseItemFunctionCallOutput():
                pending_function_call_outputs.append(item)

    return messages


response_item_adapter = TypeAdapter(ResponseItem)


def parse_response_item(data: dict[str, Any]) -> ResponseItem | None:
    if "type" not in data:
        return None

    try:
        return response_item_adapter.validate_python(data)
    except Exception as ex:
        logger.warning(f"Failed to parse line with type '{data.get('type')}': {ex}")
        return None


def as_content(item: ContentItem) -> ContentText | ContentImage:
    if isinstance(item, ContentItemInputText | ContentItemOutputText):
        return ContentText(text=item.text)
    else:
        return ContentImage(image=item.image_url)


def as_tool_call(call: ResponseItemFunctionCall) -> ToolCall:
    args, parse_error = parse_tool_arguments(call.arguments)
    return ToolCall(
        id=call.call_id,
        function=call.name,
        arguments=args,
        parse_error=parse_error,
    )


def parse_tool_arguments(arguments: str) -> tuple[dict[str, JsonValue], str | None]:
    try:
        return json.loads(arguments), None
    except Exception as ex:
        return {}, str(ex)
