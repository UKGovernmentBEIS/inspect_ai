from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from inspect_ai._util._async import run_coroutine
from inspect_ai.scanner._scanner import Scanner

from ._transcript.transcripts import Transcripts

if TYPE_CHECKING:
    import pandas as pd

DEFAULT_RESULTS_COLS = [
    "eval_id",
    "log",
    "task_name",
    "model_name",
    "sample_id",
    "message_id",
    "event_id",
    "value",
    "answer",
    "explanation",
    "metadata",
    "references",
]


class ResultsOptions(BaseModel):
    """Options for handling results from `scan()`."""

    model_config = ConfigDict(
        validate_default=True,  # Validate default values
        extra="forbid",  # Prevent unexpected fields
        frozen=True,
    )

    save: bool = Field(default=True)
    """Save results to the file system (if `False` they are returned by not written to disk)."""

    dir: str = Field(default="./scans")
    """Directory to save results to."""

    name: str = Field(default="scan", pattern=r"^[a-zA-Z0-9_-]+$")
    """Distinguishing name for scan (used in subdir name)."""

    file: str = Field(
        default="{timestamp}_{scan_name}_{scan_id}/{scanner_name}.parquet"
    )
    """Filename to save results to (includes parent directory for scan)."""

    cols: list[str] = Field(default_factory=lambda: DEFAULT_RESULTS_COLS.copy())
    """DataFrame columns to include in results.

    You must include at least the columns "eval_id", "log", and "sample_id".
    """

    @field_validator("file")
    @classmethod
    def validate_file_template(cls, v: str) -> str:
        required_placeholders = [
            "{timestamp}",
            "{scan_name}",
            "{scan_id}",
            "{scanner_name}",
        ]
        for placeholder in required_placeholders:
            if placeholder not in v:
                raise ValueError(f"File template must contain {placeholder}")
        return v

    @field_validator("cols")
    @classmethod
    def validate_columns(cls, v: list[str]) -> list[str]:
        required_cols = {"eval_id", "log", "sample_id"}  # Minimum required
        if not required_cols.issubset(set(v)):
            raise ValueError(f"cols must include: {required_cols}")
        return v


def scan(
    transcripts: Transcripts,
    scanners: list[Scanner[Any]],
    results: ResultsOptions | None = None,
) -> dict[str, "pd.DataFrame"]:
    return run_coroutine(scan_async(transcripts, scanners, results=results))


async def scan_async(
    transcripts: Transcripts,
    scanners: list[Scanner[Any]],
    results: ResultsOptions | None = None,
) -> dict[str, "pd.DataFrame"]:
    if results is None:
        results = ResultsOptions()
    return {}


# scans/
#   in_progress/
#       timestamp-scanname-scan-id/
#          scan.json
#          reward_hacking.parquet


# scorer: Scorer | Scanner[Transcript]

# eval(scorer=reward_hacking())

# scan_resume(scan_id="foo")


# inspect scan --transcripts="logs" scanner.py
