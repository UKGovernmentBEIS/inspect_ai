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
# Convention: bump this in the SAME PR that adds anything the CLI must gate
# on (a new knob or endpoint an older server would silently ignore), and
# record the new value as that feature's `_KNOB_SINCE` entry. Purely additive
# response fields the CLI already null-guards don't need a bump.
#
# Version history:
#   0 — initial channel (tolerant servers: mutation handlers silently ignore
#       unknown query params).
#   1 — max_subprocesses knob.
#   2 — strict mutations: the server 400s on unknown query params to any
#       non-GET route (`_control/strict.py`), so `api_version >= 2` means a
#       client can rely on the server to reject rather than partially apply
#       an unsupported knob.
CONTROL_API_VERSION: int = 2
