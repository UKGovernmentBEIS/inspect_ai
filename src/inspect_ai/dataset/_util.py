from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)

from ._dataset import (
    DatasetRecord,
    FieldSpec,
    RecordToSample,
    Sample,
)


# determine how we will go from file records to samples. if there is
# no field spec, we assume the column names "input" and "target",
# otherwise use the provided field spec or custom converter function
def record_to_sample_fn(
    sample_fields: FieldSpec | RecordToSample | None,
) -> RecordToSample:
    if sample_fields is None:
        sample_fields = FieldSpec()

    if isinstance(sample_fields, FieldSpec):

        def record_to_sample(record: DatasetRecord) -> Sample:
            # collect metadata if specified
            metadata: dict[str, Any] | None = None
            if sample_fields.metadata:
                metadata = {}
                for name in sample_fields.metadata:
                    metadata[name] = record.get(name)

            # return sample
            return Sample(
                input=read_input(record.get(sample_fields.input)),
                target=read_target(record.get(sample_fields.target)),
                choices=read_choices(record.get(sample_fields.choices)),
                id=record.get(sample_fields.id, None),
                metadata=metadata,
            )

    else:

        def record_to_sample(record: DatasetRecord) -> Sample:
            return sample_fields(record)

    return record_to_sample


def read_input(input: Any | None) -> str | list[ChatMessage]:
    if not input:
        raise ValueError("No input in dataset")
    if not isinstance(input, str):
        return read_messages(input)
    else:
        return input


def read_messages(messages: list[dict[str, Any]]) -> list[ChatMessage]:
    chat_messages: list[ChatMessage] = []
    for message in messages:
        role = message.get("role", None)

        content = message.get("content", None)
        if content is None:
            raise ValueError("content not specified for chat input in dataset")

        match role:
            case "system":
                chat_messages.append(ChatMessageSystem(content=content, source="input"))
            case "user":
                chat_messages.append(ChatMessageUser(content=content, source="input"))
            case "assistant":
                chat_messages.append(
                    ChatMessageAssistant(
                        content=content,
                        source="input",
                        tool_calls=message.get("tool_calls", None),
                    )
                )
            case "tool":
                chat_messages.append(
                    ChatMessageTool(
                        content=content,
                        source="input",
                        tool_call_id=message.get("tool_call_id", None),
                        tool_error=message.get("tool_error", None),
                    )
                )
            case _:
                raise ValueError("role not specified for chat input in dataset")

    return chat_messages


def read_target(obj: Any | None) -> str | list[str]:
    if obj is not None:
        return [str(item) for item in obj] if isinstance(obj, list) else str(obj)
    else:
        return ""


def read_choices(obj: Any | None) -> list[str] | None:
    if obj is not None:
        if isinstance(obj, list):
            return [str(choice) for choice in obj]
        elif isinstance(obj, str):
            choices = obj.split(",")
            if len(choices) == 1:
                choices = obj.split()
            return [choice.strip() for choice in choices]
        else:
            return [str(obj)]
    else:
        return None
