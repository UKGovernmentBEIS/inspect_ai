"""Tests for the synchronous launch handoff (``inspect eval --json``).

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
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

import inspect_ai
from inspect_ai import Task, task
from inspect_ai._cli.eval import eval_command
from inspect_ai._control.eval_state import get_eval_states
from inspect_ai._eval.handoff import (
    LaunchHandoff,
    emit_launch_handoff,
    set_launch_handoff_listener,
)
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate


@pytest.fixture(autouse=True)
def _isolate_active_model() -> Iterator[None]:
    """Keep ``eval``'s active-model contextvar from leaking across tests.

    These tests run ``eval`` *synchronously* in the test's own context
    (not a background thread), so without isolation the set persists
    after the call and leaks ``mockllm/model`` into later tests.
    """
    from inspect_ai.model._model import active_model_context_var

    token = active_model_context_var.set(active_model_context_var.get(None))
    try:
        yield
    finally:
        active_model_context_var.reset(token)


@pytest.fixture
def short_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Short data dir under /tmp so AF_UNIX paths fit in 104 chars.

    macOS pytest tmp_path lives under ``/private/var/folders/...`` which
    blows past the AF_UNIX limit. Patches both control and ACP discovery
    modules so neither subsystem writes outside the test's sandbox.
    """
    dirpath = Path(tempfile.mkdtemp(prefix="ctl_lh_", dir="/tmp"))

    def _stub(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("inspect_ai._control.discovery.inspect_data_dir", _stub)
    monkeypatch.setattr("inspect_ai.agent._acp.discovery.inspect_data_dir", _stub)
    try:
        yield dirpath
    finally:
        for p in sorted(dirpath.rglob("*"), reverse=True):
            try:
                p.unlink() if not p.is_dir() else p.rmdir()
            except OSError:
                pass
        try:
            dirpath.rmdir()
        except OSError:
            pass


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


def _runner() -> CliRunner:
    """A CliRunner that captures stderr separately across click versions.

    click < 8.2 mixes stderr into output unless ``mix_stderr=False``; click
    >= 8.2 removed the parameter and always captures stderr separately.
    Stderr must stay out of ``output`` here: the tests assert every stdout
    line parses as JSON, and log/warning lines would break that.
    """
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _run_eval_json(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, extra_args: list[str]
) -> list[dict]:
    """Run ``inspect eval --json`` on a trivial task; return parsed stdout lines."""
    task_path = short_data_dir / "handoff_cli_task.py"
    task_path.write_text(TASK_FILE)
    log_dir = str(short_data_dir / "logs")

    # task file paths on the CLI resolve relative to the working directory
    # (absolute paths aren't supported by the task-file glob)
    monkeypatch.chdir(short_data_dir)

    runner = _runner()
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
    lines = [line for line in result.output.splitlines() if line.strip()]
    # every stdout line must be JSON — that's the contract --json exists for
    return [json.loads(line) for line in lines]


def test_eval_json_emits_launch_then_done(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch, fresh_display: None
) -> None:
    records = _run_eval_json(short_data_dir, monkeypatch, [])

    launch = records[0]
    assert launch["event"] == "launch"
    assert launch["run_id"]
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
    records = _run_eval_json(short_data_dir, monkeypatch, ["--ctl-server=false"])
    launch = records[0]
    assert launch["event"] == "launch"
    assert launch["control"] is None
    assert records[-1]["event"] == "done"
