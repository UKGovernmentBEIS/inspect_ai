import json as json_module
import os
from pathlib import Path
from typing import Type, TypeVar

import pytest
from pydantic import BaseModel
from test_helpers.utils import skip_if_github_action

from inspect_ai._util.content import ContentImage
from inspect_ai._util.file import exists
from inspect_ai.dataset import (
    Dataset,
    FieldSpec,
    Sample,
    csv_dataset,
    example_dataset,
    file_dataset,
    json_dataset,
)
from inspect_ai.model._chat_message import ChatMessageUser

T_ds = TypeVar("T_ds")

# test functions are parameterized by dataset type and input file
csv = (csv_dataset, "samples.csv")
json = (json_dataset, "samples.json")
jsonl = (file_dataset, "samples.jsonl")
dataset_params = [csv, json, jsonl]

dataset_md_params = [
    (param[0], param[1].replace(".", "-md.")) for param in dataset_params
]

dataset_mcq_params = [
    (param[0], param[1].replace(".", "-mcq.")) for param in dataset_params
]


# test reading a dataset using default configuration
@pytest.mark.parametrize("type,file", dataset_params)
def test_dataset(type: Type[T_ds], file: str) -> None:
    dataset: Dataset = type.__call__(dataset_path(file))
    assert_sample(dataset[0])


# test reading a dataset with an explicit fields specification
@pytest.mark.parametrize("type,file", dataset_params)
def test_dataset_fields(type: Type[T_ds], file: str) -> None:
    dataset: Dataset = type.__call__(
        dataset_path(file), sample_fields=sample_field_spec
    )
    assert_sample(dataset[0])
    assert isinstance(dataset[0].sandbox, BaseModel)
    assert dataset[0].sandbox.type == "docker"


# test reading a dataset with a custom data_to_sample function
@pytest.mark.parametrize("type,file", dataset_params)
def test_dataset_fields_fn(type: Type[T_ds], file: str) -> None:
    dataset: Dataset = type.__call__(
        dataset_path(file),
        sample_fields=data_to_sample,
    )
    assert len(dataset) == 1
    assert_sample(dataset[0])


@pytest.mark.parametrize("type,file", dataset_params)
def test_dataset_multiple_samples_fn(type: Type[T_ds], file: str):
    dataset: Dataset = type.__call__(
        dataset_path(file),
        sample_fields=data_to_sample_multiple,
    )
    assert len(dataset) == 2


# test reading metadata field
@pytest.mark.parametrize("type,file", dataset_md_params)
def test_dataset_metadata(type: Type[T_ds], file: str) -> None:
    sample_fields = (
        FieldSpec(metadata=["name", "age", "foo"]) if file.endswith(".json") else None
    )
    dataset: Dataset = type.__call__(dataset_path(file), sample_fields=sample_fields)
    assert dataset[0].metadata and dataset[0].metadata.get("foo") == "bar"


# test pydantic metadata handling
@pytest.mark.parametrize("type,file", dataset_md_params)
def test_dataset_metadata_pydantic(type: Type[T_ds], file: str) -> None:
    class Metadata(BaseModel, frozen=True):
        name: str
        age: int
        foo: str

    dataset: Dataset = type.__call__(
        dataset_path(file), sample_fields=FieldSpec(metadata=Metadata)
    )
    assert dataset[0].metadata and dataset[0].metadata.get("foo") == "bar"
    metadata = dataset[0].metadata_as(Metadata)
    assert metadata.name == "jim"
    assert metadata.age == 42
    assert metadata.foo == "bar"

    class MetadataSlice(BaseModel, frozen=True):
        foo: str

    dataset = type.__call__(
        dataset_path(file), sample_fields=FieldSpec(metadata=MetadataSlice)
    )
    metadata_slice = dataset[0].metadata_as(MetadataSlice)
    assert metadata_slice.foo == "bar"

    class MetadataInvalid(BaseModel, frozen=True):
        x: int
        y: int

    with pytest.raises(ValueError):
        dataset = type.__call__(
            dataset_path(file), sample_fields=FieldSpec(metadata=MetadataInvalid)
        )

    class MetadataNotFrozen(BaseModel):
        name: str
        age: int
        foo: str

    with pytest.raises(ValueError):
        dataset = type.__call__(
            dataset_path(file), sample_fields=FieldSpec(metadata=MetadataNotFrozen)
        )


# test shuffling choices
@pytest.mark.parametrize("type,file", dataset_mcq_params)
def test_dataset_shuffle_choices_true_uses_no_seed(type: Type[T_ds], file: str) -> None:
    dataset_1, dataset_2 = [
        type.__call__(dataset_path(file), shuffle_choices=True) for _ in range(2)
    ]
    assert dataset_1[0].choices != dataset_2[0].choices


# test explicitly not shuffling choices
@pytest.mark.parametrize("type,file", dataset_mcq_params)
def test_dataset_shuffle_choices_false_does_not_shuffle(
    type: Type[T_ds], file: str
) -> None:
    dataset_1, dataset_2 = [
        type.__call__(dataset_path(file), shuffle_choices=False) for _ in range(2)
    ]
    assert dataset_1[0].choices == dataset_2[0].choices


@skip_if_github_action
def test_dataset_read_id() -> None:
    dataset = example_dataset(
        "biology_qa",
        FieldSpec(input="question", target="answer", id="id"),
    )
    assert dataset[0].id == "q1"


def test_example_dataset_not_found() -> None:
    with pytest.raises(ValueError):
        example_dataset("not_found")


def test_dataset_image_paths() -> None:
    dataset = json_dataset(dataset_path("images.jsonl"))
    sample = dataset[0]
    assert not isinstance(sample.input, str)
    assert isinstance(sample.input[0], ChatMessageUser)
    assert isinstance(sample.input[0].content[1], ContentImage)
    image = Path(sample.input[0].content[1].image)
    assert image.exists()


def test_dataset_image_paths_file_uri() -> None:
    # dataset locations that are filesystem URIs should keep their scheme and
    # still resolve relative sample files against the dataset's parent dir
    dataset = json_dataset(Path(dataset_path("images.jsonl")).resolve().as_uri())
    assert dataset.location is not None
    assert dataset.location.startswith("file://")
    sample = dataset[0]
    assert not isinstance(sample.input, str)
    assert isinstance(sample.input[0], ChatMessageUser)
    content = sample.input[0].content[1]
    assert isinstance(content, ContentImage)
    assert content.image.startswith("file://")
    assert exists(content.image)


def test_dataset_auto_id() -> None:
    dataset = json_dataset(dataset_path("dataset.jsonl"))
    assert all(sample.id is None for sample in dataset)
    dataset = json_dataset(dataset_path("dataset.jsonl"), auto_id=True)
    assert [sample.id for sample in dataset] == [id for id in range(1, 11)]


def test_dataset_nan_target_treated_as_missing() -> None:
    # HuggingFace / pandas-backed sources represent missing string values as
    # float NaN. These must be treated like None (-> ""), not stringified to
    # the literal "nan" (which would silently become the gold answer).
    from inspect_ai.dataset._util import record_to_sample_fn

    rec2sample = record_to_sample_fn(FieldSpec())

    sample = rec2sample({"input": "What is 2+2?", "target": float("nan")})
    assert not isinstance(sample, list)
    assert sample.target == "", (
        f"float NaN target should be treated as missing, got {sample.target!r}"
    )

    # None already handled correctly; keep as a regression guard
    sample_none = rec2sample({"input": "x", "target": None})
    assert not isinstance(sample_none, list)
    assert sample_none.target == ""

    # numeric (non-NaN) targets should still be stringified
    sample_num = rec2sample({"input": "x", "target": 4})
    assert not isinstance(sample_num, list)
    assert sample_num.target == "4"


def test_csv_dataset_skips_blank_ragged_row(tmp_path: Path) -> None:
    # A blank row with fewer fields than the header used to crash the empty-row
    # filter with `AttributeError: 'NoneType' object has no attribute 'strip'`
    # (csv.DictReader fills the missing column with None). The filter should skip
    # the ragged blank row and load the two real rows. See issue #4546.
    csv_file = tmp_path / "ragged.csv"
    csv_file.write_text("input,target,id\n2+2,4,q1\n,\n3+3,6,q2\n", newline="")
    dataset = csv_dataset(str(csv_file))
    assert len(dataset) == 2
    assert [str(sample.input) for sample in dataset] == ["2+2", "3+3"]


def test_csv_value_has_content_handles_ragged_values() -> None:
    # Guards both non-string branches produced by ragged rows: None (short row,
    # missing column) and a list (long row, extras collected under the restkey).
    from inspect_ai.dataset._sources.csv import _value_has_content

    assert _value_has_content(None) is False
    assert _value_has_content([""]) is False
    assert _value_has_content(["x"]) is True
    assert _value_has_content("") is False
    assert _value_has_content(" a ") is True


def test_dataset_zero_seed() -> None:
    dataset1 = json_dataset(dataset_path("dataset.jsonl"), shuffle=True, seed=0)
    dataset2 = json_dataset(dataset_path("dataset.jsonl"), shuffle=True, seed=0)
    assert [s.target for s in dataset1] == [s.target for s in dataset2]


def test_json_dataset_supports_kwargs() -> None:
    before = "Joe Biden"
    after = "Donald Trump"

    dataset_no_kwargs = json_dataset(dataset_path("dataset.jsonl"))
    assert (
        not isinstance((chat_message := dataset_no_kwargs[0].input[0]), str)
        and before in chat_message.content
        and after not in chat_message.content
    )

    def custom_loads(line: str):
        # Not a recommended pattern.
        # More idiomatic use cases
        # involve dealing with NaNs
        # and other nonstandard
        # types.
        data = json_module.loads(line)
        data["input"][0]["content"] = data["input"][0]["content"].replace(
            before,
            after,
        )
        return data

    dataset_custom = json_dataset(dataset_path("dataset.jsonl"), loads=custom_loads)
    assert (
        not isinstance((chat_message := dataset_custom[0].input[0]), str)
        and after in chat_message.content
        and before not in chat_message.content
    )


sample_field_spec = FieldSpec(input="input", target="label", metadata=["extra"])


def data_to_sample(data: dict) -> Sample:
    return Sample(
        input=str(data.get("input")),
        target=str(data.get("label")),
        metadata={"extra": data.get("extra")},
    )


def data_to_sample_multiple(data: dict) -> list[Sample]:
    return [data_to_sample(data), data_to_sample(data)]


def assert_sample(sample: Sample) -> None:
    assert sample.input == "Say 'Hello, World'"
    assert sample.target == "Hello, World"
    if sample.metadata:
        assert sample.metadata.get("extra") == "data"


def dataset_path(file: str) -> str:
    return os.path.join("tests", "dataset", "test_dataset", file)


def example_path(*paths: str) -> str:
    return os.path.join("examples", "/".join(paths))
