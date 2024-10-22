from logging import getLogger
from typing import (
    Callable,
)

import mmh3
from pydantic import JsonValue

from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.json import JsonChange
from inspect_ai._util.url import is_data_uri
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput

from ._log import EvalSample
from ._transcript import (
    Event,
    ModelEvent,
    SampleInitEvent,
    StateEvent,
    StoreEvent,
    SubtaskEvent,
    ToolEvent,
)

logger = getLogger(__name__)


ATTACHMENT_PROTOCOL = "attachment://"


def condense_sample(sample: EvalSample, log_images: bool = True) -> EvalSample:
    """Reduce the storage size of the eval sample.

    Reduce size by:
    1. De-duplciating larger content fields (especially important for images
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
    attachments: dict[str, str] = {}

    def create_attachment(text: str) -> str:
        hash = mm3_hash(text)
        attachments[hash] = text
        return f"{ATTACHMENT_PROTOCOL}{hash}"

    # for events, we want to strip images when requested and
    # create attachments for text > 100
    def events_fn(text: str) -> str:
        if not log_images and is_data_uri(text):
            return BASE_64_DATA_REMOVED
        elif len(text) > 100:
            return create_attachment(text)
        else:
            return text

    # for messages, we only want to handle images (either stripping
    # them or turning them into attachments as required)
    def messages_fn(text: str) -> str:
        if is_data_uri(text):
            if log_images:
                return create_attachment(text)
            else:
                return BASE_64_DATA_REMOVED
        else:
            return text

    return sample.model_copy(
        update={
            "input": walk_input(sample.input, messages_fn),
            "messages": walk_chat_messages(sample.messages, messages_fn),
            "events": walk_events(sample.events, events_fn),
            "attachments": attachments,
        }
    )


def resolve_sample_attachments(sample: EvalSample) -> EvalSample:
    """Resolve content attachments (typically images) in sample.

    Take 'attachment://*` references and resolve them to their
    underlying content, then remove the 'attachments' field.

    Args:
       sample (EvalSample): Eval sample with attachments.

    Returns:
       EvalSample: Sample with attachment content resolved.
    """

    def content_fn(text: str) -> str:
        # migrate previous flavor of content reference
        CONTENT_PROTOCOL = "tc://"
        if text.startswith(CONTENT_PROTOCOL):
            text = text.replace(CONTENT_PROTOCOL, ATTACHMENT_PROTOCOL, 1)
        # resovle attachment
        if text.startswith(ATTACHMENT_PROTOCOL):
            return sample.attachments.get(
                text.replace(ATTACHMENT_PROTOCOL, "", 1), text
            )
        else:
            return text

    return sample.model_copy(
        update={
            "input": walk_input(sample.input, content_fn),
            "messages": walk_chat_messages(sample.messages, content_fn),
            "events": walk_events(sample.events, content_fn),
            "attachments": {},
        }
    )


def walk_events(events: list[Event], content_fn: Callable[[str], str]) -> list[Event]:
    return [walk_event(event, content_fn) for event in events]


def walk_event(event: Event, content_fn: Callable[[str], str]) -> Event:
    if isinstance(event, SampleInitEvent):
        return walk_sample_init_event(event, content_fn)
    elif isinstance(event, ModelEvent):
        return walk_model_event(event, content_fn)
    elif isinstance(event, StateEvent):
        return walk_state_event(event, content_fn)
    elif isinstance(event, StoreEvent):
        return walk_store_event(event, content_fn)
    elif isinstance(event, SubtaskEvent):
        return walk_subtask_event(event, content_fn)
    elif isinstance(event, ToolEvent):
        return walk_tool_event(event, content_fn)
    else:
        return event


def walk_subtask_event(
    event: SubtaskEvent, content_fn: Callable[[str], str]
) -> SubtaskEvent:
    return event.model_copy(update=dict(events=walk_events(event.events, content_fn)))


def walk_tool_event(event: ToolEvent, content_fn: Callable[[str], str]) -> ToolEvent:
    return event.model_copy(update=dict(events=walk_events(event.events, content_fn)))


def walk_sample_init_event(
    event: SampleInitEvent, content_fn: Callable[[str], str]
) -> SampleInitEvent:
    return event.model_copy(
        update=dict(
            sample=walk_sample(event.sample, content_fn),
            state=walk_json_value(event.state, content_fn),
        )
    )


def walk_sample(sample: Sample, content_fn: Callable[[str], str]) -> Sample:
    if isinstance(sample.input, str):
        return sample.model_copy(
            update=dict(input=walk_json_value(sample.input, content_fn))
        )
    else:
        return sample.model_copy(
            update=dict(input=walk_chat_messages(sample.input, content_fn))
        )


def walk_model_event(event: ModelEvent, content_fn: Callable[[str], str]) -> ModelEvent:
    return event.model_copy(
        update=dict(
            input=walk_chat_messages(event.input, content_fn),
            output=walk_model_output(event.output, content_fn),
            call=walk_model_call(event.call, content_fn),
        ),
    )


def walk_model_output(
    output: ModelOutput, content_fn: Callable[[str], str]
) -> ModelOutput:
    return output.model_copy(
        update=dict(
            choices=[
                choice.model_copy(
                    update=dict(message=walk_chat_message(choice.message, content_fn))
                )
                for choice in output.choices
            ]
        )
    )


def walk_model_call(
    call: ModelCall | None, content_fn: Callable[[str], str]
) -> ModelCall | None:
    if call:
        return ModelCall(
            request=walk_json_dict(call.request, content_fn),
            response=walk_json_dict(call.response, content_fn),
        )
    else:
        return None


def walk_state_event(event: StateEvent, content_fn: Callable[[str], str]) -> StateEvent:
    event = event.model_copy(
        update=dict(
            changes=[
                walk_state_json_change(change, content_fn) for change in event.changes
            ]
        )
    )
    return event


def walk_store_event(event: StoreEvent, content_fn: Callable[[str], str]) -> StoreEvent:
    event = event.model_copy(
        update=dict(
            changes=[
                walk_state_json_change(change, content_fn) for change in event.changes
            ]
        )
    )
    return event


def walk_state_json_change(
    change: JsonChange, content_fn: Callable[[str], str]
) -> JsonChange:
    return change.model_copy(
        update=dict(value=walk_json_value(change.value, content_fn))
    )


def walk_json_value(value: JsonValue, content_fn: Callable[[str], str]) -> JsonValue:
    if isinstance(value, str):
        return content_fn(value)
    elif isinstance(value, list):
        return [walk_json_value(v, content_fn) for v in value]
    elif isinstance(value, dict):
        return walk_json_dict(value, content_fn)
    else:
        return value


def walk_json_dict(
    value: dict[str, JsonValue], content_fn: Callable[[str], str]
) -> dict[str, JsonValue]:
    updates: dict[str, JsonValue] = {}
    for k, v in value.items():
        updates[k] = walk_json_value(v, content_fn)
    if updates:
        value = value.copy()
        value.update(updates)
    return value


def walk_input(
    input: str | list[ChatMessage], content_fn: Callable[[str], str]
) -> str | list[ChatMessage]:
    if isinstance(input, str):
        return input
    else:
        return walk_chat_messages(input, content_fn)


def walk_chat_messages(
    messages: list[ChatMessage], content_fn: Callable[[str], str]
) -> list[ChatMessage]:
    return [walk_chat_message(message, content_fn) for message in messages]


def walk_chat_message(
    message: ChatMessage, content_fn: Callable[[str], str]
) -> ChatMessage:
    if isinstance(message.content, str):
        return message.model_copy(update=dict(content=content_fn(message.content)))
    else:
        return message.model_copy(
            update=dict(
                content=[
                    walk_content(content, content_fn) for content in message.content
                ]
            )
        )


def walk_content(content: Content, content_fn: Callable[[str], str]) -> Content:
    if isinstance(content, ContentText):
        return content.model_copy(update=dict(text=content_fn(content.text)))
    elif isinstance(content, ContentImage):
        return content.model_copy(update=dict(image=content_fn(content.image)))


def mm3_hash(message: str) -> str:
    # Generate the 128-bit hash as two 64-bit integers
    h1, h2 = mmh3.hash64(message.encode("utf-8"))

    # Convert to unsigned integers and then to hexadecimal
    return f"{h1 & 0xFFFFFFFFFFFFFFFF:016x}{h2 & 0xFFFFFFFFFFFFFFFF:016x}"
