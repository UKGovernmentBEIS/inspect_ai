"""Detached launch (``--detach``) for ``inspect eval`` / ``eval-set`` / ``eval-retry``.

``--detach`` turns the foreground command into a launcher: it re-invokes
the same command as a session-detached child process (forcing ``--json``),
blocks until the child's ``launch`` record appears, re-emits that record
on its own stdout (augmented with the child's output file path), and
exits 0 — leaving the eval running with `inspect ctl` as the live
monitoring surface. The point is the *synchronous handoff*, not the
daemonization: a consumer that has read the launch record can trust
``inspect ctl`` immediately (see ``design/control-channel.md`` → "The
launch handoff is load-bearing"), while a launch that dies pre-flight
exits non-zero with the diagnostic relayed to stderr — never a silent
fire-and-forget.

There is no supervising daemon (unlike e.g. Claude Code's ``--bg``, whose
daemon is its reattach surface): Inspect already has a reattach surface —
the control channel and its discovery files — so the launcher's whole job
ends at the handoff. The child is a fresh ``subprocess`` re-invocation
(never ``fork()``: the parent has long since imported heavyweight,
thread-spawning modules) started in its own session (POSIX ``setsid``; on
Windows ``DETACHED_PROCESS``), so terminal hangups and Ctrl+C in the
launching shell cannot reach it. Its stdout+stderr land in a file under
the Inspect data dir — reported as ``output_file`` in the re-emitted
launch record.

The child exits on its own when the eval finishes, and the ``done``
record at the end of the output file is the completion signal: present →
finished, with overall success and each task's status and log location;
process gone without one → the run died mid-flight, with diagnostics in
the same file. There is deliberately no forced ``--ctl-server=keep``: a
long eval routinely outlives the agent session that launched it, and a
park waiting for an ``inspect ctl process release`` from a consumer that
no longer exists would leak an idle process per launch. The control
server itself (on by default) is still required — ``--ctl-server=false``
is rejected — so a detached eval is always observable and cancellable
*while running*. A consumer that wants the process to stay queryable
after the eval finishes passes ``--ctl-server=keep`` explicitly (the
value is preserved, and the ``done`` record is then written only when
the park is released).
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any, NoReturn

from shortuuid import uuid

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.error import PrerequisiteError

DETACH_HELP = (
    "Run the eval in the background: prints the launch record (implies --json) "
    "once the control endpoint is bound, then returns, leaving the eval running "
    "detached from the terminal (the detached process's output goes to a file "
    "reported as 'output_file' in the launch record). While it runs, monitor "
    "with `inspect ctl task list` and cancel with `inspect ctl task cancel`. "
    "The process exits when the eval finishes, leaving a 'done' record — "
    "overall success plus each task's status and log_location — as the output "
    "file's last line; a process that exited without one died mid-run, with "
    "diagnostics in the same file. Pass --ctl-server=keep to instead keep the "
    "process alive (and queryable via `inspect ctl`) after the eval finishes, "
    "until `inspect ctl process release`."
)


def exec_detached(ctl_server: bool | str | None) -> NoReturn:
    """Hand the current CLI command off to a detached child process and exit.

    Spawns the child, waits for its ``launch`` record (tailing the output
    file, so the child's stdout never depends on the launcher staying
    alive), re-emits the record, and exits with the handoff verdict:

    - ``launch`` with a control endpoint → record (plus ``output_file``)
      on stdout, exit 0; the eval keeps running detached.
    - ``launch`` with ``control: null`` (the control server failed to
      bind) → the child is terminated, its output relayed to stderr, and
      the launcher exits non-zero: a detached eval with no control
      surface could not be observed or cancelled while running — the
      same state the ``--ctl-server=false`` rejection rules out.
    - child exited without a record → its output is relayed to stderr and
      the launcher exits non-zero (pre-flight failure).
    - ``done`` without a prior ``launch`` → the run finished during the
      handoff without ever binding a control surface (an all-reused
      eval-set runs no eval, so nothing binds — unless an explicit
      ``--ctl-server=keep`` park does): the record is re-emitted and the
      launcher exits with the child's code.
    - Ctrl+C or SIGTERM during the wait terminates the child, preserving
      the invariant that no emitted ``launch`` record means no detached
      eval (exit 130/143 respectively).

    There is deliberately no timeout: task imports can legitimately take
    minutes, and the contract is "returns when the handoff resolves".
    """
    if ctl_server is False:
        raise PrerequisiteError(
            "--detach requires the control server (monitoring a detached eval "
            "goes through `inspect ctl`): remove --ctl-server=false or drop "
            "--detach."
        )

    output_file = _allocate_output_file()
    argv = [sys.executable, "-m", "inspect_ai._cli.main", *_child_args(sys.argv[1:])]
    # the child must not re-detach when the flag came from the environment
    # (its argv copy is already stripped of --detach)
    env = dict(os.environ)
    env.pop("INSPECT_EVAL_DETACH", None)

    # start_new_session (POSIX setsid) detaches from the terminal's session;
    # CPython ignores it on Windows, where the creation flags detach from the
    # console and its ctrl-c/ctrl-break signal group instead
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    with open(output_file, "wb") as output:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
            creationflags=creationflags,
        )

    # SIGTERM (e.g. `timeout … inspect eval --detach`, CI cancellation) must
    # preserve the same no-third-state invariant as Ctrl+C: no emitted
    # launch record means no detached eval left behind
    previous_sigterm = signal.signal(signal.SIGTERM, _raise_terminated)
    try:
        record = _wait_for_record(child, output_file)
    except (KeyboardInterrupt, _Terminated) as ex:
        child.terminate()
        print(
            f"\nDetached launch interrupted — terminated the eval process "
            f"(pid {child.pid}). Its output so far is in {output_file}.",
            file=sys.stderr,
            flush=True,
        )
        interrupt = signal.SIGTERM if isinstance(ex, _Terminated) else signal.SIGINT
        sys.exit(128 + int(interrupt))
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)

    if record is not None and record.get("event") == "launch":
        if record.get("control") is None:
            # the control server failed to bind: the eval would run detached
            # but could be neither observed nor cancelled while running — the
            # exact state --detach exists to prevent — so treat the handoff
            # as failed rather than exit 0 into an unmonitorable run
            child.terminate()
            child.wait()
            print(
                f"Detached launch failed — the control endpoint did not bind, "
                f"so the eval could not be monitored; terminated the eval "
                f"process (pid {child.pid}). Its output (also in "
                f"{output_file}) follows.",
                file=sys.stderr,
                flush=True,
            )
            _exit_relaying_output(output_file, 1)
        record["output_file"] = str(output_file)
        print(json.dumps(record), flush=True)
        sys.exit(0)

    if record is not None:  # done without a prior launch
        record["output_file"] = str(output_file)
        print(json.dumps(record), flush=True)
        sys.exit(child.wait())

    _exit_relaying_output(output_file, child.wait())


class _Terminated(BaseException):
    """SIGTERM arrived during the handoff wait (mirrors KeyboardInterrupt)."""


def _raise_terminated(signum: int, frame: FrameType | None) -> NoReturn:
    raise _Terminated()


def _exit_relaying_output(output_file: Path, returncode: int) -> NoReturn:
    """Relay the child's output to stderr and exit non-zero (failed handoff)."""
    sys.stderr.write(output_file.read_text(encoding="utf-8", errors="replace"))
    sys.stderr.flush()
    sys.exit(returncode if returncode != 0 else 1)


def _child_args(args: list[str]) -> list[str]:
    """Build the detached child's command arguments from this process's own.

    Strips the ``--detach`` flag tokens and adds ``--json`` (a bare
    repeated ``--json`` flag is harmless); any ``--ctl-server`` value the
    user passed — notably an explicit ``keep`` — is preserved verbatim.
    The forced flag goes before any bare ``--`` separator (click stops
    option parsing there, so tokens after it are positional); everything
    from the separator on is preserved verbatim.
    """
    forced = ["--json"]
    separator = args.index("--") if "--" in args else len(args)
    options = [arg for arg in args[:separator] if arg != "--detach"]
    return options + forced + args[separator:]


def _allocate_output_file() -> Path:
    """Allocate the detached run's output file under the Inspect data dir."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return inspect_data_dir("detach") / f"{stamp}-{uuid()[:8]}.out"


def _wait_for_record(
    child: "subprocess.Popen[bytes]", output_file: Path
) -> dict[str, Any] | None:
    """Tail the child's output file until a handoff record or child exit.

    Returns the first ``launch``/``done`` record, or ``None`` when the
    child exited without producing one. The exit check precedes each read,
    so the final iteration always drains output written before the exit.
    """
    partial = ""
    with open(output_file, encoding="utf-8", errors="replace") as output:
        while True:
            exited = child.poll() is not None
            partial += output.read()
            lines = partial.split("\n")
            partial = lines.pop()
            for line in lines:
                record = _handoff_record(line)
                if record is not None:
                    return record
            if exited:
                # a crashed child can leave an unterminated trailing line;
                # a complete record may still be sitting in it
                return _handoff_record(partial)
            time.sleep(0.1)


def _handoff_record(line: str) -> dict[str, Any] | None:
    """Parse one output line, returning it when it is a handoff record.

    The child's stdout and stderr share the output file, so stderr
    diagnostics interleave with the JSON records; anything that doesn't
    parse as a ``launch``/``done`` record is skipped.
    """
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if isinstance(record, dict) and record.get("event") in ("launch", "done"):
        return record
    return None
