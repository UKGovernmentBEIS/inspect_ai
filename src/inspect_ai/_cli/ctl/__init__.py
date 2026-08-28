"""`inspect ctl` — control-channel CLI subcommands.

The ``ctl`` group hosts the commands that operate on a *running* Inspect
eval via the per-process control server's HTTP endpoints. See
``design/ctl/control-channel.md`` for the design.

Commands are grouped by **resource noun**, mirroring the HTTP API's object
model (see "CLI command hierarchy: noun groups" in the design doc):

- ``task`` — a logical task in a running process (stable across retries):
  ``list`` (implied by the bare noun), ``log-flush``, ``cancel``, ``pause``,
  ``resume``; ``add`` / ``drain`` are planned.
- ``sample`` — one sample (``TASK SAMPLE_ID [EPOCH]``) or a task's samples:
  ``list`` (implied by the bare noun), ``show``, ``errors``, ``events``,
  ``messages``, ``cancel``, ``requeue``.
- ``config`` — a top-level *command* (not a group): view / retune launch
  configuration mid-flight (concurrency limits, log buffering). Scope is a
  property of each knob (task vs process), labeled in the output.
- ``process`` — the running Inspect process itself: ``list`` (implied by the
  bare noun), ``anomalies``, ``keep``, ``release``, ``pause``, ``resume``.
"""

# Importing the noun modules registers their commands on the `ctl` group
# (click decorators run at import time); do not remove them as unused.
from . import _config as _config
from . import _model as _model
from . import _process as _process
from . import _sample as _sample
from . import _task as _task
from ._group import ctl_command

__all__ = ["ctl_command"]
