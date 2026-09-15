import csv as csv_module
import inspect
import json as json_module
import os
from pathlib import Path
from typing import Callable, Type, TypeVar
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
from inspect_ai.dataset._util import read_choices
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.util import (
    ArchiveSnapshots,
    CheckpointConfig,
    CheckpointSampleConfig,
    Manual,
    SandboxSnapshotConfig,
)
from inspect_ai.util._checkpoint.config import merge_checkpoint_configs

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
        (".tsv", "csv_dataset", "csv_file"),
        (".tab", "csv_dataset", "csv_file"),
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


@pytest.mark.parametrize(
    ("suffix", "delimiter"),
    [(".csv", None), (".tsv", "\t"), (".tab", "\t")],
)
def test_file_dataset_delimiter_by_extension(
    suffix: str, delimiter: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_reader = Mock(return_value=object())
    monkeypatch.setattr("inspect_ai.dataset._sources.file.csv_dataset", mock_reader)

    file_dataset(f"dataset{suffix}", fieldnames=["input", "target"])

    kwargs = mock_reader.call_args.kwargs
    assert kwargs["delimiter"] == delimiter
    assert kwargs["fieldnames"] == ["input", "target"]


@pytest.mark.parametrize("suffix", [".tsv", ".tab", ".TSV"])
def test_file_dataset_reads_tab_delimited(tmp_path: Path, suffix: str) -> None:
    tsv_file = tmp_path / f"data{suffix}"
    tsv_file.write_text('input\ttarget\n"hello, world"\tA\nfoo\tbar\n')

    dataset = file_dataset(str(tsv_file))

    assert len(dataset) == 2
    assert dataset[0].input == "hello, world"
    assert dataset[0].target == "A"
    assert dataset[1].input == "foo"


def test_file_dataset_tab_delimited_without_header(tmp_path: Path) -> None:
    tsv_file = tmp_path / "data.tsv"
    tsv_file.write_text("hello\tA\n")

    dataset = file_dataset(str(tsv_file), fieldnames=["input", "target"])

    assert len(dataset) == 1
    assert dataset[0].input == "hello"
    assert dataset[0].target == "A"


def test_file_dataset_csv_honors_dialect_delimiter(tmp_path: Path) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("input\ttarget\nhello\tA\n")

    dataset = file_dataset(str(csv_file), dialect="excel-tab")

    assert len(dataset) == 1
    assert dataset[0].input == "hello"
    assert dataset[0].target == "A"


def test_file_dataset_has_no_delimiter_parameter() -> None:
    # custom delimiters belong to csv_dataset(); file_dataset() only
    # defaults by extension
    assert "delimiter" not in inspect.signature(file_dataset).parameters


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


def test_dataset_empty_string_files_not_resolved(tmp_path: Path) -> None:
    # empty-string files/setup values are literal contents, and must not be
    # resolved against the dataset's parent directory (which exists, so would
    # replace the value with a directory path and later copy that whole
    # directory into the sandbox)
    dataset_file = tmp_path / "dataset.jsonl"
    dataset_file.write_text(
        json_module.dumps(
            {
                "input": "Say hello",
                "target": "hello",
                "files": {"submission/report.md": ""},
                "setup": "",
                "sandbox": ["docker", ""],
            }
        )
        + "\n"
    )
    sample = json_dataset(dataset_file.as_posix())[0]
    assert sample.files == {"submission/report.md": ""}
    assert sample.setup == ""
    assert sample.sandbox is not None and sample.sandbox.config == ""


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


def test_dataset_nan_fields_treated_as_missing() -> None:
    from inspect_ai.dataset._util import record_to_sample_fn

    rec2sample = record_to_sample_fn(FieldSpec())

    # NaN input should raise ValueError("No input in dataset")
    with pytest.raises(ValueError, match="No input in dataset"):
        rec2sample({"input": float("nan"), "target": "4"})

    # NaN choices, setup, sandbox, files, metadata, checkpoint should be treated
    # as missing (None). The HuggingFace fake loader path shares this mapper.
    sample = rec2sample(
        {
            "input": "x",
            "target": "y",
            "choices": float("nan"),
            "setup": float("nan"),
            "sandbox": float("nan"),
            "files": float("nan"),
            "metadata": float("nan"),
            "checkpoint": float("nan"),
        }
    )
    assert not isinstance(sample, list)
    assert sample.choices is None, f"expected None for choices, got {sample.choices!r}"
    assert sample.setup is None, f"expected None for setup, got {sample.setup!r}"
    assert sample.sandbox is None, f"expected None for sandbox, got {sample.sandbox!r}"
    assert sample.files is None, f"expected None for files, got {sample.files!r}"
    assert sample.metadata is None, (
        f"expected None for metadata, got {sample.metadata!r}"
    )
    assert sample.checkpoint is None, (
        f"expected None for checkpoint, got {sample.checkpoint!r}"
    )


def _write_checkpoint_records(path: Path, records: list[dict]) -> None:
    if path.suffix == ".jsonl":
        path.write_text("".join(json_module.dumps(r) + "\n" for r in records))
    else:
        path.write_text(json_module.dumps(records))


@pytest.mark.parametrize(
    "loader,suffix",
    [
        (json_dataset, ".json"),
        (json_dataset, ".jsonl"),
        (file_dataset, ".json"),
        (file_dataset, ".jsonl"),
    ],
)
def test_dataset_checkpoint_settings_preserved(
    tmp_path: Path, loader: Callable[[str], Dataset], suffix: str
) -> None:
    # A serialized sample's checkpoint settings must survive default loading, so
    # the real merge sees the sample's zero and empty-list overrides instead of
    # the task defaults.
    sample = Sample(
        input="Run the sample task",
        id="s1",
        metadata={"phase": "train"},
        checkpoint=CheckpointSampleConfig(
            sandbox_paths={
                "default": SandboxSnapshotConfig(paths=[], strategy=ArchiveSnapshots())
            },
            max_consecutive_failures=0,
        ),
    )
    text = sample.model_dump_json()
    dataset_file = tmp_path / f"dataset{suffix}"
    dataset_file.write_text(text + ("\n" if suffix == ".jsonl" else ""))

    loaded = loader(str(dataset_file))[0]
    direct = Sample.model_validate_json(text)
    assert loaded.checkpoint == direct.checkpoint
    assert loaded.id == "s1"
    assert loaded.metadata == {"phase": "train"}

    resolved = merge_checkpoint_configs(
        task=CheckpointConfig(
            trigger=Manual(),
            sandbox_paths={"default": ["/workspace"]},
            max_consecutive_failures=7,
        ),
        sample=loaded.checkpoint,
    )
    assert resolved is not None
    assert resolved.max_consecutive_failures == 0
    assert resolved.sandbox_paths == {"default": []}
    assert resolved.sandbox_strategy_config("default") == ArchiveSnapshots()

    # A sample-only config must not enable checkpointing.
    assert merge_checkpoint_configs(task=None, sample=loaded.checkpoint) is None


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
@pytest.mark.parametrize(
    "checkpoint",
    [
        pytest.param({}, id="empty-object"),
        pytest.param({"sandbox_paths": {}}, id="empty-sandbox-paths"),
        pytest.param(
            {"max_consecutive_failures": 0, "sandbox_paths": {}},
            id="zero-and-empty-paths",
        ),
    ],
)
def test_dataset_checkpoint_empty_overrides_preserved(
    tmp_path: Path, suffix: str, checkpoint: dict
) -> None:
    dataset_file = tmp_path / f"dataset{suffix}"
    _write_checkpoint_records(dataset_file, [{"input": "x", "checkpoint": checkpoint}])

    loaded = json_dataset(str(dataset_file))[0]
    assert loaded.checkpoint is not None

    resolved = merge_checkpoint_configs(
        task=CheckpointConfig(
            trigger=Manual(), sandbox_paths={"default": ["/workspace"]}
        ),
        sample=loaded.checkpoint,
    )
    assert resolved is not None
    if "sandbox_paths" in checkpoint:
        assert resolved.sandbox_paths == {}
    else:
        assert resolved.sandbox_paths == {"default": ["/workspace"]}
    if checkpoint.get("max_consecutive_failures") == 0:
        assert resolved.max_consecutive_failures == 0


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
def test_dataset_checkpoint_missing_and_null_are_none(
    tmp_path: Path, suffix: str
) -> None:
    dataset_file = tmp_path / f"dataset{suffix}"
    _write_checkpoint_records(
        dataset_file, [{"input": "x"}, {"input": "x", "checkpoint": None}]
    )

    samples = json_dataset(str(dataset_file))

    assert [sample.checkpoint for sample in samples] == [None, None]


@pytest.mark.parametrize("value", ["not json", "[1, 2]", 5, ["a"]])
def test_dataset_checkpoint_malformed_rejected(value: object) -> None:
    from inspect_ai.dataset._util import record_to_sample_fn

    rec2sample = record_to_sample_fn(FieldSpec())
    with pytest.raises(ValueError, match="checkpoint"):
        rec2sample({"input": "x", "checkpoint": value})


@pytest.mark.parametrize(
    "checkpoint",
    [
        pytest.param({"max_consecutive_failures": "x"}, id="invalid-failure-count"),
        pytest.param(
            {"sandbox_paths": {"default": {"strategy": {"name": "nope"}}}},
            id="unknown-snapshot-strategy",
        ),
    ],
)
def test_dataset_checkpoint_invalid_known_fields_rejected(
    tmp_path: Path, checkpoint: dict
) -> None:
    dataset_file = tmp_path / "data.jsonl"
    _write_checkpoint_records(dataset_file, [{"input": "x", "checkpoint": checkpoint}])

    with pytest.raises(ValueError, match="checkpoint"):
        json_dataset(str(dataset_file))


def test_dataset_checkpoint_field_spec_mapping(tmp_path: Path) -> None:
    dataset_file = tmp_path / "data.jsonl"
    dataset_file.write_text(
        json_module.dumps(
            {
                "question": "2+2",
                "answer": "4",
                # an invalid default checkpoint key must not be consumed once
                # the FieldSpec remaps checkpoint to "ckpt"
                "checkpoint": "not-valid",
                "ckpt": {"max_consecutive_failures": 0},
            }
        )
        + "\n"
    )

    dataset = json_dataset(
        str(dataset_file),
        sample_fields=FieldSpec(input="question", target="answer", checkpoint="ckpt"),
    )

    assert dataset[0].input == "2+2"
    assert dataset[0].target == "4"
    assert dataset[0].checkpoint == CheckpointSampleConfig(max_consecutive_failures=0)


def test_dataset_checkpoint_custom_converter_owns_conversion(tmp_path: Path) -> None:
    dataset_file = tmp_path / "data.json"
    dataset_file.write_text(
        json_module.dumps([{"input": "x", "target": "y", "checkpoint": "not-valid"}])
    )

    def to_sample(_record: dict) -> Sample:
        # A custom converter owns conversion; the loader must neither parse nor
        # reject the record's invalid checkpoint field.
        return Sample(
            input="chosen",
            checkpoint=CheckpointSampleConfig(max_consecutive_failures=0),
        )

    dataset = json_dataset(str(dataset_file), sample_fields=to_sample)

    assert dataset[0].input == "chosen"
    assert dataset[0].checkpoint == CheckpointSampleConfig(max_consecutive_failures=0)


def test_dataset_checkpoint_merge_precedence_preserved() -> None:
    from inspect_ai.dataset._util import record_to_sample_fn

    loaded = record_to_sample_fn(FieldSpec())(
        {"input": "x", "checkpoint": {"max_consecutive_failures": 3}}
    )
    assert not isinstance(loaded, list)

    eval_wins = merge_checkpoint_configs(
        task=CheckpointConfig(trigger=Manual(), max_consecutive_failures=7),
        sample=loaded.checkpoint,
        eval_=CheckpointConfig(max_consecutive_failures=9),
    )
    assert eval_wins is not None and eval_wins.max_consecutive_failures == 9

    sample_wins = merge_checkpoint_configs(
        task=CheckpointConfig(trigger=Manual(), max_consecutive_failures=7),
        sample=loaded.checkpoint,
    )
    assert sample_wins is not None and sample_wins.max_consecutive_failures == 3


def test_csv_checkpoint_json_object_string(tmp_path: Path) -> None:
    csv_file = tmp_path / "data.csv"
    with csv_file.open("w", newline="") as f:
        writer = csv_module.writer(f)
        writer.writerow(["input", "target", "checkpoint"])
        writer.writerow(
            [
                "2+2",
                "4",
                json_module.dumps(
                    {"max_consecutive_failures": 0, "sandbox_paths": {"default": []}}
                ),
            ]
        )

    sample = csv_dataset(str(csv_file))[0]

    assert sample.checkpoint is not None
    assert sample.checkpoint.max_consecutive_failures == 0
    assert sample.checkpoint.sandbox_paths == {"default": []}


def test_csv_empty_checkpoint_cell_is_missing(tmp_path: Path) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("input,target,checkpoint\n2+2,4,\n")

    assert csv_dataset(str(csv_file))[0].checkpoint is None


def test_csv_null_checkpoint_cell_is_missing(tmp_path: Path) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("input,target,checkpoint\n2+2,4,null\n")

    assert csv_dataset(str(csv_file))[0].checkpoint is None


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


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("fieldnames", [None, ["input", "target"]])
def test_csv_utf8_with_or_without_bom(
    tmp_path: Path, encoding: str, fieldnames: list[str] | None
) -> None:
    csv_file = tmp_path / "data.csv"
    body = "café \ufeff text,résumé\r\n"
    if fieldnames is None:
        body = "input,target\r\n" + body
    csv_file.write_bytes(body.encode(encoding))

    dataset = csv_dataset(str(csv_file), fieldnames=fieldnames)

    assert len(dataset) == 1
    assert dataset[0].input == "café \ufeff text"
    assert dataset[0].target == "résumé"


@pytest.mark.parametrize("encoding", ["utf-16", "cp1252"])
def test_csv_explicit_encoding(tmp_path: Path, encoding: str) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_bytes("input,target\r\ncafé,résumé\r\n".encode(encoding))

    dataset = csv_dataset(str(csv_file), encoding=encoding)

    assert len(dataset) == 1
    assert dataset[0].input == "café"
    assert dataset[0].target == "résumé"


def test_csv_explicit_utf8_preserves_bom(tmp_path: Path) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_bytes("café,résumé\r\n".encode("utf-8-sig"))

    dataset = csv_dataset(
        str(csv_file), encoding="utf-8", fieldnames=["input", "target"]
    )

    assert len(dataset) == 1
    assert dataset[0].input == "\ufeffcafé"
    assert dataset[0].target == "résumé"


def write_ragged_csv(tmp_path: Path, body: str) -> str:
    path = tmp_path / "data.csv"
    path.write_text(body, newline="")
    return str(path)


@pytest.mark.parametrize("dialect", ["unix", "excel", "excel-tab"])
@pytest.mark.parametrize("fieldnames", [None, ["input", "target"]])
def test_csv_dialect_delimiter(
    tmp_path: Path, dialect: str, fieldnames: list[str] | None
) -> None:
    delimiter = csv_module.get_dialect(dialect).delimiter
    body = f'"hello, world"{delimiter}A\n'
    if fieldnames is None:
        body = f"input{delimiter}target\n" + body

    dataset = csv_dataset(
        write_ragged_csv(tmp_path, body), dialect=dialect, fieldnames=fieldnames
    )

    assert len(dataset) == 1
    assert dataset[0].input == "hello, world"
    assert dataset[0].target == "A"


def test_csv_registered_dialect_delimiter(tmp_path: Path) -> None:
    csv_module.register_dialect("inspect-test-semicolon", "unix", delimiter=";")
    try:
        dataset = csv_dataset(
            write_ragged_csv(tmp_path, 'input;target\n"hello; world";A\n'),
            dialect="inspect-test-semicolon",
        )
        assert len(dataset) == 1
        assert dataset[0].input == "hello; world"
        assert dataset[0].target == "A"
    finally:
        csv_module.unregister_dialect("inspect-test-semicolon")


@pytest.mark.parametrize("dialect,delimiter", [("excel-tab", ","), ("unix", "\t")])
def test_csv_delimiter_overrides_dialect(
    tmp_path: Path, dialect: str, delimiter: str
) -> None:
    dataset = csv_dataset(
        write_ragged_csv(tmp_path, f"input{delimiter}target\nhello{delimiter}A\n"),
        dialect=dialect,
        delimiter=delimiter,
    )

    assert len(dataset) == 1
    assert dataset[0].input == "hello"
    assert dataset[0].target == "A"


def test_csv_short_blank_row_names_the_line(tmp_path: Path) -> None:
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
    csv_file = write_ragged_csv(tmp_path, "input,target,id\n2+2,4\n")

    with pytest.raises(ValueError, match="No value for: id"):
        csv_dataset(csv_file)


def test_csv_long_row_with_content_is_not_silently_absorbed(tmp_path: Path) -> None:
    # DictReader collects a long row's extras under the restkey
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
    # DictReader skips blank lines and a quoted field can span several, so a
    # count of yielded rows drifts from the physical line. This one is line 7.
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


def test_read_choices_drops_empty_entries() -> None:
    assert read_choices("Paris,London,") == ["Paris", "London"]
    assert read_choices("Paris,,London") == ["Paris", "London"]
    assert read_choices("Paris, London") == ["Paris", "London"]
    assert read_choices("Paris London") == ["Paris", "London"]
    assert read_choices(",,") == []
    assert read_choices(None) is None
    assert read_choices(["Paris", "", "London"]) == ["Paris", "London"]
    assert read_choices(["Paris", " ", "London"]) == ["Paris", "London"]
