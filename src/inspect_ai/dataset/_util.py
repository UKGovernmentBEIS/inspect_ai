import json
from typing import Any, Iterable, cast

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

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
            elif "metadata" in record:
                metadata_field = record.get("metadata")
                if isinstance(metadata_field, str):
                    metadata = json.loads(metadata_field)
                elif isinstance(metadata_field, dict):
                    metadata = metadata_field
                else:
                    raise ValueError(
                        f"Unexpected type for 'metadata' field: {type(metadata_field)}"
                    )

            # return sample
            return Sample(
                input=read_input(record.get(sample_fields.input)),
                target=read_target(record.get(sample_fields.target)),
                choices=read_choices(record.get(sample_fields.choices)),
                id=record.get(sample_fields.id, None),
                metadata=metadata,
                sandbox=read_sandbox(record.get(sample_fields.sandbox)),
                files=read_files(record.get(sample_fields.files)),
                setup=read_setup(record.get(sample_fields.setup)),
            )

        return record_to_sample

    else:
        return sample_fields


def data_to_samples(
    data: Iterable[DatasetRecord], data_to_sample: RecordToSample, auto_id: bool
) -> list[Sample]:
    next_id = 1
    samples: list[Sample] = []
    for record in data:
        record_samples = as_sample_list(data_to_sample(record))
        if auto_id:
            for record_sample in record_samples:
                record_sample.id = next_id
                next_id += 1
        samples.extend(record_samples)
    return samples


def as_sample_list(samples: Sample | list[Sample]) -> list[Sample]:
    if isinstance(samples, list):
        return samples
    else:
        return [samples]


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
                        function=message.get("function", None),
                        error=message.get("error", None),
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


def read_setup(setup: Any | None) -> str | None:
    if setup is not None:
        return str(setup)
    else:
        return None


def read_sandbox(sandbox: Any | None) -> SandboxEnvironmentSpec | None:
    if sandbox is not None:
        if isinstance(sandbox, str):
            if sandbox.strip().startswith("["):
                sandbox = json.loads(sandbox)
            else:
                return SandboxEnvironmentSpec(sandbox)

        if isinstance(sandbox, list):
            if len(sandbox) == 2:
                return SandboxEnvironmentSpec(str(sandbox[0]), str(sandbox[1]))
            else:
                raise ValueError(
                    f"Invalid 'sandbox' value: '{str(sandbox)}'. Sandbox must be string or 2-item list"
                )

        # didn't find the right type
        raise ValueError(f"Unexpected type for 'sandbox' field: {type(sandbox)}")
    else:
        return None


def read_files(files: Any | None) -> dict[str, str] | None:
    if files is not None:
        if isinstance(files, str):
            files = json.loads(files)
        if isinstance(files, dict):
            if all(isinstance(v, str) for v in files.values()):
                return cast(dict[str, str], files)

        # didn't find the right type
        raise ValueError(f"Unexpected type for 'files' field: {type(files)}")
    else:
        return None
