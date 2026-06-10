"""Unit tests for :mod:`inspect_ai._util.process`."""

import os

from inspect_ai._util.process import pid_alive


def test_pid_alive_for_current_process() -> None:
    """The current PID is always alive."""
    assert pid_alive(os.getpid()) is True


def test_pid_alive_for_zero_pid_is_dead() -> None:
    """PID 0 is never a valid process id."""
    assert pid_alive(0) is False


def test_pid_alive_for_negative_pid_is_dead() -> None:
    """Negative PIDs are never valid."""
    assert pid_alive(-1) is False
    assert pid_alive(-999999) is False


def test_pid_alive_for_high_pid_is_dead() -> None:
    """A PID far above the kernel's max is reliably dead."""
    # POSIX kernel.pid_max is typically 32768 or 4194304; 999_999_999
    # is essentially never assignable, so this is a stable "dead" PID
    # without racing against process recycling.
    assert pid_alive(999_999_999) is False
