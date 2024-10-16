import csv
from io import TextIOWrapper
from pathlib import Path
from typing import Any

from inspect_ai._util.file import file
from inspect_ai.dataset._sources.util import resolve_sample_files

from .._dataset import (
    Dataset,
    DatasetReader,
    FieldSpec,
    MemoryDataset,
    RecordToSample,
)
from .._util import data_to_samples, record_to_sample_fn


def csv_dataset(
    csv_file: str,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    limit: int | None = None,
    dialect: str = "unix",
    encoding: str = "utf-8",
    name: str | None = None,
    fs_options: dict[str, Any] = {},
    fieldnames: list[str] | None = None,
    delimiter: str = ",",
) -> Dataset:
    r"""Read dataset from CSV file.

    Args:
        csv_file (str): Path to CSV file. Can be a local filesystem path,
            a path to an S3 bucket (e.g. "s3://my-bucket"), or an HTTPS URL.
            Use `fs_options` to pass arguments through to the `S3FileSystem` constructor.
        sample_fields (FieldSpec | RecordToSample): Method of mapping underlying
            fields in the data source to Sample objects. Pass `None` if the data is already
            stored in `Sample` form (i.e. has "input" and "target" columns.); Pass a
            `FieldSpec` to specify mapping fields by name; Pass a `RecordToSample` to
            handle mapping with a custom function that returns one or more samples.
        auto_id (bool): Assign an auto-incrementing ID for each sample.
        shuffle (bool): Randomly shuffle the dataset order.
        seed: (int | None): Seed used for random shuffle.
        limit (int | None): Limit the number of records to read.
        dialect (str): CSV dialect ("unix", "excel" or"excel-tab"). Defaults to "unix". See https://docs.python.org/3/library/csv.html#dialects-and-formatting-parameters for more details
        encoding (str): Text encoding for file (defaults to "utf-8").
        name (str): Optional name for dataset (for logging). If not specified,
            defaults to the stem of the filename
        fs_options (dict[str, Any]): Optional. Additional arguments to pass through
            to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }`
            if you are accessing a public S3 bucket with no credentials.
        fieldnames (list[str] | None): Optional. A list of fieldnames to use for the CSV.
            If None, the values in the first row of the file will be used as the fieldnames.
            Useful for files without a header.
        delimiter (str): Optional. The delimiter to use when parsing the file. Defaults to ",".

    Returns:
        Dataset read from CSV file.
    """
    # resolve data_to_sample function
    data_to_sample = record_to_sample_fn(sample_fields)

    # read and convert samples
    with file(csv_file, "r", encoding=encoding, fs_options=fs_options) as f:
        # filter out rows with empty values
        valid_data = [
            data
            for data in csv_dataset_reader(f, dialect, fieldnames, delimiter)
            if data and any(value.strip() for value in data.values())
        ]
        name = name if name else Path(csv_file).stem
        dataset = MemoryDataset(
            samples=data_to_samples(valid_data, data_to_sample, auto_id),
            name=name,
            location=csv_file,
        )

        # resolve relative file paths
        resolve_sample_files(dataset)

        # shuffle if requested
        if shuffle:
            dataset.shuffle(seed=seed)

        # limit if requested
        if limit:
            return dataset[0:limit]

        return dataset


def csv_dataset_reader(
    file: TextIOWrapper,
    dialect: str = "unix",
    fieldnames: list[str] | None = None,
    delimiter: str = ",",
) -> DatasetReader:
    return csv.DictReader(
        file, dialect=dialect, fieldnames=fieldnames, delimiter=delimiter
    )
