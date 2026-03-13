"""Disk-paged sample store for large datasets."""

import os
import pickle
import sys
import tempfile
from typing import Any, BinaryIO, Sequence, cast

from inspect_ai.dataset import Dataset, Sample


class DiskSampleStore:
    """Stores samples on disk, providing indexed access via pickle."""

    def __init__(self, samples: Sequence[Sample]) -> None:
        self._len = len(samples)
        fd, self._path = tempfile.mkstemp(suffix=".pkl")
        try:
            with os.fdopen(fd, "wb") as f:
                self._offsets: list[int] = []
                for sample in samples:
                    self._offsets.append(f.tell())
                    pickle.dump(sample, f)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(self._path)
            except OSError:
                pass
            raise
        self._reader: BinaryIO | None = None

    def __len__(self) -> int:
        return self._len

    def __getitem__(self, index: int) -> Sample:
        if self._reader is None:
            self._reader = open(self._path, "rb")
        self._reader.seek(self._offsets[index])
        return cast(Sample, pickle.load(self._reader))  # noqa: S301

    def close(self) -> None:
        try:
            if self._reader is not None:
                self._reader.close()
                self._reader = None
            os.unlink(self._path)
        except Exception:
            pass


def deep_getsizeof(obj: Any, seen: set[int] | None = None) -> int:
    """Recursively measure total memory of an object graph."""
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        size += sum(
            deep_getsizeof(k, seen) + deep_getsizeof(v, seen) for k, v in obj.items()
        )
    elif isinstance(obj, (list, tuple, set, frozenset)):
        size += sum(deep_getsizeof(i, seen) for i in obj)
    elif hasattr(obj, "__dict__"):
        size += deep_getsizeof(obj.__dict__, seen)
    elif hasattr(obj, "__slots__"):
        size += sum(
            deep_getsizeof(getattr(obj, s), seen)
            for s in obj.__slots__
            if hasattr(obj, s)
        )
    return size


def maybe_page_to_disk(
    dataset: Dataset, max_dataset_memory_mb: int | None
) -> Dataset | DiskSampleStore:
    """Page dataset to disk if estimated memory exceeds budget."""
    if max_dataset_memory_mb is None or len(dataset) == 0:
        return dataset

    # Probe a few samples to estimate per-sample memory
    probe_count = min(10, len(dataset))
    total_bytes = sum(deep_getsizeof(dataset[i]) for i in range(probe_count))
    avg_bytes = total_bytes / probe_count
    estimated_memory = avg_bytes * len(dataset)
    budget_bytes = max_dataset_memory_mb * 1024 * 1024

    if estimated_memory > budget_bytes:
        return DiskSampleStore(dataset)
    return dataset
