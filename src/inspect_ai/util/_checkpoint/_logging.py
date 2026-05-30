"""Opt-in debug print backing the resume-validation diagnostics.

Off by default. Set ``INSPECT_CHECKPOINT_VALIDATE`` to any non-empty
value to run the heavyweight ``_validate_resume_state`` resume sanity
checks (in ``hydrate.py``) and emit their verbose stdout dump — useful
for diagnosing a broken resume.

Normal-path subsystem logging (hydrate / fire / egress) does **not**
go through here; it uses ``trace_action`` / ``trace_message`` from
``inspect_ai._util.trace`` so it is structured, always recorded to the
trace log, and visible to ``inspect trace`` (e.g.
``inspect trace anomalies --filter checkpoint``).
"""

from __future__ import annotations

import os
from typing import Any

_ENV_VAR = "INSPECT_CHECKPOINT_VALIDATE"


def debug_enabled() -> bool:
    return bool(os.environ.get(_ENV_VAR))


def debug(*args: Any, **kwargs: Any) -> None:
    if debug_enabled():
        print(*args, **kwargs)
