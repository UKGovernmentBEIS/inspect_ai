import os
from pathlib import Path
from typing import Type, TypeVar

import pytest
from test_helpers.utils import skip_if_github_action

from inspect_ai._util.content import ContentImage
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
    assert isinstance(dataset[0].sandbox, tuple)
    assert dataset[0].sandbox[0] == "docker"


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
    dataset: Dataset = type.__call__(dataset_path(file))
    assert dataset[0].metadata and dataset[0].metadata.get("foo") == "bar"


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


def test_dataset_auto_id() -> None:
    dataset = json_dataset(dataset_path("dataset.jsonl"))
    assert all(sample.id is None for sample in dataset)
    dataset = json_dataset(dataset_path("dataset.jsonl"), auto_id=True)
    assert [sample.id for sample in dataset] == [id for id in range(1, 11)]


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
