"""Log format version gate shared by the `.json` and `.eval` readers."""

import os

from inspect_ai._util.constants import LOG_SCHEMA_VERSION

MAX_LOG_FILE_VERSION_VAR = "INSPECT_MAX_LOG_FILE_VERSION"
"""Env var raising the maximum log format version the readers accept.

Undocumented developer affordance: work on an unreleased format version
(e.g. the chunked format's version 3) needs to read logs that released
readers must still refuse while the format can change.
"""


def max_log_file_version() -> int:
    """Maximum log format version the readers accept.

    `LOG_SCHEMA_VERSION` unless `INSPECT_MAX_LOG_FILE_VERSION` raises it
    (the env var can never lower the ceiling below what this build supports).
    """
    return max(LOG_SCHEMA_VERSION, int(os.environ.get(MAX_LOG_FILE_VERSION_VAR, "0")))


def validate_log_file_version(version: int) -> None:
    """Refuse logs written in a future format version.

    Raises:
        ValueError: The log's version exceeds `max_log_file_version()`.
    """
    max_version = max_log_file_version()
    if version > max_version:
        raise ValueError(
            f"Unable to read version {version} of log format (this version of "
            f"inspect_ai reads formats up to version {max_version}; upgrade "
            "inspect_ai to read this log)."
        )
