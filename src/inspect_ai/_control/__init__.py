"""Control channel — HTTP server embedded in each running eval process.

Exposes live-eval read / direct / event-subscription operations to
external clients (the `inspect ctl` CLI, TUIs, agents). See
``design/control-channel.md`` for the full design.
"""
