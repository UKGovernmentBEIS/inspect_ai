import os
from typing import Type, TypeVar

import pytest
from test_helpers.utils import skip_if_github_action

from inspect_ai.dataset import (
    Dataset,
    FieldSpec,
    Sample,
    csv_dataset,
    example_dataset,
    file_dataset,
    json_dataset,
)

T_ds = TypeVar("T_ds")

# test functions are parameterized by dataset type and input file
csv = (csv_dataset, "samples.csv")
json = (json_dataset, "samples.json")
jsonl = (file_dataset, "samples.jsonl")
dataset_params = [csv, json, jsonl]


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


# test reading a dataset with a custom data_to_sample function
@pytest.mark.parametrize("type,file", dataset_params)
def test_dataset_fields_fn(type: Type[T_ds], file: str) -> None:
    dataset: Dataset = type.__call__(
        dataset_path(file),
        sample_fields=data_to_sample,
    )
    assert_sample(dataset[0])


@skip_if_github_action
def test_dataset_read_id() -> None:
    dataset = example_dataset(
        "biology_qa",
        FieldSpec(input="question", target="answer", id="id"),
    )
    assert dataset[0].id == "q1"


sample_field_spec = FieldSpec(input="input", target="label", metadata=["extra"])


def data_to_sample(data: dict) -> Sample:
    return Sample(
        input=str(data.get("input")),
        target=str(data.get("label")),
        metadata={"extra": data.get("extra")},
    )


def assert_sample(sample: Sample) -> None:
    assert sample.input == "Say 'Hello, World'"
    assert sample.target == "Hello, World"
    if sample.metadata:
        assert sample.metadata.get("extra") == "data"


def dataset_path(file: str) -> str:
    return os.path.join("tests", "dataset", "test_dataset", file)


def example_path(*paths: str) -> str:
    return os.path.join("examples", "/".join(paths))
