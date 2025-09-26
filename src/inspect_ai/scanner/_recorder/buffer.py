from __future__ import annotations

import json
import os
import shutil
from typing import TYPE_CHECKING, Any, Sequence, Set, cast

from upath import UPath

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.hash import mm3_hash
from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._transcript.types import TranscriptInfo

if TYPE_CHECKING:
    import pyarrow as pa


class RecorderBuffer:
    """
    Parquet-backed buffer compatible with the previous RecorderBuffer API.

    Layout on disk:
      inspect_data_dir("scan_buffer") / "<hash_of_scan_location>" /
          scanner=<scanner_name> /
              <transcript_id>.parquet

    Assumptions:
      - transcript_id is a UUID (safe as filename)
      - only one process writes a given <transcript_id>.parquet once
    """

    def __init__(self, scan_location: str):
        self._buffer_dir = UPath(
            inspect_data_dir("scan_buffer") / f"{mm3_hash(scan_location)}"
        )

    async def record(
        self, transcript: TranscriptInfo, scanner: str, results: Sequence[Result]
    ) -> None:
        import pyarrow.parquet as pq

        records = [
            cast(
                dict[str, str | bool | int | float | None],
                {
                    "transcript_id": transcript.id,
                    "transcript_source_id": transcript.source_id,
                    "transcript_source_uri": transcript.source_uri,
                    "scanner": scanner,
                },
            )
            | result.to_df_columns()
            for result in results
        ]
        if not records:
            return

        table = _records_to_arrow(records)

        # Ensure destination directory exists
        sdir = self._buffer_dir / f"scanner={_sanitize_component(scanner)}"
        sdir.mkdir(parents=True, exist_ok=True)

        # One-shot write per transcript
        final_path = sdir / f"{transcript.id}.parquet"
        if final_path.exists():
            # Idempotent: already recorded
            return

        # Atomic write: write to .tmp, then os.replace to final
        tmp_path = sdir / f".{transcript.id}.parquet.tmp"
        pq.write_table(
            table,
            tmp_path.as_posix(),
            compression="zstd",
            use_dictionary=True,
        )
        os.replace(tmp_path.as_posix(), final_path.as_posix())

    async def is_recorded(self, transcript: TranscriptInfo, scanner: str) -> bool:
        sdir = self._buffer_dir / f"scanner={_sanitize_component(scanner)}"
        return (sdir / f"{transcript.id}.parquet").exists()

    async def table_for_scanner(self, scanner: str) -> "pa.Table" | None:
        """
        Return a PyArrow Table with all shards for the scanner (or None if none exist).

        If a fixed schema for the scanner was provided, it is supplied to the dataset
        so that unification uses the canonical types.
        """
        import pyarrow.dataset as ds

        sdir = self._buffer_dir / f"scanner={_sanitize_component(scanner)}"
        if not sdir.exists():
            return None

        dataset = ds.dataset(sdir.as_posix(), format="parquet")
        table = (
            dataset.to_table()
        )  # materialize; for huge datasets you can stream batches
        # Return None for totally empty datasets (e.g., rare edge cases)
        return table if table.num_rows > 0 else None

    def cleanup(self) -> None:
        """Remove the buffer directory for this scan (best-effort)."""
        try:
            shutil.rmtree(self._buffer_dir.as_posix(), ignore_errors=True)
        except Exception:
            pass


def _sanitize_component(name: str) -> str:
    """Make a string safe for use as a single path component."""
    import re

    # allow [A-Za-z0-9 _-+=.,@]; replace others with "_"
    return re.sub(r"[^a-zA-Z0-9_\-=+.,@]", "_", name)


def _normalize_scalar(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (str, int, float)):
        return v
    # datetime/date
    try:
        from datetime import date, datetime

        if isinstance(v, (datetime, date)):
            return v
    except Exception:
        pass
    # Decimal, lists, dicts, sets, tuples -> JSON text if possible
    try:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(v)


def _records_to_arrow(records: list[dict[str, Any]]) -> "pa.Table":
    """Build an Arrow table directly from normalized Python records."""
    import pyarrow as pa

    # First normalize scalars
    norm = [{k: _normalize_scalar(v) for k, v in r.items()} for r in records]

    # Check for mixed-type columns and convert them to strings
    if norm:
        # Detect which columns have mixed types
        columns_types: dict[str, Set[Any]] = {}
        for record in norm:
            for key, value in record.items():
                if value is not None:
                    val_type = type(value).__name__
                    if key not in columns_types:
                        columns_types[key] = set()
                    columns_types[key].add(val_type)

        # Convert mixed-type columns to strings
        mixed_cols = {k for k, types in columns_types.items() if len(types) > 1}
        if mixed_cols:
            for record in norm:
                for col in mixed_cols:
                    if col in record and record[col] is not None:
                        record[col] = str(record[col])

    return pa.Table.from_pylist(norm)
