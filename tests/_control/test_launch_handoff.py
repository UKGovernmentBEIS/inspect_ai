"""Tests for the synchronous launch handoff (``inspect eval[-set|-retry] --json``).

The launch-and-babysit workflow needs ``inspect eval`` to say where the
control surface is the moment it exists: right after launch, ``inspect
ctl task list`` returning ``[]`` is indistinguishable from a failed
launch (the socket may simply not be bound yet). These tests pin the two
halves of the guarantee:

- ``eval_async`` emits the :class:`LaunchHandoff` only after the control
  server is bound (the socket is live at emission time, while the task
  list is still empty — exactly the window the handoff exists to make
  unambiguous), or with ``control_socket=None`` when the surface is
  definitively absent (``ctl_server=False``).
- ``inspect eval --json`` renders the handoff as a ``launch`` JSON line
  and finishes with a ``done`` line carrying per-task log locations,
  with every stdout line parseable as JSON.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

import inspect_ai
from _control.conftest import cli_runner
from inspect_ai import Task, task
from inspect_ai._cli.eval import (
    _json_prerequisite_errors_to_stderr,
    eval_command,
    eval_retry_command,
    eval_set_command,
)
from inspect_ai._control.eval_state import get_eval_states
from inspect_ai._eval.handoff import (
    LaunchHandoff,
    emit_launch_handoff,
    set_launch_handoff_listener,
)
from inspect_ai._util.error import PrerequisiteError, SilentException
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate

# `_isolate_active_model` (autouse) and `short_data_dir` come from
# tests/_control/conftest.py.


@pytest.fixture
def handoff_listener() -> Iterator[list[LaunchHandoff]]:
    """Register a recording listener, guaranteeing it is cleared afterwards."""
    seen: list[LaunchHandoff] = []
    set_launch_handoff_listener(seen.append)
    try:
        yield seen
    finally:
        set_launch_handoff_listener(None)


@task
def handoff_task() -> Task:
    return Task(
        dataset=[Sample(input="x", target="y")],
        solver=[generate()],
        name="handoff_task",
    )


def test_handoff_fires_after_control_bind(
    short_data_dir: Path, handoff_listener: list[LaunchHandoff]
) -> None:
    """The handoff is emitted once the control socket is live, before any task.

    Captures the launch guarantee at its sharpest point: at emission time
    the socket already accepts (it exists on disk) while no task has
    registered yet — the exact window where, without the handoff, an
    empty ``ctl task list`` would be indistinguishable from a failed
    launch.
    """
    at_emission: list[tuple[bool, int]] = []

    def on_launch(handoff: LaunchHandoff) -> None:
        handoff_listener.append(handoff)
        at_emission.append(
            (
                handoff.control_socket is not None
                and Path(handoff.control_socket).is_socket(),
                len(get_eval_states()),
            )
        )

    set_launch_handoff_listener(on_launch)

    log_dir = str(short_data_dir / "logs")
    logs = inspect_ai.eval(handoff_task(), model="mockllm/model", log_dir=log_dir)

    assert len(handoff_listener) == 1
    handoff = handoff_listener[0]
    assert handoff.run_id == logs[0].eval.run_id
    assert handoff.pid == os.getpid()
    assert handoff.log_dir == log_dir
    assert at_emission == [(True, 0)], (
        "expected a live control socket and an empty task list at emission time"
    )


def test_handoff_reports_no_control_when_disabled(
    short_data_dir: Path, handoff_listener: list[LaunchHandoff]
) -> None:
    """``ctl_server=False`` still emits the handoff, with a null control socket.

    The record must appear either way — its absence means "launch failed",
    so a disabled surface is reported as ``control_socket=None`` (a
    definitive "no server"), not by omitting the handoff.
    """
    log_dir = str(short_data_dir / "logs")
    inspect_ai.eval(
        handoff_task(), model="mockllm/model", log_dir=log_dir, ctl_server=False
    )

    assert len(handoff_listener) == 1
    assert handoff_listener[0].control_socket is None


def test_emit_without_listener_is_noop() -> None:
    """``eval()`` outside the CLI has no listener — emission must be silent."""
    emit_launch_handoff(
        LaunchHandoff(run_id="r", pid=1, log_dir="/logs", control_socket=None)
    )


# --- inspect eval --json -----------------------------------------------------


@pytest.fixture
def fresh_display(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate the process-global display state the CLI path mutates.

    ``--json`` forces the display type to "none", which reconfigures the
    global rich console to quiet — both process-wide globals that would
    otherwise leak into later tests (and a previously-cached active
    display would leak *into* this test, breaking the parseable-stdout
    assertion). Reset the cache, and restore type + console after.
    """
    import rich

    import inspect_ai._display.core.active as active_mod
    import inspect_ai.util._display as display_mod

    monkeypatch.setattr(active_mod, "_active_display", None)
    monkeypatch.setattr(display_mod, "_display_type", display_mod._display_type)
    try:
        yield
    finally:
        rich.reconfigure(quiet=False)


TASK_FILE = """
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate


@task
def handoff_cli_task():
    return Task(dataset=[Sample(input="x", target="y")], solver=[generate()])
"""


class EvalJsonResult(NamedTuple):
    """Parsed output of an ``inspect eval --json`` CLI invocation."""

    records: list[dict]
    """Parsed stdout JSON lines (asserting each line parses)."""

    stderr: str
    """Raw stderr (diagnostics, redirected stray prints)."""


def _run_eval_json(
    short_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    task_file: str = TASK_FILE,
) -> EvalJsonResult:
    """Run ``inspect eval --json`` on a trivial task; return parsed stdout lines."""
    task_path = short_data_dir / "handoff_cli_task.py"
    task_path.write_text(task_file)
    log_dir = str(short_data_dir / "logs")

    # task file paths on the CLI resolve relative to the working directory
    # (absolute paths aren't supported by the task-file glob)
    monkeypatch.chdir(short_data_dir)

    runner = cli_runner()
    result = runner.invoke(
        eval_command,
        [
            task_path.name,
            "--model",
            "mockllm/model",
            "--log-dir",
            log_dir,
            "--json",
            *extra_args,
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # every stdout line (blank included) must be JSON — that's the
    # contract --json exists for. Assert on ``result.stdout`` (not
    # ``result.output``: in click >= 8.2 that is the *mixed* stdout+stderr
    # stream, so redirected stderr diagnostics would pollute it).
    records = [json.loads(line) for line in result.stdout.splitlines()]
    return EvalJsonResult(records=records, stderr=result.stderr)


def test_eval_json_emits_launch_then_done(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    records = _run_eval_json(short_data_dir, monkeypatch, []).records

    launch = records[0]
    assert launch["event"] == "launch"
    assert launch["run_id"]
    assert launch["eval_set_id"] is None
    assert launch["pid"] == os.getpid()
    assert launch["log_dir"] == str(short_data_dir / "logs")
    assert launch["control"]["socket_path"]

    done = records[-1]
    assert done["event"] == "done"
    assert done["run_id"] == launch["run_id"]
    assert len(done["logs"]) == 1
    log = done["logs"][0]
    assert log["task"] == "handoff_cli_task"
    assert log["status"] == "success"
    assert log["location"]


def test_eval_json_null_control_when_server_disabled(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    records = _run_eval_json(
        short_data_dir, monkeypatch, ["--ctl-server=false"]
    ).records
    launch = records[0]
    assert launch["event"] == "launch"
    assert launch["control"] is None
    assert records[-1]["event"] == "done"


def test_eval_json_overrides_trace(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """``--trace`` must not break the NDJSON contract.

    ``--trace`` promotes the display to "conversation", whose panels are
    written to stdout — and it also binds to ``INSPECT_EVAL_TRACE``, so a
    user with that exported would get a silently broken stream without
    ever typing the flag. ``--json`` clears it (``_run_eval_json`` fails
    on any non-JSON stdout line).
    """
    records = _run_eval_json(short_data_dir, monkeypatch, ["--trace"]).records
    assert records[0]["event"] == "launch"
    assert records[-1]["event"] == "done"


NOISY_TASK_FILE = """
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, solver

print("stray stdout at import time")


@solver
def noisy_solver():
    async def solve(state, generate):
        print("stray stdout from solver")
        return state

    return solve


@task
def handoff_cli_task():
    return Task(
        dataset=[Sample(input="x", target="y")], solver=[noisy_solver(), generate()]
    )
"""


def test_eval_json_redirects_stray_stdout_to_stderr(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """Bare ``print`` writers inside the run cannot corrupt the NDJSON stream.

    ``eval()`` internals (trailing scan status, cosmetic spacing above
    the task display) and user task/solver code all write to stdout with
    builtin ``print``, which the quiet rich console does not cover.
    ``--json`` runs the eval with stdout redirected to stderr, so those
    writers stay visible as diagnostics while stdout carries only the
    JSON records (``_run_eval_json`` fails on any non-JSON stdout line).
    """
    result = _run_eval_json(short_data_dir, monkeypatch, [], task_file=NOISY_TASK_FILE)
    assert result.records[0]["event"] == "launch"
    assert result.records[-1]["event"] == "done"
    assert "stray stdout at import time" in result.stderr
    assert "stray stdout from solver" in result.stderr


FD_LEAK_TASK_FILE = """
import subprocess

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, solver


@solver
def fd_leak_solver():
    async def solve(state, generate):
        subprocess.run(["echo", "FD1-LEAK"])
        return state

    return solve


@task
def handoff_cli_task():
    return Task(
        dataset=[Sample(input="x", target="y")], solver=[fd_leak_solver(), generate()]
    )
"""


def test_eval_json_redirects_subprocess_stdout_to_stderr(
    short_data_dir: Path,
) -> None:
    """Subprocess writers cannot corrupt the NDJSON stream either.

    A Python-level ``redirect_stdout`` only rebinds the ``sys.stdout``
    object — a subprocess spawned by solver code without capturing output
    inherits file descriptor 1 and writes straight into the stream. So
    ``--json`` redirects at the fd level (``os.dup2``). An in-process
    ``CliRunner`` invocation cannot exercise that path (its streams have
    no real fds), so this test runs the actual CLI in a subprocess.

    ``short_data_dir``'s monkeypatching is in-process only, so the spawned
    CLI is sandboxed via ``XDG_DATA_HOME`` instead — effective on Linux
    (where CI runs); on macOS platformdirs has no env override, so there
    the CLI's control/ACP discovery entries land in the real user data
    dir for the duration of the test (the normal production path, cleaned
    up on exit).
    """
    task_path = short_data_dir / "handoff_cli_task.py"
    task_path.write_text(FD_LEAK_TASK_FILE)
    log_dir = str(short_data_dir / "logs")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inspect_ai._cli.main",
            "eval",
            task_path.name,
            "--model",
            "mockllm/model",
            "--log-dir",
            log_dir,
            "--json",
        ],
        cwd=short_data_dir,
        env={**os.environ, "XDG_DATA_HOME": str(short_data_dir / "xdg")},
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr
    # every stdout line must parse — the leaked subprocess output would
    # land between the launch and done records without the fd redirect
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert records[0]["event"] == "launch"
    assert records[-1]["event"] == "done"
    assert "FD1-LEAK" in result.stderr


def test_debug_diagnostics_go_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fresh_display: None,
) -> None:
    """``--debug`` attach messages must not land on ``--json``'s stdout.

    ``process_common_options`` runs before the fd redirect in
    ``_eval_exec_json`` engages, so anything it printed to stdout would
    lead the NDJSON stream under ``--json --debug``.
    """
    from types import SimpleNamespace

    from inspect_ai._cli.common import CommonOptions, process_common_options

    monkeypatch.setitem(
        sys.modules,
        "debugpy",
        SimpleNamespace(listen=lambda port: None, wait_for_client=lambda: None),
    )
    options = CommonOptions(
        log_level="warning",
        log_dir="./logs",
        display="none",
        no_ansi=None,
        traceback_locals=False,
        env=None,
        debug=True,
        debug_port=5678,
        debug_errors=False,
    )

    process_common_options(options)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Waiting for debugger attach" in captured.err
    assert "Debugger attached" in captured.err


def test_eval_json_preflight_failure_reports_to_stderr(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """A failed launch under ``--json`` must still say why, on stderr.

    ``--json`` forces ``display="none"``, which quiets the global rich
    console — the excepthook's ``PrerequisiteError`` rendering goes
    through that console, so without re-rendering to stderr every common
    pre-flight failure (bad task path, missing API key, ...) would exit 1
    with no diagnostic at all, leaving the driving agent blind.
    """
    monkeypatch.chdir(short_data_dir)

    runner = cli_runner()
    result = runner.invoke(
        eval_command,
        ["definitely_not_here.py", "--model", "mockllm/model", "--json"],
    )

    assert result.exit_code != 0
    # stdout stays NDJSON-clean (no launch happened, so no records at all);
    # ``result.stdout``, not ``result.output`` — the latter mixes in stderr
    # on click >= 8.2, where this error message lands by design
    assert result.stdout.strip() == ""
    assert "No inspect tasks were found" in result.stderr


def test_eval_json_pre_eval_failure_reports_to_stderr(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """``PrerequisiteError``s raised before ``eval()`` honor the contract too.

    ``parse_run_config`` (and the config conflict checks in ``eval_exec``)
    raise while the global rich console still writes to *stdout* — the
    quiet reconfigure only happens once the display initializes inside
    ``eval()`` — so without command-level handling the excepthook would
    render the message onto the NDJSON stream, with stderr empty.
    """
    task_path = short_data_dir / "handoff_cli_task.py"
    task_path.write_text(TASK_FILE)
    bad_config = short_data_dir / "bad_run_config.yaml"
    bad_config.write_text("not_a_run_config_field: 1\n")
    monkeypatch.chdir(short_data_dir)

    runner = cli_runner()
    result = runner.invoke(
        eval_command,
        [
            task_path.name,
            "--model",
            "mockllm/model",
            "--json",
            "--run-config",
            str(bad_config),
        ],
    )

    assert result.exit_code != 0
    assert result.stdout.strip() == ""
    assert "Invalid run config" in result.stderr


def test_eval_json_prerequisite_message_survives_brackets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bracketed text in a ``PrerequisiteError`` reaches stderr verbatim.

    Many of these messages embed user-controlled paths (e.g.
    ``pretty_solver_file``), and rendering through a rich ``Console``
    would interpret ``[dev]`` as markup and silently swallow it.
    """
    message = (
        "The source file solvers/[dev]/solver.py "
        "does not contain any @solver functions."
    )

    with pytest.raises(SilentException):
        with _json_prerequisite_errors_to_stderr(True):
            raise PrerequisiteError(message)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


# --- inspect eval-set --json --------------------------------------------------


FAILING_TASK_FILE = """
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver


@solver
def failing_solver():
    async def solve(state, generate):
        raise RuntimeError("boom")

    return solve


@task
def handoff_cli_task():
    return Task(dataset=[Sample(input="x", target="y")], solver=[failing_solver()])
"""


def _run_eval_set_json(
    short_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    task_file: str = TASK_FILE,
    expected_exit_code: int = 0,
) -> EvalJsonResult:
    """Run ``inspect eval-set --json`` on a trivial task; return parsed stdout lines."""
    task_path = short_data_dir / "handoff_cli_task.py"
    task_path.write_text(task_file)
    log_dir = str(short_data_dir / "logs")

    monkeypatch.chdir(short_data_dir)

    runner = cli_runner()
    result = runner.invoke(
        eval_set_command,
        [
            task_path.name,
            "--model",
            "mockllm/model",
            "--log-dir",
            log_dir,
            "--json",
            *extra_args,
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == expected_exit_code, result.output
    records = [json.loads(line) for line in result.stdout.splitlines()]
    return EvalJsonResult(records=records, stderr=result.stderr)


def test_eval_set_json_emits_launch_then_done(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    records = _run_eval_set_json(short_data_dir, monkeypatch, []).records

    launch = records[0]
    assert launch["event"] == "launch"
    assert launch["run_id"]
    assert launch["eval_set_id"]
    assert launch["pid"] == os.getpid()
    assert launch["control"]["socket_path"]

    done = records[-1]
    assert done["event"] == "done"
    assert done["run_id"] == launch["run_id"]
    assert done["eval_set_id"] == launch["eval_set_id"]
    assert done["success"] is True
    assert len(done["logs"]) == 1
    log = done["logs"][0]
    assert log["task"] == "handoff_cli_task"
    assert log["status"] == "success"
    assert log["location"]


def test_eval_set_json_all_reused_emits_done_only(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """A set whose tasks are all complete runs no eval: ``done`` record only.

    The second invocation over the same log dir reuses every log without
    an ``eval()`` call, so no control server binds and no ``launch``
    record is emitted — the documented eval-set deviation from the
    "exactly one launch then one done" shape (agents must not read a
    missing ``launch`` line as a failed launch once ``done`` arrived).
    """
    first = _run_eval_set_json(short_data_dir, monkeypatch, []).records
    assert first[0]["event"] == "launch"

    second = _run_eval_set_json(short_data_dir, monkeypatch, []).records
    assert [record["event"] for record in second] == ["done"]
    done = second[0]
    assert done["success"] is True
    assert done["eval_set_id"] == first[0]["eval_set_id"]
    assert len(done["logs"]) == 1
    assert done["logs"][0]["status"] == "success"


def test_eval_set_json_reports_failure(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """A failed set still emits the ``done`` record, with ``success: false``.

    The exit code carries the same verdict (non-zero), so an agent can
    branch on either; per-task statuses in ``logs`` say what failed.
    """
    records = _run_eval_set_json(
        short_data_dir,
        monkeypatch,
        ["--retry-attempts", "0"],
        task_file=FAILING_TASK_FILE,
        expected_exit_code=1,
    ).records

    assert records[0]["event"] == "launch"
    done = records[-1]
    assert done["event"] == "done"
    assert done["success"] is False
    assert done["logs"][0]["status"] == "error"


FLAKY_TASK_FILE = """
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, solver


@solver
def flaky_solver():
    async def solve(state, generate):
        flag = Path("flaky_attempted.txt")
        if not flag.exists():
            flag.write_text("attempted")
            raise RuntimeError("first attempt fails")
        return state

    return solve


@task
def handoff_cli_task():
    return Task(
        dataset=[Sample(input="x", target="y")], solver=[flaky_solver(), generate()]
    )
"""


def test_eval_set_json_batch_retry_done_reports_last_launch(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """Legacy ``--no-retry-immediate``: ``done`` correlates with the last launch.

    Each batch retry is a fresh ``eval()`` call with a fresh ``run_id``,
    and each bind emits a fresh ``launch`` record — so the ``done``
    record must carry the *last* launch's ``run_id`` (the run that
    produced the final state, and the most recent ``launch`` an agent
    read), while ``eval_set_id`` stays stable across batches.
    """
    records = _run_eval_set_json(
        short_data_dir,
        monkeypatch,
        # retry_attempts counts total attempts (2 = one retry); retry_wait
        # treats 0 as unset (`retry_wait or 30`), so 1 is the fastest wait
        ["--no-retry-immediate", "--retry-attempts", "2", "--retry-wait", "1"],
        task_file=FLAKY_TASK_FILE,
    ).records

    launches = [record for record in records if record["event"] == "launch"]
    assert len(launches) == 2
    assert launches[0]["run_id"] != launches[1]["run_id"]
    assert launches[0]["eval_set_id"] == launches[1]["eval_set_id"]

    done = records[-1]
    assert done["event"] == "done"
    assert done["success"] is True
    assert done["run_id"] == launches[-1]["run_id"]
    assert done["eval_set_id"] == launches[0]["eval_set_id"]
    assert done["logs"][0]["status"] == "success"


def test_eval_set_json_preflight_failure_reports_to_stderr(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """Eval-set launch failures under ``--json`` report on stderr like eval's."""
    monkeypatch.chdir(short_data_dir)

    runner = cli_runner()
    result = runner.invoke(
        eval_set_command,
        [
            "definitely_not_here.py",
            "--model",
            "mockllm/model",
            "--log-dir",
            str(short_data_dir / "logs"),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert result.stdout.strip() == ""
    assert "No inspect tasks were found" in result.stderr


# --- inspect eval-retry --json -------------------------------------------------


def _run_eval_retry_json(short_data_dir: Path, log_files: list[str]) -> EvalJsonResult:
    """Run ``inspect eval-retry --json`` on prior logs; return parsed stdout lines."""
    runner = cli_runner()
    result = runner.invoke(
        eval_retry_command,
        [*log_files, "--log-dir", str(short_data_dir / "logs"), "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in result.stdout.splitlines()]
    return EvalJsonResult(records=records, stderr=result.stderr)


def test_eval_retry_json_emits_launch_then_done(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """``inspect eval-retry --json`` follows the eval contract: launch then done.

    The flaky task fails its first attempt (producing a retryable error
    log) and succeeds on retry, so the retry's ``done`` record reports a
    fresh run with ``status: success``.
    """
    first = _run_eval_json(
        short_data_dir, monkeypatch, [], task_file=FLAKY_TASK_FILE
    ).records
    failed = first[-1]["logs"][0]
    assert failed["status"] == "error"

    records = _run_eval_retry_json(short_data_dir, [failed["location"]]).records

    launch = records[0]
    assert launch["event"] == "launch"
    assert launch["run_id"] != first[0]["run_id"]
    assert launch["pid"] == os.getpid()
    assert launch["control"]["socket_path"]

    done = records[-1]
    assert done["event"] == "done"
    assert done["run_id"] == launch["run_id"]
    assert len(done["logs"]) == 1
    log = done["logs"][0]
    assert log["task"] == "handoff_cli_task"
    assert log["status"] == "success"
    assert log["location"]


def test_eval_retry_json_multi_file_emits_launch_per_file(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    """Each retried log file is its own eval: one ``launch`` record per file.

    ``eval_retry`` runs the files sequentially through separate
    ``eval()`` calls, each binding afresh — so agents see a fresh
    ``launch`` record per file (each superseding the previous), and the
    ``done`` record carries the *last* launch's ``run_id`` with one
    ``logs`` entry per retried task.
    """
    failed_locations = [
        _run_eval_json(
            short_data_dir, monkeypatch, [], task_file=FAILING_TASK_FILE
        ).records[-1]["logs"][0]["location"]
        for _ in range(2)
    ]

    records = _run_eval_retry_json(short_data_dir, failed_locations).records

    launches = [record for record in records if record["event"] == "launch"]
    assert len(launches) == 2
    assert launches[0]["run_id"] != launches[1]["run_id"]

    done = records[-1]
    assert done["event"] == "done"
    assert done["run_id"] == launches[-1]["run_id"]
    # the task fails again on retry — still a done record (exit 0), with
    # per-task statuses saying what failed
    assert [log["status"] for log in done["logs"]] == ["error", "error"]
