"""PROTOTYPE: tamper-evident eval logs (add-only store writes and validation)."""

from ._store import AddOnlyStoreError, StoreLocation
from ._writer import (
    EvalRecordWriter,
    SampleRecordWriter,
    init_sample_record_writer,
    store_boundary,
)

__all__ = [
    "AddOnlyStoreError",
    "EvalRecordWriter",
    "SampleRecordWriter",
    "StoreLocation",
    "init_sample_record_writer",
    "store_boundary",
]
