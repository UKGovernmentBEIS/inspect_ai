"""Control channel — HTTP server embedded in each running eval process.

Exposes live-eval read / direct / event-subscription operations to
external clients (the `inspect ctl` CLI, TUIs, agents). See
``design/control-channel.md`` for the full design.
"""

# Control-channel API version, for CLI <-> server skew handling. `inspect
# ctl` talks to live eval processes that embed whatever inspect version they
# were launched with, so a newer CLI can be pointed at an older process —
# rare, but possible when the CLI is upgraded mid-eval. The server advertises
# this single channel-wide integer (in its discovery file and on each
# `/tasks` row); the CLI's legacy `_KNOB_SINCE` gates (see
# `inspect_ai._cli.ctl`) compare against it before sending a mutation. A
# server that predates this field implicitly reports version 0.
#
# What needs a bump (and what doesn't), per kind of change:
#
# - New MUTATION PARAM (a knob, or an action-style param on a POST route):
#   no bump, no CLI gate. Every server in the field is strict (version >= 3):
#   it rejects unknown query params on any non-GET route with a 400
#   (`_control/strict.py`), so a mutation an older server can't honor fails
#   loudly instead of silently no-opping. Pre-strict (version < 3) servers —
#   whose mutation handlers silently ignored unknown params — are considered
#   aged out (eval processes are short-lived). The remaining `_KNOB_SINCE`
#   entries (`max_subprocesses` since 1, `key` since 2) predate strict
#   mutations and retire with issue #67.
# - New ENDPOINT: no bump. An older server answers a missing route with
#   FastAPI's stock `{"detail": "Not Found"}` 404, which the CLI tells apart
#   from a handler's `{"error": ...}` entity-not-found 404 — pass
#   `not_found_missing_route` to `_request_json` and the skew is reported
#   definitively with no version bookkeeping (and accurately even against
#   servers that predate version reporting). Handler 404s must carry the
#   `{"error": ...}` body for this to hold — see the convention comment in
#   `server.py`.
# - Purely additive response fields the CLI already null-guards: no bump.
#
# Version history:
#   0 — initial channel (tolerant servers: mutation handlers silently ignore
#       unknown query params).
#   1 — max_subprocesses knob.
#   2 — key/key_limit knob.
#   3 — strict mutations: the server 400s on unknown query params to any
#       non-GET route (`_control/strict.py`), so `api_version >= 3` means a
#       client can rely on the server to reject rather than partially apply
#       an unsupported knob.
#   4 — retry override knobs (timeout / attempt_timeout / max_retries).
#   5 — config-change persistence (EvalLog.config_updates) and the
#       author/reason provenance params on the config PATCH routes. The
#       params themselves need no gate per the strict-mutations policy
#       above, but the CLI sends a *default* author (git identity) the user
#       never typed — a defaulted param must not 400 every config mutation
#       against an older server, so the CLI includes it only when the
#       server advertises >= 5 (an explicit --author/--reason against an
#       older server hard-errors before sending, like the legacy knob gates).
CONTROL_API_VERSION: int = 5
