from pathlib import Path
from typing import Callable

from .._dataset import Dataset, FieldSpec, MemoryDataset, RecordToSample
from .csv import csv_dataset
from .json import json_dataset

EXAMPLES_PATH = Path(__file__).parent.parent / "_examples"


def example_dataset(
    name: str,
    sample_fields: FieldSpec | RecordToSample | None = None,
) -> Dataset:
    """Read a dataset from inspect_ai package examples.

    This is primarily used for sharing runnable example
    snippets that don't need to read an external dataset.

    Args:
      name (str): Example dataset name. One of 'security_guide', 'theory_of_mind', 'popularity', or 'biology_qa'.
      sample_fields (FieldSpec | RecordToSample): Method of mapping underlying
        fields in the data source to `Sample` objects. Pass `None` if the data is already
        stored in `Sample` form (i.e. object with "input" and "target" fields); Pass a
        `FieldSpec` to specify mapping fields by name; Pass a `RecordToSample` to
        handle mapping with a custom function that returns one or more samples.


    Returns:
      Dataset read from example file.
    """

    def get_dataset(
        file_path: Path,
        dataset_func: Callable[[str, FieldSpec | RecordToSample | None], Dataset],
    ) -> Dataset | None:
        if file_path.exists():
            return dataset_func(str(file_path), sample_fields)
        return None

    json_file = EXAMPLES_PATH / f"{name}.jsonl"
    csv_file = EXAMPLES_PATH / f"{name}.csv"

    dataset = get_dataset(json_file, json_dataset) or get_dataset(csv_file, csv_dataset)

    if dataset is None:
        available_datasets = [
            file.stem for file in EXAMPLES_PATH.iterdir() if file.is_file()
        ]
        raise ValueError(
            f"Sample dataset {name} not found. Available datasets: {available_datasets}"
        )

    return MemoryDataset(samples=list(dataset), name=name, location=f"example://{name}")
