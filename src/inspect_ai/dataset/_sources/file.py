import os
from typing import Any

from .._dataset import (
    Dataset,
    FieldSpec,
    RecordToSample,
)
from .csv import csv_dataset
from .json import json_dataset


def file_dataset(
    file: str,
    sample_fields: FieldSpec | RecordToSample | None = None,
    dialect: str = "unix",
    encoding: str = "utf-8",
    name: str | None = None,
    fs_options: dict[str, Any] = {},
) -> Dataset:
    """Dataset read from a JSON or CSV file.

    The `file_dataset` function supports reading from CSV and JSON files
    (and automatically delegates to the appropriate function to do so)

    Args:
        file (str): Path to JSON or CSV file. Can be a local filesystem path or
            a path to an S3 bucket (e.g. "s3://my-bucket"). Use `fs_options`
            to pass arguments through to the `S3FileSystem` constructor.
        sample_fields (FieldSpec | RecordToSample): Method of mapping underlying
            fields in the data source to Sample objects. Pass `None` if the data is already
            stored in `Sample` form (i.e. has "input" and "target" columns.); Pass a
            `FieldSpec` to specify mapping fields by name; Pass a `RecordToSample` to
            handle mapping with a custom function that returns one or more samples.
        dialect (str): CSV dialect ("unix" or "excel", defaults to "unix"). Only
            applies to reading CSV files.
        encoding (str): Text encoding for file (defaults to "utf-8").
        name (str): Optional name for dataset (for logging). If not specified,
            defaults to the stem of the filename
        fs_options (dict[str, Any]): Optional. Additional arguments to pass through
            to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }`
            if you are accessing a public S3 bucket with no credentials.

    Returns:
        Dataset read from JSON or CSV file.
    """
    ext = os.path.splitext(file)[1].lower()

    match ext:
        case ".json" | ".jsonl":
            return json_dataset(
                json_file=file,
                sample_fields=sample_fields,
                encoding=encoding,
                name=name,
                fs_options=fs_options,
            )
        case ".csv":
            return csv_dataset(
                csv_file=file,
                sample_fields=sample_fields,
                dialect=dialect,
                encoding=encoding,
                name=name,
                fs_options=fs_options,
            )
        case _:
            raise ValueError(f"No dataset reader for file with extension {ext}")
