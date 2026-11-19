"""PROTOTYPE: tamper-evident eval logs (add-only store writes and validation)."""

from ._store import ADDONLY_STORE_ENV, AddOnlyStoreError, addonly_store_location
from ._writer import (
    EvalRecordWriter,
    SampleRecordWriter,
    init_sample_record_writer,
    store_boundary,
)

__all__ = [
    "ADDONLY_STORE_ENV",
    "AddOnlyStoreError",
    "EvalRecordWriter",
    "SampleRecordWriter",
    "addonly_store_location",
    "init_sample_record_writer",
    "store_boundary",
]
