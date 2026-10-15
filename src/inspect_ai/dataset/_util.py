import json
import math
import numbers
import sys
from typing import Any, Iterable, NamedTuple, cast

from pydantic import ValidationError

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

from ._dataset import (
    Dataset,
    DatasetRecord,
    FieldSpec,
    RecordToSample,
    Sample,
)


def normalise_sample_id(id: str | int | None) -> str:
    if isinstance(id, str) and id.isdigit():
        id = int(id)
    return id if isinstance(id, str) else str(id).zfill(20)


SampleIdEpoch = tuple[str | int, int]
"""A sample's dataset-typed ``(id, epoch)``."""


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
                if isinstance(sample_fields.metadata, list):
                    metadata = {}
                    for name in sample_fields.metadata:
                        metadata[name] = record.get(name)
                else:
                    # must be frozen
                    if not sample_fields.metadata.model_config.get("frozen", False):
                        raise ValueError(
                            f"Metadata model {sample_fields.metadata.__name__} must have frozen=True"
                        )

                    # filter to only fields in the model
                    model_fields = record.get("metadata", None)
                    if isinstance(model_fields, str):
                        model_fields = json.loads(model_fields)
                    elif model_fields is None:
                        model_fields = {
                            k: v
                            for k, v in record.items()
                            if k in sample_fields.metadata.__pydantic_fields__.keys()
                        }

                    # parse and return metadata
                    try:
                        metadata = sample_fields.metadata(**model_fields).model_dump()
                    except ValidationError as ex:
                        raise ValueError(
                            f"Could not parse metadata into {sample_fields.metadata.__name__}: {ex}"
                        )
            elif "metadata" in record:
                metadata_field = record.get("metadata")
                if is_none_or_nan(metadata_field):
                    metadata = None
                elif isinstance(metadata_field, str):
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
                description=read_description(record.get(sample_fields.description))
                if sample_fields.description is not None
                else None,
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


def is_none_or_nan(obj: Any) -> bool:
    return obj is None or (isinstance(obj, float) and math.isnan(obj))


def read_input(input: Any | None) -> str | list[ChatMessage]:
    if is_none_or_nan(input) or not input:
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
    # treat float NaN (commonly produced by HuggingFace / pandas for missing
    # string values) the same as None rather than stringifying it to "nan"
    if is_none_or_nan(obj):
        return ""
    return [str(item) for item in obj] if isinstance(obj, list) else str(obj)


def read_choices(obj: Any | None) -> list[str] | None:
    if not is_none_or_nan(obj):
        if isinstance(obj, list):
            # drop empty entries the same way as the string branch
            return [str(choice) for choice in obj if str(choice).strip()]
        elif isinstance(obj, str):
            choices = obj.split(",")
            if len(choices) == 1:
                choices = obj.split()
            # drop empty entries so a trailing or doubled comma does not
            # produce an empty-string choice
            return [choice.strip() for choice in choices if choice.strip()]
        else:
            return [str(obj)]
    else:
        return None


def read_description(description: Any | None) -> str | None:
    if is_none_or_nan(description):
        return None
    if not isinstance(description, str):
        raise ValueError(
            f"Sample 'description' field must be a string (got {type(description).__name__})"
        )
    # empty CSV cells read as "" (no description)
    return description or None


def read_setup(setup: Any | None) -> str | None:
    if not is_none_or_nan(setup):
        return str(setup)
    else:
        return None


def read_sandbox(sandbox: Any | None) -> SandboxEnvironmentSpec | None:
    if not is_none_or_nan(sandbox):
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
    if not is_none_or_nan(files):
        if isinstance(files, str):
            files = json.loads(files)
        if isinstance(files, dict):
            if all(isinstance(v, str) for v in files.values()):
                return cast(dict[str, str], files)

        # didn't find the right type
        raise ValueError(f"Unexpected type for 'files' field: {type(files)}")
    else:
        return None


def shuffle_choices_if_requested(
    dataset: Dataset, shuffle_choices: bool | int | None
) -> None:
    """
    Shuffle the choices in the dataset if requested.

    The `shuffle_choices` parameter passed to `json_dataset`, `csv_dataset`,
    and `hf_dataset` can be a boolean, an integer, or `None` (default).
    If it is a boolean, it will shuffle the choices if the value is `True`,
    and do nothing if it is `False`.
    If it is an integer, it will shuffle the choices using the integer as the seed.
    """
    # Note that `isinstance(x, int)` returns True if x is True or False,
    # so we need to check for both explicitly
    if shuffle_choices is True:
        dataset.shuffle_choices()
    elif shuffle_choices is False:
        pass
    elif isinstance(shuffle_choices, int):
        dataset.shuffle_choices(seed=shuffle_choices)


class ResolvedShuffle(NamedTuple):
    """Shuffle settings for a dataset loader.

    `seed` is None for an unseeded shuffle and is ignored when `enabled` is False.
    """

    enabled: bool
    seed: int | None


def resolve_shuffle(shuffle: bool | int | None, seed: int | None) -> ResolvedShuffle:
    """Resolve the `shuffle` and `seed` arguments passed to a dataset loader.

    A boolean `shuffle` uses `seed` as given, and None means no shuffle. An
    integer `shuffle` (including 0) is itself the seed, so passing a non-None
    `seed` with it is an error. `bool` is a subclass of `int`, so booleans are
    checked first. numpy booleans and integers are accepted the same way.

    Raises:
        TypeError: If `shuffle` is not a bool, int or None.
        ValueError: If `shuffle` is a negative integer, or an integer passed
            with a non-None `seed`.
    """
    if shuffle is None:
        return ResolvedShuffle(enabled=False, seed=seed)
    if isinstance(shuffle, bool) or _is_numpy_bool(shuffle):
        return ResolvedShuffle(enabled=bool(shuffle), seed=seed)
    if not isinstance(shuffle, numbers.Integral):
        raise TypeError(
            f"shuffle must be a bool or an int seed, got {type(shuffle).__name__}."
        )
    shuffle_seed = int(shuffle)
    if shuffle_seed < 0:
        raise ValueError(f"shuffle seed must be non-negative, got {shuffle_seed}.")
    if seed is not None:
        raise ValueError(
            f"Pass either an integer shuffle seed (shuffle={shuffle_seed}) or seed={seed}, not both."
        )
    return ResolvedShuffle(enabled=True, seed=shuffle_seed)


def _is_numpy_bool(value: object) -> bool:
    # a numpy bool can only exist if numpy is already imported, so check
    # sys.modules rather than importing numpy here
    numpy = sys.modules.get("numpy")
    return numpy is not None and isinstance(value, numpy.bool_)
