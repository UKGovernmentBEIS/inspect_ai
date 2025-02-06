import json
import os
from io import TextIOWrapper
from pathlib import Path
from typing import Any, cast

import jsonlines

from inspect_ai._util.file import file

from .._dataset import (
    Dataset,
    DatasetReader,
    FieldSpec,
    MemoryDataset,
    RecordToSample,
)
from .._util import data_to_samples, record_to_sample_fn
from .util import resolve_sample_files


def json_dataset(
    json_file: str,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    shuffle_choices: bool | int | None = None,
    limit: int | None = None,
    encoding: str = "utf-8",
    name: str | None = None,
    fs_options: dict[str, Any] = {},
) -> Dataset:
    r"""Read dataset from a JSON file.

    Read a dataset from a JSON file containing an array of objects, or
    from a JSON Lines file containing one object per line. These objects may
    already be formatted as `Sample` instances, or may require some mapping using
    the `sample_fields` argument.

    Args:
      json_file: Path to JSON file. Can be a local filesystem path or
        a path to an S3 bucket (e.g. "s3://my-bucket"). Use `fs_options`
        to pass arguments through to the `S3FileSystem` constructor.
      sample_fields: Method of mapping underlying
        fields in the data source to `Sample` objects. Pass `None` if the data is already
        stored in `Sample` form (i.e. object with "input" and "target" fields); Pass a
        `FieldSpec` to specify mapping fields by name; Pass a `RecordToSample` to
        handle mapping with a custom function that returns one or more samples.
      auto_id: Assign an auto-incrementing ID for each sample.
      shuffle: Randomly shuffle the dataset order.
      seed: Seed used for random shuffle.
      shuffle_choices: Whether to shuffle the choices. If an int is passed, this will be used as the seed when shuffling.
      limit: Limit the number of records to read.
      encoding: Text encoding for file (defaults to "utf-8").
      name: Optional name for dataset (for logging). If not specified,
        defaults to the stem of the filename.
      fs_options: Optional. Additional arguments to pass through
        to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }`
        if you are accessing a public S3 bucket with no credentials.

    Returns:
        Dataset read from JSON file.
    """
    # resolve data_to_sample function
    data_to_sample = record_to_sample_fn(sample_fields)

    # pick the right reader for the file extension
    dataset_reader = (
        jsonlines_dataset_reader
        if json_file.lower().endswith(".jsonl")
        else json_dataset_reader
    )

    # read and convert samples
    with file(json_file, "r", encoding=encoding, fs_options=fs_options) as f:
        name = name if name else Path(json_file).stem
        dataset = MemoryDataset(
            samples=data_to_samples(dataset_reader(f), data_to_sample, auto_id),
            name=name,
            location=os.path.abspath(json_file),
        )

        # resolve relative file paths
        resolve_sample_files(dataset)

        # shuffle if requested
        if shuffle:
            dataset.shuffle(seed=seed)

        # shuffle choices, if requested
        if isinstance(shuffle_choices, int):
            dataset.shuffle_choices(seed=shuffle_choices)
        elif shuffle_choices is True:
            dataset.shuffle_choices()

        # limit if requested
        if limit:
            return dataset[0:limit]

    return dataset


def jsonlines_dataset_reader(file: TextIOWrapper) -> DatasetReader:
    jsonlines_reader = jsonlines.Reader(file)
    return jsonlines_reader.iter(type=dict)


def json_dataset_reader(file: TextIOWrapper) -> DatasetReader:
    data = cast(list[dict[str, Any]], json.load(file))
    return iter(data)
