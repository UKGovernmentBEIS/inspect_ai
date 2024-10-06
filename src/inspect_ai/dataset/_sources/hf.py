# mypy: disable-error-code="unused-ignore"

from pathlib import Path
from typing import Any

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from .._dataset import (
    Dataset,
    FieldSpec,
    MemoryDataset,
    RecordToSample,
)
from .._util import data_to_samples, record_to_sample_fn


def hf_dataset(
    path: str,
    name: str | None = None,
    data_dir: str | None = None,
    split: str | None = None,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    limit: int | None = None,
    trust: bool = False,
    **kwargs: Any,
) -> Dataset:
    """Datasets read using the Hugging Face `datasets` package.

    The `hf_dataset` function supports reading datasets using the Hugging Face
    `datasets` package, including remote datasets on Hugging Face Hub.

    Args:
        path (str): Path or name of the dataset. Depending on path, the dataset
          builder that is used comes from a generic dataset script (JSON, CSV,
          Parquet, text etc.) or from the dataset script (a python file) inside
          the dataset directory.
        name (str | None): Name of the dataset configuration.
        data_dir (str | None): data_dir of the dataset configuration
          to read data from.
        split (str | None): Which split of the data to load.
        sample_fields (FieldSpec | RecordToSample): Method of mapping underlying
          fields in the data source to Sample objects. Pass `None` if the data is already
          stored in `Sample` form (i.e. has "input" and "target" columns.); Pass a
          `FieldSpec` to specify mapping fields by name; Pass a `RecordToSample` to
          handle mapping with a custom function that returns one or more samples.
        auto_id (bool): Assign an auto-incrementing ID for each sample.
        shuffle (bool): Randomly shuffle the dataset order.
        seed: (int | None): Seed used for random shuffle.
        limit (int | None): Limit the number of records to read.
        trust (bool): Whether or not to allow for datasets defined on the Hub
          using a dataset script. This option should only be set to True for
          repositories you trust and in which you have read the code, as it
          will execute code present on the Hub on your local machine.
        **kwargs (dict[str, Any]): Additional arguments to pass through to the
          `load_dataset` function of the `datasets` package.

    Returns:
        Dataset read from Hugging Face
    """
    # ensure we have the datasets package (>= v2.16, which supports trust_remote_code)
    FEATURE = "Hugging Face Datasets"
    PACKAGE = "datasets"
    VERSION = "2.16.0"
    try:
        import datasets  # type: ignore
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])
    verify_required_version(FEATURE, PACKAGE, VERSION)

    # resolve data_to_sample function
    data_to_sample = record_to_sample_fn(sample_fields)

    # load the dataset as a list of dicts
    dataset = datasets.load_dataset(  # type: ignore
        path=path,
        name=name,
        data_dir=data_dir,
        split=split,
        trust_remote_code=trust,
        **kwargs,
    )

    # shuffle if requested
    if shuffle:
        dataset = dataset.shuffle(seed=seed)

    # limit if requested
    if limit:
        dataset = dataset.select(range(limit))

    # return the dataset
    return MemoryDataset(
        samples=data_to_samples(dataset.to_list(), data_to_sample, auto_id),
        name=Path(path).stem if Path(path).exists() else path,
        location=path,
    )
