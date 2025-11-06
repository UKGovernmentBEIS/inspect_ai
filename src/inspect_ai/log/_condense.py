from logging import getLogger
from typing import (
    Callable,
    Literal,
    TypedDict,
)

from pydantic import JsonValue

from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentData,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    ContentVideo,
)
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import JsonChange
from inspect_ai._util.url import is_data_uri
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo

from ..event._event import (
    Event,
)
from ..event._info import InfoEvent
from ..event._model import ModelEvent
from ..event._sample_init import SampleInitEvent
from ..event._state import StateEvent
from ..event._store import StoreEvent
from ..event._subtask import SubtaskEvent
from ..event._tool import ToolEvent
from ._log import EvalSample

logger = getLogger(__name__)


ATTACHMENT_PROTOCOL = "attachment://"


class WalkContext(TypedDict):
    message_cache: dict[str, ChatMessage]
    only_core: bool


def condense_sample(sample: EvalSample, log_images: bool = True) -> EvalSample:
    """Reduce the storage size of the eval sample.

    Reduce size by:
    1. De-duplicating larger content fields (especially important for images
       but also for message repeated over and over in the event stream)
    2. Removing base64 encoded images if log_images is True

    The de-duplication of content fields can be reversed by calling
    `resolve_attachments()`. Removal of base64 encoded images is a
    one-way operation.

    Args:
       sample (EvalSample): Eval sample to condense.
       log_images (bool): Should base64 images be logged for this sample.

    Returns:
       EvalSample: Eval sample in condensed form.
    """
    # de-duplicate large content fields as 'attachments'
    attachments: dict[str, str] = dict(sample.attachments)
    events_fn = events_attachment_fn(attachments, log_images)
    messages_fn = messages_attachment_fn(attachments, log_images)

    context = WalkContext(message_cache={}, only_core=False)
    return sample.model_copy(
        update={
            "input": walk_input(sample.input, messages_fn, context),
            "messages": walk_chat_messages(sample.messages, messages_fn, context),
            "events": walk_events(sample.events, events_fn, context),
            "attachments": attachments,
        }
    )


def condense_event(
    event: Event,
    attachments: dict[str, str],
    log_images: bool = True,
    context: WalkContext | None = None,
) -> Event:
    event_fn = events_attachment_fn(attachments, log_images)
    if context is None:
        context = WalkContext(message_cache={}, only_core=False)
    return walk_event(event, event_fn, context)


def events_attachment_fn(
    attachments: dict[str, str], log_images: bool = True
) -> Callable[[str], str]:
    create_attachment = attachment_fn(attachments)

    # for events, we want to strip images when requested and
    # create attachments for text > 100
    def fn(text: str) -> str:
        if not log_images and is_data_uri(text):
            return BASE_64_DATA_REMOVED
        elif len(text) > 100:
            return create_attachment(text)
        else:
            return text

    return fn


def messages_attachment_fn(
    attachments: dict[str, str], log_images: bool = True
) -> Callable[[str], str]:
    create_attachment = attachment_fn(attachments)

    # for messages, we only want to handle images (either stripping
    # them or turning them into attachments as required)
    def fn(text: str) -> str:
        if is_data_uri(text):
            if log_images:
                return create_attachment(text)
            else:
                return BASE_64_DATA_REMOVED
        else:
            return text

    return fn


def attachment_fn(attachments: dict[str, str]) -> Callable[[str], str]:
    def create_attachment(text: str) -> str:
        hash = mm3_hash(text)
        attachments[hash] = text
        return f"{ATTACHMENT_PROTOCOL}{hash}"

    return create_attachment


def resolve_sample_attachments(
    sample: EvalSample,
    resolve_attachments: bool | Literal["full", "core"] = "core",
) -> EvalSample:
    """Resolve content attachments (typically images) in sample.

    Take 'attachment://*` references and resolve them to their
    underlying content, then remove the 'attachments' field.

    Args:
       sample (EvalSample): Eval sample with attachments.
       resolve_attachments: Should attachments be resolved. "core" means only resolving attachments in the core fields.

    Returns:
       EvalSample: Sample with attachment content resolved.
    """
    if resolve_attachments is False:
        return sample

    def content_fn(text: str) -> str:
        # migrate previous flavor of content reference
        CONTENT_PROTOCOL = "tc://"
        if text.startswith(CONTENT_PROTOCOL):
            text = text.replace(CONTENT_PROTOCOL, ATTACHMENT_PROTOCOL, 1)
        # resolve attachment
        if text.startswith(ATTACHMENT_PROTOCOL):
            return sample.attachments.get(
                text.replace(ATTACHMENT_PROTOCOL, "", 1), text
            )
        else:
            return text

    context = WalkContext(
        message_cache={},
        only_core=resolve_attachments == "core",
    )
    return sample.model_copy(
        update={
            "input": walk_input(sample.input, content_fn, context),
            "messages": walk_chat_messages(sample.messages, content_fn, context),
            "events": walk_events(sample.events, content_fn, context),
            "attachments": {},
        }
    )


def attachments_content_fn(
    log_images: bool, max_length: int, attachments: dict[str, str]
) -> Callable[[str], str]:
    def create_attachment(text: str) -> str:
        hash = mm3_hash(text)
        attachments[hash] = text
        return f"{ATTACHMENT_PROTOCOL}{hash}"

    def content_fn(text: str) -> str:
        if not log_images and is_data_uri(text):
            return BASE_64_DATA_REMOVED
        elif len(text) > max_length:
            return create_attachment(text)
        else:
            return text

    return content_fn


def walk_events(
    events: list[Event], content_fn: Callable[[str], str], context: WalkContext
) -> list[Event]:
    return [walk_event(event, content_fn, context) for event in events]


def walk_event(
    event: Event, content_fn: Callable[[str], str], context: WalkContext
) -> Event:
    if isinstance(event, SampleInitEvent):
        return walk_sample_init_event(event, content_fn, context)
    elif isinstance(event, ModelEvent):
        return walk_model_event(event, content_fn, context)
    elif isinstance(event, StateEvent):
        return walk_state_event(event, content_fn, context)
    elif isinstance(event, StoreEvent):
        return walk_store_event(event, content_fn, context)
    elif isinstance(event, SubtaskEvent):
        return walk_subtask_event(event, content_fn, context)
    elif isinstance(event, ToolEvent):
        return walk_tool_event(event, content_fn, context)
    elif isinstance(event, InfoEvent):
        return walk_info_event(event, content_fn, context)
    else:
        return event


def walk_subtask_event(
    event: SubtaskEvent, content_fn: Callable[[str], str], context: WalkContext
) -> SubtaskEvent:
    return event.model_copy(
        update=dict(events=walk_events(event.events, content_fn, context))
    )


def walk_tool_event(
    event: ToolEvent, content_fn: Callable[[str], str], context: WalkContext
) -> ToolEvent:
    return event.model_copy(
        update=dict(
            arguments=walk_json_dict(event.arguments, content_fn, context),
            events=walk_events(event.events, content_fn, context),
        )
    )


def walk_info_event(
    event: InfoEvent, content_fn: Callable[[str], str], context: WalkContext
) -> InfoEvent:
    return event.model_copy(
        update=dict(data=walk_json_value(event.data, content_fn, context))
    )


def walk_sample_init_event(
    event: SampleInitEvent, content_fn: Callable[[str], str], context: WalkContext
) -> SampleInitEvent:
    return event.model_copy(
        update=dict(
            sample=walk_sample(event.sample, content_fn, context),
            state=walk_json_value(event.state, content_fn, context),
        )
    )


def walk_sample(
    sample: Sample, content_fn: Callable[[str], str], context: WalkContext
) -> Sample:
    if isinstance(sample.input, str):
        return sample.model_copy(
            update=dict(input=walk_json_value(sample.input, content_fn, context))
        )
    else:
        return sample.model_copy(
            update=dict(input=walk_chat_messages(sample.input, content_fn, context))
        )


def walk_model_event(
    event: ModelEvent, content_fn: Callable[[str], str], context: WalkContext
) -> ModelEvent:
    return event.model_copy(
        update=dict(
            tools=walk_tools(event.tools, content_fn, context),
            input=walk_chat_messages(event.input, content_fn, context),
            output=walk_model_output(event.output, content_fn, context),
            call=walk_model_call(event.call, content_fn, context),
        ),
    )


def walk_model_output(
    output: ModelOutput, content_fn: Callable[[str], str], context: WalkContext
) -> ModelOutput:
    return output.model_copy(
        update=dict(
            choices=[
                choice.model_copy(
                    update=dict(
                        message=walk_chat_message(choice.message, content_fn, context)
                    )
                )
                for choice in output.choices
            ]
        )
    )


def walk_model_call(
    call: ModelCall | None, content_fn: Callable[[str], str], context: WalkContext
) -> ModelCall | None:
    if context.get("only_core") is True:
        return call
    if call:
        return ModelCall(
            request=walk_json_dict(call.request, content_fn, context),
            response=walk_json_dict(call.response, content_fn, context),
            time=call.time,
        )
    else:
        return None


def walk_state_event(
    event: StateEvent, content_fn: Callable[[str], str], context: WalkContext
) -> StateEvent:
    event = event.model_copy(
        update=dict(
            changes=[
                walk_state_json_change(change, content_fn, context)
                for change in event.changes
            ]
        )
    )
    return event


def walk_store_event(
    event: StoreEvent, content_fn: Callable[[str], str], context: WalkContext
) -> StoreEvent:
    event = event.model_copy(
        update=dict(
            changes=[
                walk_state_json_change(change, content_fn, context)
                for change in event.changes
            ]
        )
    )
    return event


def walk_state_json_change(
    change: JsonChange, content_fn: Callable[[str], str], context: WalkContext
) -> JsonChange:
    return change.model_copy(
        update=dict(value=walk_json_value(change.value, content_fn, context))
    )


def walk_json_value(
    value: JsonValue, content_fn: Callable[[str], str], context: WalkContext
) -> JsonValue:
    if isinstance(value, str):
        return content_fn(value)
    elif isinstance(value, list):
        return [walk_json_value(v, content_fn, context) for v in value]
    elif isinstance(value, dict):
        return walk_json_dict(value, content_fn, context)
    else:
        return value


def walk_json_dict(
    value: dict[str, JsonValue],
    content_fn: Callable[[str], str],
    context: WalkContext,
) -> dict[str, JsonValue]:
    updates: dict[str, JsonValue] = {}
    for k, v in value.items():
        updates[k] = walk_json_value(v, content_fn, context)
    if updates:
        value = value.copy()
        value.update(updates)
    return value


def walk_input(
    input: str | list[ChatMessage],
    content_fn: Callable[[str], str],
    context: WalkContext,
) -> str | list[ChatMessage]:
    if isinstance(input, str):
        return input
    else:
        return walk_chat_messages(input, content_fn, context)


def walk_chat_messages(
    messages: list[ChatMessage],
    content_fn: Callable[[str], str],
    context: WalkContext,
) -> list[ChatMessage]:
    return [walk_chat_message(message, content_fn, context) for message in messages]


def walk_chat_message(
    message: ChatMessage, content_fn: Callable[[str], str], context: WalkContext
) -> ChatMessage:
    cache = context.get("message_cache")
    if cache is not None and message.id is not None:
        hit = cache.get(message.id)
        if hit is not None and hit == message:
            return hit
    if isinstance(message.content, str):
        res = message.model_copy(update=dict(content=content_fn(message.content)))
    else:
        res = message.model_copy(
            update=dict(
                tool_calls=[
                    walk_tool_call(tool_call, content_fn, context)
                    for tool_call in message.tool_calls
                ]
                if isinstance(message, ChatMessageAssistant) and message.tool_calls
                else None,
                content=[
                    walk_content(content, content_fn, context)
                    for content in message.content
                ],
            )
        )
    if cache is not None and message.id is not None:
        cache[message.id] = res
    return res


def walk_content(
    content: Content, content_fn: Callable[[str], str], context: WalkContext
) -> Content:
    if isinstance(content, ContentText):
        return content.model_copy(update=dict(text=content_fn(content.text)))
    elif isinstance(content, ContentImage):
        return content.model_copy(update=dict(image=content_fn(content.image)))
    elif isinstance(content, ContentAudio):
        return content.model_copy(update=dict(audio=content_fn(content.audio)))
    elif isinstance(content, ContentVideo):
        return content.model_copy(update=dict(video=content_fn(content.video)))
    elif isinstance(content, ContentReasoning):
        return content.model_copy(update=dict(reasoning=content_fn(content.reasoning)))
    elif isinstance(content, ContentToolUse):
        return content.model_copy(
            update=dict(
                arguments=walk_json_value(content.arguments, content_fn, context),
                result=walk_json_value(content.result, content_fn, context),
                error=content_fn(content.error) if content.error else content.error,
            )
        )
    elif isinstance(content, ContentData):
        return content.model_copy(
            update=dict(data=walk_json_value(content.data, content_fn, context))
        )
    elif isinstance(content, ContentDocument):
        return content.model_copy(update=dict(document=content_fn(content.document)))


def walk_tools(
    tools: list[ToolInfo], content_fn: Callable[[str], str], context: WalkContext
) -> list[ToolInfo]:
    return [
        tool.model_copy(
            update=dict(
                description=content_fn(tool.description),
            )
        )
        for tool in tools
    ]


def walk_tool_call(
    tool_call: ToolCall, content_fn: Callable[[str], str], context: WalkContext
) -> ToolCall:
    return ToolCall(
        id=tool_call.id,
        function=tool_call.function,
        arguments=walk_json_dict(tool_call.arguments, content_fn, context),
        parse_error=tool_call.parse_error,
        view=tool_call.view.model_copy(
            update=dict(
                content=content_fn(tool_call.view.content)
                if tool_call.view and tool_call.view.content
                else None,
            )
        )
        if tool_call.view
        else None,
        type=tool_call.type,
    )
