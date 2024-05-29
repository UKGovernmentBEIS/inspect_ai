from pathlib import Path
from typing import Literal

from .._dataset import Dataset, FieldSpec, MemoryDataset, RecordToSample
from .csv import csv_dataset
from .json import json_dataset

EXAMPLES_PATH = Path(__file__).parent.parent / "_examples"


def example_dataset(
    name: Literal["security_guide", "theory_of_mind", "popularity", "biology_qa"],
    sample_fields: FieldSpec | RecordToSample | None = None,
) -> Dataset:
    """Read a dataset from inspect_ai package examples.

    This is primarily used for sharing runnable example
    snippets that don't need to read an external dataset.

    Args:
      name (Literal["security_guide", "theory_of_mind", "popularity", "biology_qa"]):
         Example dataset name. One of 'security_guide', 'theory_of_mind',
        'popularity', or 'biology_qa'
      sample_fields (SampleFieldSpec | RecordToSample): Method of mapping underlying
        fields in the data source to `Sample` objects. Pass `None` if the data is already
        stored in `Sample` form (i.e. object with "input" and "target" fields); Pass a
        `SampleFieldSpec` to specify mapping fields by name; Pass a `RecordToSample` to
        handle mapping with a custom function.


    Returns:
      Dataset read from example file.
    """
    json_file = (EXAMPLES_PATH / f"{name}.jsonl").as_posix()
    csv_file = (EXAMPLES_PATH / f"{name}.csv").as_posix()
    if not Path(json_file).exists() and Path(csv_file).exists():
        raise ValueError(f"Sample dataset {name} not found.")

    if Path(json_file).exists():
        dataset = json_dataset(
            json_file=json_file,
            sample_fields=sample_fields,
        )
    else:
        dataset = csv_dataset(
            csv_file=csv_file,
            sample_fields=sample_fields,
        )

    return MemoryDataset(samples=list(dataset), name=name, location=f"example://{name}")
