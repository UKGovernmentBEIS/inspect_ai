"""Control channel — HTTP server embedded in each running eval process.

Exposes live-eval read / direct / event-subscription operations to
external clients (the `inspect ctl` CLI, TUIs, agents). See
``design/ctl/control-channel.md`` for the full design.
"""

# Control-channel API version, for CLI <-> server skew handling. `inspect
# ctl` talks to live eval processes that embed whatever inspect version they
# were launched with, so a newer CLI can be pointed at an older process —
# rare, but possible when the CLI is upgraded mid-eval. The server advertises
# this single channel-wide integer (in its discovery file and on each
# `/tasks` row); a server that predates the field implicitly reports
# version 0.
#
# Skew handling needs NO bump for the routine kinds of change — both halves
# interrogate the actual server rather than a version table:
#
# - New MUTATION PARAM (a knob, or an action-style param on a POST route):
#   every server in the field is strict (version >= 3): it rejects unknown
#   query params on any non-GET route with a 400 (`_control/strict.py`),
#   atomically — so a mutation an older server can't honor fails loudly
#   before anything is applied, instead of silently no-opping. (The
#   per-knob `_KNOB_SINCE` pre-flight gate that covered pre-strict servers
#   was retired with issue #67 once those aged out of the field.)
# - New ENDPOINT: an older server answers a missing route with FastAPI's
#   stock `{"detail": "Not Found"}` 404, which the CLI tells apart from a
#   handler's `{"error": ...}` entity-not-found 404 — pass
#   `not_found_missing_route` to `_request_json` and the skew is reported
#   definitively with no version bookkeeping (and accurately even against
#   servers that predate version reporting). Handler 404s must carry the
#   `{"error": ...}` body for this to hold — see the convention comment in
#   `server.py`.
# - Purely additive response fields the CLI already null-guards: no bump.
#
# What still warrants a bump: a change the CLI must *adapt its own behavior*
# to, where failing loudly is the wrong outcome. The one live example is
# version 5's defaulted provenance author — a param the user never typed
# must not 400 their retune on an older strict server, so the CLI includes
# it only when the server advertises support (`_PROVENANCE_SINCE` in
# `inspect_ai._cli.ctl`). Bump the constant in the same PR as such a change.
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
#       older server hard-errors before sending).
CONTROL_API_VERSION: int = 5
