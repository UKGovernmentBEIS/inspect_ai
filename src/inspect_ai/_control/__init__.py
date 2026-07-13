"""Control channel — HTTP server embedded in each running eval process.

Exposes live-eval read / direct / event-subscription operations to
external clients (the `inspect ctl` CLI, TUIs, agents). See
``design/control-channel.md`` for the full design.
"""

# Control-channel API version, for CLI <-> server skew gating. `inspect ctl`
# talks to live eval processes that embed whatever inspect version they were
# launched with, so a newer CLI can be pointed at an older process — rare,
# but possible when the CLI is upgraded mid-eval. The server advertises this
# single channel-wide integer (in its discovery file and on each `/tasks`
# row); the CLI gates version-dependent knobs on it *before* sending a
# mutation (see `_KNOB_SINCE` in `inspect_ai._cli.ctl`) — an older server's
# PATCH handlers silently ignore unknown query params, so without the gate a
# new knob would no-op behind a success-shaped response. A server that
# predates this field implicitly reports version 0.
#
# What needs a bump (and what doesn't), per kind of change:
#
# - New KNOB (query param an older PATCH handler would silently ignore):
#   bump this in the SAME PR and record the new value as the knob's
#   `_KNOB_SINCE` entry. Until older servers reject unknown params
#   server-side (issue #66; the gate then retires per issue #67), this is
#   the only defense against a silent partial apply.
# - New ENDPOINT: no bump. An older server answers a missing route with
#   FastAPI's stock `{"detail": "Not Found"}` 404, which the CLI tells apart
#   from a handler's `{"error": ...}` entity-not-found 404 — pass
#   `not_found_missing_route` to `_request_json` and the skew is reported
#   definitively with no version bookkeeping (and accurately even against
#   servers that predate version reporting). Handler 404s must carry the
#   `{"error": ...}` body for this to hold — see the convention comment in
#   `server.py`.
# - Purely additive response fields the CLI already null-guards: no bump.
CONTROL_API_VERSION: int = 1  # 1: max_subprocesses knob
