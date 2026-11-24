"""Read-only eval status from a log directory (``inspect ctl ... --log-dir``).

Builds the control API's task rows, sample rows and per-sample envelopes from
the ``.eval`` logs in a directory rather than from a live process. Nothing
here starts a server, writes to the directory or runs task code. See
``design/ctl/log-dir-mode.md``.
"""
