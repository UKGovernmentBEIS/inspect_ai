import json as json_module
import os
from pathlib import Path
from typing import Type, TypeVar
from unittest.mock import Mock

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

limit_dataset_params = [
    (csv_dataset, ".csv", '"input","target"\n"a","1"\n"b","2"\n'),
    (
        json_dataset,
        ".json",
        json_module.dumps(
            [{"input": "a", "target": "1"}, {"input": "b", "target": "2"}]
        ),
    ),
]


@pytest.mark.parametrize(
    ("suffix", "reader", "file_argument"),
    [
        (".csv", "csv_dataset", "csv_file"),
        (".json", "json_dataset", "json_file"),
        (".jsonl", "json_dataset", "json_file"),
    ],
)
def test_file_dataset_url_query_uses_path_extension(
    suffix: str,
    reader: str,
    file_argument: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"https://example.test/dataset{suffix}?signature=abc123"
    expected = object()
    mock_reader = Mock(return_value=expected)
    monkeypatch.setattr(f"inspect_ai.dataset._sources.file.{reader}", mock_reader)

    assert file_dataset(url) is expected
    assert mock_reader.call_args.kwargs[file_argument] == url


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


@pytest.mark.parametrize("type,suffix,contents", limit_dataset_params)
@pytest.mark.parametrize("limit,expected", [(None, 2), (0, 0), (1, 1)])
def test_dataset_limit(
    type: Type[T_ds],
    suffix: str,
    contents: str,
    limit: int | None,
    expected: int,
    tmp_path: Path,
) -> None:
    dataset_file = tmp_path / f"dataset{suffix}"
    dataset_file.write_text(contents)

    dataset: Dataset = type.__call__(str(dataset_file), limit=limit)

    assert len(dataset) == expected


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


def write_ragged_csv(tmp_path: Path, body: str) -> str:
    path = tmp_path / "data.csv"
    path.write_text(body, newline="")
    return str(path)


def test_csv_short_blank_row_names_the_line(tmp_path: Path) -> None:
    # 2 fields under a 3 column header, which used to die on AttributeError
    csv_file = write_ragged_csv(tmp_path, "input,target,id\n2+2,4,q1\n,\n3+3,6,q2\n")

    with pytest.raises(ValueError) as info:
        csv_dataset(csv_file)

    message = str(info.value)
    assert "line 3" in message
    assert "2 fields, the header has 3" in message
    assert "id" in message


def test_csv_long_row_names_the_line(tmp_path: Path) -> None:
    csv_file = write_ragged_csv(tmp_path, "input,target\n2+2,4\n,,extra\n")

    with pytest.raises(ValueError) as info:
        csv_dataset(csv_file)

    message = str(info.value)
    assert "line 3" in message
    assert "3 fields, the header has 2" in message
    assert "extra" in message


def test_csv_short_row_with_content_is_not_silently_truncated(tmp_path: Path) -> None:
    # used to load, dropping the missing column as None
    csv_file = write_ragged_csv(tmp_path, "input,target,id\n2+2,4\n")

    with pytest.raises(ValueError, match="No value for: id"):
        csv_dataset(csv_file)


def test_csv_long_row_with_content_is_not_silently_absorbed(tmp_path: Path) -> None:
    # used to load too, with the extras swallowed by the restkey
    csv_file = write_ragged_csv(tmp_path, "input,target\n2+2,4\n3+3,6,extra\n")

    with pytest.raises(ValueError, match="Unexpected values"):
        csv_dataset(csv_file)


def test_csv_singular_field_count_reads_correctly(tmp_path: Path) -> None:
    csv_file = write_ragged_csv(tmp_path, "a,b,c,d\n1,2,3,4\nz\n")

    with pytest.raises(ValueError, match="has 1 field, the header has 4"):
        csv_dataset(csv_file)


def test_csv_line_number_with_explicit_fieldnames(tmp_path: Path) -> None:
    # no header line to skip when fieldnames are supplied
    csv_file = write_ragged_csv(tmp_path, "2+2,4,q1\n,\n")

    with pytest.raises(ValueError) as info:
        csv_dataset(csv_file, fieldnames=["input", "target", "id"])

    assert "line 2" in str(info.value)


def test_csv_line_number_survives_blank_lines_and_multiline_fields(
    tmp_path: Path,
) -> None:
    # the reader skips blank lines and a quoted field can span several, so
    # counting rows as they come out drifts away from the file. Here that
    # would say 4; the ragged row is really on line 7.
    csv_file = write_ragged_csv(
        tmp_path, 'input,target\n2+2,4\n\n\n"multi\nline",6\nragged\n'
    )

    with pytest.raises(ValueError) as info:
        csv_dataset(csv_file)

    assert "line 7" in str(info.value)


def test_csv_well_formed_blank_row_is_still_skipped(tmp_path: Path) -> None:
    # all columns present and blank: the empty-row filter's actual job
    csv_file = write_ragged_csv(tmp_path, "input,target\n2+2,4\n,\n3+3,6\n")

    dataset = csv_dataset(csv_file)

    assert len(dataset) == 2
    assert [sample.input for sample in dataset] == ["2+2", "3+3"]


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
