"""Launch-handoff notification for agent-friendly launch output.

Right after ``inspect eval`` is launched, ``inspect ctl task list``
returning ``[]`` is indistinguishable from a failed launch: the control
socket may simply not be bound yet (and the first task registers only
after task startup, which can take minutes). The hook here closes that
race: ``eval_async`` emits a :class:`LaunchHandoff` the moment the
control-server context has been entered — i.e. once the control surface
is bound (or is definitively absent: disabled, or its bind failed) and
before any task work begins. A consumer that has seen the handoff holds
a hard guarantee: if ``control_socket`` is set the control surface
exists, so an empty ``ctl task list`` means "no tasks registered yet",
never "no server".

The current listeners are ``inspect eval --json`` and ``inspect
eval-set --json``, which print the record as a JSON line on stdout. The
listener is a process-wide module-level slot (not a parameter threaded
through ``eval()``) because the handoff is a launch concern of the CLI
process, not part of the public ``eval()`` surface. See
``design/ctl/control-channel.md`` → "Agent output contract" → "The launch
handoff is load-bearing".
"""

from typing import Callable, NamedTuple


class LaunchHandoff(NamedTuple):
    """Where a just-launched eval run can be reached."""

    run_id: str | None
    """Unique id of the run.

    ``None`` for the handoff emitted by an all-reused eval-set's
    keep-alive park: every task was reused from prior logs, so no eval
    ran — the record exists to report the parked process's control
    surface (see :func:`launch_handoff_emitted`).
    """

    pid: int
    """Process id hosting the run (the ``inspect ctl process`` selector)."""

    log_dir: str
    """Resolved directory the run's eval logs are written to."""

    control_socket: str | None
    """Path of the bound control-channel AF_UNIX socket.

    ``None`` means the run definitively has no control surface (the
    server was disabled via ``ctl_server=False``, or its bind failed and
    the eval degraded to running without one) — never that the socket
    isn't bound *yet*.
    """

    eval_set_id: str | None = None
    """Id of the enclosing eval set, when the run belongs to one."""


LaunchHandoffListener = Callable[[LaunchHandoff], None]

_listener: LaunchHandoffListener | None = None
_emitted = False


def set_launch_handoff_listener(listener: LaunchHandoffListener | None) -> None:
    """Register (or, with ``None``, clear) the process-wide handoff listener."""
    global _listener, _emitted
    _listener = listener
    _emitted = False


def emit_launch_handoff(handoff: LaunchHandoff) -> None:
    """Notify the registered listener (no-op when none is registered)."""
    global _emitted
    if _listener is not None:
        _emitted = True
        _listener(handoff)


def reset_launch_handoff_emitted() -> None:
    """Reset the per-run emitted flag at a run boundary.

    Called by ``eval_set`` at run start (alongside ``reset_keep_alive``)
    so a listener that stays registered across successive runs in one
    process doesn't carry a prior run's emission into this run's
    :func:`launch_handoff_emitted` check.
    """
    global _emitted
    _emitted = False


def launch_handoff_emitted() -> bool:
    """Whether a handoff was delivered to the currently registered listener.

    Lets the eval-set keep-alive park close the one hole in the launch
    contract: a set whose tasks are all already complete runs no eval, so
    nothing emits a handoff — yet with keep-alive the park still binds a
    control server the consumer should hear about (a ``--detach``
    launcher blocks on the ``launch`` record and would otherwise wait on
    a parked process forever). The park emits a handoff only when the
    run itself emitted none, keeping "exactly one ``launch`` record" true
    for every keep-alive run.
    """
    return _emitted
