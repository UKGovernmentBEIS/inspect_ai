"""Config knob tables: scope and version floors.

Pure data, imported from both the config and rendering sides (keeping
it a leaf avoids a ``_config``/``_render`` import cycle).
"""

from __future__ import annotations

# One source of truth for each retunable config knob's scope. The `ctl config`
# option help tags, the composed JSON view's per-knob "scope" labels, and the
# human rendering's [task]/[process] labels all derive from this table, so a
# knob's advertised blast radius can't drift between the three surfaces.
_KNOB_SCOPE: dict[str, str] = {
    "max_samples": "task",
    "max_tasks": "process",
    "max_sandboxes": "process",
    "max_subprocesses": "process",
    "max_connections": "process",
    "key": "process",
    "log_buffer": "task",
    "log_shared": "task",
    "timeout": "process",
    "attempt_timeout": "process",
    "max_retries": "process",
    "time_limit": "task",
    "token_limit": "task",
    "message_limit": "task",
}

# Minimum control-API version at which the server enforces strict mutations:
# a PATCH/POST carrying a query param the route doesn't declare is rejected
# with a 400, atomically, before anything is applied (`_control/strict.py`).
# From this version on, individual knobs need no client-side version gate —
# the server itself fails closed on a knob it doesn't know. Below it the
# tolerant handlers silently ignore unknown params while applying the rest,
# so the CLI refuses knob mutations outright. See `_gate_strict_floor`.
_STRICT_SINCE = 3

# Minimum control-API version for the config provenance params (`author` /
# `reason`, recorded into `EvalLog.config_updates`). Knobs themselves need no
# per-knob version gate — a strict server 400s a mutation carrying a knob it
# doesn't know, atomically (see the skew-policy comment in
# `inspect_ai._control`) — but the CLI sends a *defaulted* author the user
# never typed, and a strict older server would 400 the whole mutation for it,
# so the default is included only against servers advertising >= this version
# (an explicit --author/--reason against an older server hard-errors before
# sending). See `_gate_provenance_support`.
_PROVENANCE_SINCE = 5
