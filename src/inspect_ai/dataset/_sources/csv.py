import csv
from io import TextIOWrapper
from pathlib import Path
from typing import Any, NoReturn, cast

from inspect_ai._util.asyncfiles import is_s3_filename
from inspect_ai._util.file import absolute_file_path, file
from inspect_ai.dataset._sources.util import resolve_sample_files

from .._dataset import (
    Dataset,
    FieldSpec,
    MemoryDataset,
    RecordToSample,
)
from .._util import data_to_samples, record_to_sample_fn, shuffle_choices_if_requested


def _field_count(count: int) -> str:
    return f"{count} field" if count == 1 else f"{count} fields"


def _raise_ragged_row(
    data: dict[str, Any], csv_file: str, line_number: int
) -> NoReturn:
    """Report a row whose field count does not match the header.

    DictReader pads a short row with restval (None) and collects a long row's
    extras under restkey (also None), so one of the two branches always applies
    by the time this is called.
    """
    # the restkey is not a column name, so it is not in the declared key type
    extra_values = cast(dict[str | None, Any], data).get(None)
    if extra_values is not None:
        columns = len(data) - 1
        raise ValueError(
            f"{csv_file} line {line_number} has "
            f"{_field_count(columns + len(extra_values))}, the header has "
            f"{columns}. Unexpected values: {extra_values}."
        )

    missing_fields = [field for field, value in data.items() if value is None]
    raise ValueError(
        f"{csv_file} line {line_number} has "
        f"{_field_count(len(data) - len(missing_fields))}, the header has "
        f"{len(data)}. No value for: {', '.join(missing_fields)}."
    )


def csv_dataset(
    csv_file: str,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    shuffle_choices: bool | int | None = None,
    limit: int | None = None,
    dialect: str = "unix",
    encoding: str = "utf-8",
    name: str | None = None,
    fs_options: dict[str, Any] | None = None,
    fieldnames: list[str] | None = None,
    delimiter: str = ",",
) -> Dataset:
    r"""Read dataset from CSV file.

    Args:
        csv_file: Path to CSV file. Can be a local filesystem path,
            a path to an S3 bucket (e.g. "s3://my-bucket"), or an HTTPS URL.
            Use `fs_options` to pass arguments through to the `S3FileSystem` constructor.
        sample_fields: Method of mapping underlying
            fields in the data source to Sample objects. Pass `None` if the data is already
            stored in `Sample` form (i.e. has "input" and "target" columns.); Pass a
            `FieldSpec` to specify mapping fields by name; Pass a `RecordToSample` to
            handle mapping with a custom function that returns one or more samples.
        auto_id: Assign an auto-incrementing ID for each sample.
        shuffle: Randomly shuffle the dataset order.
        seed: Seed used for random shuffle.
        shuffle_choices: Whether to shuffle the choices. If an int is passed, this will be used as the seed when shuffling.
        limit: Limit the number of records to read.
        dialect: CSV dialect ("unix", "excel" or"excel-tab"). Defaults to "unix". See https://docs.python.org/3/library/csv.html#dialects-and-formatting-parameters for more details
        encoding: Text encoding for file (defaults to "utf-8").
        name: Optional name for dataset (for logging). If not specified,
            defaults to the stem of the filename
        fs_options: Optional. Additional arguments to pass through
            to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }`
            if you are accessing a public S3 bucket with no credentials.
        fieldnames: Optional. A list of fieldnames to use for the CSV.
            If None, the values in the first row of the file will be used as the fieldnames.
            Useful for files without a header.
        delimiter: Optional. The delimiter to use when parsing the file. Defaults to ",".

    Returns:
        Dataset read from CSV file.
    """
    # resolve data_to_sample function
    data_to_sample = record_to_sample_fn(sample_fields)

    # use readahead cache by default for s3
    if fs_options is None and is_s3_filename(csv_file):
        fs_options = dict(default_fill_cache=True, default_cache_type="readahead")

    # read and convert samples
    with file(csv_file, "r", encoding=encoding, fs_options=fs_options or {}) as f:
        # reject ragged rows, filter out rows with empty values
        valid_data = []
        reader = csv_dataset_reader(f, dialect, fieldnames, delimiter)
        for data in reader:
            if not data:
                continue
            # too many fields leaves a None key, too few leaves a None value
            if None in data or None in data.values():
                # line_num is the physical line the reader is on. Counting rows
                # as they come out drifts instead, because DictReader skips
                # blank lines and a quoted field can span several lines.
                _raise_ragged_row(data, csv_file, reader.line_num)
            if any(value.strip() for value in data.values()):
                valid_data.append(data)
        name = name if name else Path(csv_file).stem
        dataset = MemoryDataset(
            samples=data_to_samples(valid_data, data_to_sample, auto_id),
            name=name,
            location=absolute_file_path(csv_file),
        )

        # resolve relative file paths
        resolve_sample_files(dataset)

        # shuffle if requested
        if shuffle:
            dataset.shuffle(seed=seed)

        shuffle_choices_if_requested(dataset, shuffle_choices)

        # limit if requested
        if limit is not None:
            return dataset[0:limit]

        return dataset


def csv_dataset_reader(
    file: TextIOWrapper,
    dialect: str = "unix",
    fieldnames: list[str] | None = None,
    delimiter: str = ",",
) -> "csv.DictReader[str]":
    return csv.DictReader(
        file, dialect=dialect, fieldnames=fieldnames, delimiter=delimiter
    )
