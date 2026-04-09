"""Read crashed .eval files for recovery."""

import json
from dataclasses import dataclass, field
from typing import Any

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai.log._log import EvalPlan, EvalSample, EvalSampleSummary, EvalSpec
from inspect_ai.log._pool import resolve_sample_events_data
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    JOURNAL_DIR,
    SAMPLES_DIR,
    START_JSON,
    SUMMARIES_JSON,
    SUMMARY_DIR,
    LogStart,
)


@dataclass
class CrashedEvalLog:
    """Data extracted from a crashed .eval file."""

    location: str
    """Path to the crashed .eval file."""

    version: int
    """Log schema version."""

    eval: EvalSpec
    """Eval specification."""

    plan: EvalPlan
    """Eval plan."""

    summaries: list[EvalSampleSummary] = field(default_factory=list)
    """Sample summaries from journal flushes."""

    sample_entries: list[str] = field(default_factory=list)
    """ZIP entry names for flushed samples (e.g. 'samples/sample_1_1.json')."""


async def read_crashed_eval_log(location: str) -> CrashedEvalLog:
    """Read a crashed .eval file and extract its partial contents.

    Args:
        location: Path to the crashed .eval file (local path, file:// URI, or s3://).

    Returns:
        CrashedEvalLog with extracted start data, summaries, and sample entry names.

    Raises:
        ValueError: If the log is complete (has header.json) or invalid (no start.json).
    """
    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, location)
        cd = await reader.entries()
        entry_names = {e.filename for e in cd.entries}

        # Validate: must NOT have header.json (would mean log completed normally)
        if HEADER_JSON in entry_names:
            raise ValueError(f"Log is not crashed (has {HEADER_JSON}): {location}")

        # Validate: must have start.json
        start_path = _journal_path(START_JSON)
        if start_path not in entry_names:
            raise ValueError(f"Log is invalid (missing {start_path}): {location}")

        # Read start data
        start = LogStart.model_validate(
            await _read_member_json(reader, start_path),
            context=get_deserializing_context(),
        )

        # Read journal summaries
        summaries = await _read_journal_summaries(reader, entry_names)

        # Collect sample entry names (don't read the data)
        sample_entries = sorted(
            name
            for name in entry_names
            if name.startswith(f"{SAMPLES_DIR}/") and name.endswith(".json")
        )

        return CrashedEvalLog(
            location=location,
            version=start.version,
            eval=start.eval,
            plan=start.plan,
            summaries=summaries,
            sample_entries=sample_entries,
        )


async def read_flushed_sample(reader: AsyncZipReader, entry_name: str) -> EvalSample:
    """Read a single flushed sample from a .eval ZIP file.

    Args:
        reader: An open AsyncZipReader for the .eval file.
        entry_name: The ZIP entry name (e.g. 'samples/sample_1_1.json').

    Returns:
        The deserialized EvalSample.
    """
    data = await _read_member_json(reader, entry_name)
    sample = EvalSample.model_validate(data, context=get_deserializing_context())
    return resolve_sample_events_data(sample)


async def _read_member_json(reader: AsyncZipReader, member: str) -> Any:
    """Read and parse a JSON member from a ZIP file."""
    return json.loads(await reader.read_member_fully(member))


async def _read_journal_summaries(
    reader: AsyncZipReader, entry_names: set[str]
) -> list[EvalSampleSummary]:
    """Read journal summaries from a crashed .eval file.

    Reads from _journal/summaries/*.json (intermediate flush files).
    A crashed log won't have consolidated summaries.json.
    """
    # If consolidated summaries exist (shouldn't for crashed logs, but handle it)
    if SUMMARIES_JSON in entry_names:
        return _parse_summaries(await _read_member_json(reader, SUMMARIES_JSON))

    # Read intermediate summary files
    summary_prefix = _journal_summary_path()
    summary_files: list[tuple[int, str]] = []
    for name in entry_names:
        if name.startswith(summary_prefix) and name.endswith(".json"):
            index = int(name.split("/")[-1].split(".")[0])
            summary_files.append((index, name))

    # Read in order
    summary_files.sort()
    summaries: list[EvalSampleSummary] = []
    for _, path in summary_files:
        summaries.extend(_parse_summaries(await _read_member_json(reader, path)))
    return summaries


def _parse_summaries(data: list[Any]) -> list[EvalSampleSummary]:
    """Parse a list of summary dicts into EvalSampleSummary objects."""
    return [
        EvalSampleSummary.model_validate(value, context=get_deserializing_context())
        for value in data
    ]


def _journal_path(file: str) -> str:
    return f"{JOURNAL_DIR}/{file}"


def _journal_summary_path(file: str | None = None) -> str:
    if file is None:
        return _journal_path(f"{SUMMARY_DIR}/")
    return f"{_journal_path(SUMMARY_DIR)}/{file}"
