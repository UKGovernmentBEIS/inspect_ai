from __future__ import annotations

import io
import json
import os
import shutil
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Sequence, Set, cast

from upath import UPath

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.hash import mm3_hash
from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._scanspec import ScanSpec
from inspect_ai.scanner._transcript.types import TranscriptInfo
from inspect_ai.scanner._util.file import write_file_async

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

    @staticmethod
    def buffer_dir(scan_location: str) -> UPath:
        scan_path = UPath(scan_location).resolve()
        return UPath(
            inspect_data_dir("scan_buffer") / f"{mm3_hash(scan_path.as_posix())}"
        )

    def __init__(self, scan_location: str, spec: ScanSpec):
        self._buffer_dir = RecorderBuffer.buffer_dir(scan_location)
        self._spec = spec

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
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "scan_id": self._spec.scan_id,
                    "scan_tags": self._spec.tags,
                    "scan_metadata": self._spec.metadata,
                    "scanner_name": scanner,
                    "scanner_file": self._spec.scanners[scanner].file,
                    "scanner_params": self._spec.scanners[scanner].params,
                },
            )
            | transcript.metadata
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

    async def write_table_for_scanner(self, scanner: str, table_file: str) -> None:
        import pyarrow as pa
        import pyarrow.dataset as ds
        import pyarrow.parquet as pq

        # NOTE: this function attempts to cap memory usage at ~ 100MB for compacting
        # scanner results. It does get a bit fancy/complicated and uses a bunch of
        # pyarrow streaming primitives. If this ends up working out poorly the naive
        # implementation is just this:
        #
        #   dataset = ds.dataset(sdir.as_posix(), format="parquet")
        #   table = dataset.to_table() # materialize fully
        #
        #   pq.write_table(
        #       table,
        #       table_file,
        #       compression="zstd",
        #       use_dictionary=True,
        #   )

        MAX_BYTES: Final[int] = 100_000_000
        DEFAULT_BATCH_ROWS: Final[int] = 1_000

        # resolve input dir
        sdir = self._buffer_dir / f"scanner={_sanitize_component(scanner)}"
        if not sdir.exists():
            # we avoid creating a schema-less empty Parquet when there is no dataset at all.
            # If you *must* emit a file even when the directory is missing, you need a known schema.
            return

        # build dataset
        dataset: ds.Dataset = ds.dataset(str(sdir), format="parquet")

        # discover the unified schema up-front. This ensures column order/types are stable.
        # if there are absolutely no fragments under sdir, accessing .schema may raise.
        try:
            schema: pa.Schema = dataset.schema
        except Exception as e:
            raise RuntimeError(
                f"Unable to discover dataset schema under {sdir}: {e}"
            ) from e

        # state for bounded accumulation -> large-ish row groups
        accumulated: list[pa.RecordBatch] = []
        accumulated_bytes: int = 0

        def flush_accumulated(writer: pq.ParquetWriter) -> None:
            nonlocal accumulated, accumulated_bytes
            if not accumulated:
                return
            table = pa.Table.from_batches(accumulated)  # bounded by MAX_BYTES
            writer.write_table(table)
            accumulated.clear()
            accumulated_bytes = 0

        # Create an in-memory buffer
        buffer = io.BytesIO()
        writer = pq.ParquetWriter(
            buffer,
            schema,
            compression="zstd",
            use_dictionary=True,
        )

        # iterate materialized batches; to keep memory in check we use a small batch_size.
        for batch in dataset.to_batches(
            batch_size=DEFAULT_BATCH_ROWS,
            use_threads=True,
        ):
            size = batch.nbytes
            if accumulated_bytes and accumulated_bytes + size > MAX_BYTES:
                flush_accumulated(writer)
            accumulated.append(batch)
            accumulated_bytes += size

        # Final flush. If no rows were seen, this still leaves us with an empty file (schema only).
        flush_accumulated(writer)
        writer.close()

        # rewind bytes and write
        buffer.seek(0)
        await write_file_async(table_file, buffer.getvalue())

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
