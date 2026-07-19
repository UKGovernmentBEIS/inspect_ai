# mypy: disable-error-code="unused-ignore"

import logging
import os
from pathlib import Path
from typing import Any, Callable, TypeVar

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.file import safe_filename
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.version import verify_required_version

from .._dataset import (
    Dataset,
    FieldSpec,
    MemoryDataset,
    RecordToSample,
)
from .._util import data_to_samples, record_to_sample_fn, shuffle_choices_if_requested

logger = logging.getLogger(__name__)

# Retry policy for transient Hugging Face failures. The HF rate-limit
# window is 5 minutes, so cap individual sleeps there.
_HF_RATE_LIMIT_WINDOW_SECS = 5 * 60
_INITIAL_WAIT_SECS = 60
_MAX_TRIES_DEFAULT = 3
_MAX_TRIES_CI = 5
_TRANSIENT_HTTP_STATUSES = {429, 502}


def _should_retry_hf_error(err: BaseException) -> bool:
    """Return True if `err` is a transient HF failure worth retrying."""
    try:
        from huggingface_hub.errors import HfHubHTTPError, LocalEntryNotFoundError

        if isinstance(err, LocalEntryNotFoundError):
            return True
        if isinstance(err, HfHubHTTPError):
            return err.response.status_code in _TRANSIENT_HTTP_STATUSES
    except ImportError:
        pass

    try:
        from datasets.exceptions import DatasetGenerationError  # type: ignore

        if isinstance(err, DatasetGenerationError):
            return True
    except ImportError:
        pass

    if isinstance(err, FileNotFoundError):
        msg = str(err)
        return (
            "An error happened while trying to locate the file on the Hub" in msg
            or "on the Hugging Face Hub either" in msg
        )

    if isinstance(err, ValueError):
        return "Couldn't find cache for" in str(err)

    try:
        from requests.exceptions import ReadTimeout

        if isinstance(err, ReadTimeout):
            return "huggingface.co" in str(err)
    except ImportError:
        pass

    return False


def _hf_max_tries() -> int:
    return _MAX_TRIES_CI if os.getenv("CI") else _MAX_TRIES_DEFAULT


_T = TypeVar("_T")


def _call_with_hf_retry(fn: Callable[[], _T]) -> _T:
    import tenacity.nap
    from tenacity import (
        RetryCallState,
        Retrying,
        retry_if_exception,
        stop_after_attempt,
        wait_random_exponential,
    )

    def log_before_sleep(rs: RetryCallState) -> None:
        if rs.outcome is None:
            return
        ex = rs.outcome.exception()
        if ex is None:
            return
        logger.warning(
            "Hugging Face request failed with %s (attempt %d); retrying in %.1fs",
            type(ex).__name__,
            rs.attempt_number,
            rs.upcoming_sleep,
        )

    retrier = Retrying(
        sleep=tenacity.nap.sleep,
        retry=retry_if_exception(_should_retry_hf_error),
        wait=wait_random_exponential(
            multiplier=_INITIAL_WAIT_SECS, max=_HF_RATE_LIMIT_WINDOW_SECS
        ),
        stop=stop_after_attempt(_hf_max_tries()),
        before_sleep=log_before_sleep,
        reraise=True,
    )
    return retrier(fn)


def hf_dataset(
    path: str,
    split: str,
    name: str | None = None,
    data_dir: str | None = None,
    revision: str | None = None,
    sample_fields: FieldSpec | RecordToSample | None = None,
    auto_id: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    shuffle_choices: bool | int | None = None,
    limit: int | None = None,
    trust: bool = False,
    cached: bool = True,
    retry: bool = True,
    **kwargs: Any,
) -> Dataset:
    """Datasets read using the Hugging Face `datasets` package.

    The `hf_dataset` function supports reading datasets using the Hugging Face
    `datasets` package, including remote datasets on Hugging Face Hub.

    Args:
      path: Path or name of the dataset. Depending on path, the dataset
        builder that is used comes from a generic dataset script (JSON, CSV,
        Parquet, text etc.) or from the dataset script (a python file) inside
        the dataset directory.
      split: Which split of the data to load.
      name: Name of the dataset configuration.
      data_dir: data_dir of the dataset configuration
        to read data from.
      revision: Specific revision to load (e.g. "main", a branch
        name, or a specific commit SHA). When using `revision` the `cached` option
        is ignored and datasets are revalidated on Hugging Face before loading.
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
      trust: Whether or not to allow for datasets defined on the Hub
        using a dataset script. This option should only be set to True for
        repositories you trust and in which you have read the code, as it
        will execute code present on the Hub on your local machine.
      cached: By default, datasets are read once from HuggingFace
        Hub and then cached for future reads. Pass `cached=False` to force
        re-reading the dataset from Hugging Face. Ignored when the `revision`
        option is specified.
      retry: Retry transient Hugging Face errors (rate limits, timeouts,
        Hub-unreachable cache misses) with exponential backoff. Pass
        `False` to disable.
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

    # generate a unique cache dir for this dataset (revision must be part of
    # the key so that loading a pinned revision does not poison the cache for
    # later default-revision loads, and vice versa)
    dataset_hash = mm3_hash(f"{path}{name}{data_dir}{split}{revision}{kwargs}")
    datasets_cache_dir = inspect_cache_dir("hf_datasets")
    dataset_cache_dir = os.path.join(
        datasets_cache_dir, f"{safe_filename(path)}-{dataset_hash}"
    )
    if os.path.exists(dataset_cache_dir) and cached and revision is None:
        dataset = datasets.load_from_disk(dataset_cache_dir)
    else:

        def _load() -> Any:
            print(f"Loading dataset {path} from Hugging Face...")
            return datasets.load_dataset(  # type: ignore
                path=path,
                name=name,
                data_dir=data_dir,
                split=split,
                revision=revision,
                trust_remote_code=trust,
                **kwargs,
            )

        dataset = _call_with_hf_retry(_load) if retry else _load()
        dataset.save_to_disk(dataset_cache_dir)

    # Assigning auto ids once shuffling is involved needs care: an id must
    # track its *record* (mirroring csv/json), not the record's shuffled
    # position (#4459). A custom RecordToSample may emit multiple samples per
    # record, so there an id depends on every preceding record's sample count
    # and can only be assigned against the full unshuffled order -- forcing us
    # to materialize the split and shuffle in memory. For the common case
    # (sample_fields is None or a FieldSpec, a 1:1 record->sample mapping) we
    # instead tag each row with its original index before shuffling and recover
    # the id afterwards, keeping HF's lazy shuffle(seed).select(limit) ordering
    # (and materializing only `limit` rows) intact.
    custom_mapping = sample_fields is not None and not isinstance(
        sample_fields, FieldSpec
    )
    materialize_for_ids = auto_id and shuffle and custom_mapping

    if materialize_for_ids:
        # assign auto ids over the unshuffled records, then shuffle in memory
        samples = data_to_samples(dataset.to_list(), data_to_sample, auto_id)
    else:
        index_col = "__inspect_auto_id_index__"
        recover_ids = auto_id and shuffle  # implies a 1:1 mapping here
        if recover_ids:
            dataset = dataset.add_column(index_col, list(range(len(dataset))))
        if shuffle:
            dataset = dataset.shuffle(seed=seed)
        if limit:
            dataset = dataset.select(range(limit))
        records = dataset.to_list()
        if recover_ids:
            # pop the tag so it can't leak into sample metadata
            indices = [record.pop(index_col) for record in records]
            samples = data_to_samples(records, data_to_sample, False)
            for sample, index in zip(samples, indices):
                sample.id = index + 1
        else:
            samples = data_to_samples(records, data_to_sample, auto_id)

    memory_dataset: Dataset = MemoryDataset(
        samples=samples,
        name=Path(path).stem if Path(path).exists() else path,
        location=path,
        shuffled=shuffle,
    )

    if materialize_for_ids:
        # ids travel with their records
        memory_dataset.shuffle(seed=seed)

    shuffle_choices_if_requested(memory_dataset, shuffle_choices)

    if materialize_for_ids and limit:
        memory_dataset = memory_dataset[0:limit]

    return memory_dataset
