"""Parse compact duration strings like ``15m`` / ``30s`` / ``2h`` into ``timedelta``.

Single-unit shorthand (or a bare integer interpreted as seconds). Distinct
from :mod:`inspect_ai._util.http`'s multi-unit ``"1m30s"``-style parser and
from :mod:`inspect_ai.util._sandbox.docker.service`'s Docker-compose
parser — those keep their own variants because they have different
output types and accept different unit sets.
"""

from __future__ import annotations

import re
from datetime import timedelta

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_DURATION_UNITS_S: dict[str, float] = {
    "": 1.0,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}


def parse_duration(value: str, *, error_prefix: str = "duration") -> timedelta:
    """Parse ``15m`` / ``30s`` / ``2h`` / ``1d``, or a bare integer (seconds).

    Raises ``ValueError`` on a malformed string or a non-positive result.
    ``error_prefix`` is used to tag the raised message (e.g. the CLI flag
    name) so the diagnostic is meaningful to the caller's audience.
    """
    m = _DURATION_RE.match(value)
    if m is None:
        raise ValueError(f"{error_prefix}: expected <number><s|m|h|d>, got {value!r}")
    seconds = float(m.group(1)) * _DURATION_UNITS_S[m.group(2).lower()]
    if seconds <= 0:
        raise ValueError(f"{error_prefix}: duration must be > 0, got {value!r}")
    return timedelta(seconds=seconds)
