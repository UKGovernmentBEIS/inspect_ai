import functools
import logging
import os
import tempfile
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Literal, NoReturn, cast
from unittest import mock

import anyio
import pytest
from botocore.exceptions import ClientError

from inspect_ai import (
    Epochs,
    Task,
    TaskSource,
    eval,
    eval_async,
    eval_set,
    task,
    task_source,
)
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._util._async import tg_collect
from inspect_ai._util.dateutil import datetime_from_iso_format_safe, datetime_now_utc
from inspect_ai.approval._policy import ApprovalPolicyConfig, ApproverPolicyConfig
from inspect_ai.dataset import Sample
from inspect_ai.hooks._hooks import Hooks
from inspect_ai.scorer import Score, Scorer, Target, accuracy, match, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import DisplayType


def test_eval_epochs_sample_count():
    task = Task(dataset=[Sample(input="s1"), Sample(input="s2")])
    log = eval(task, model="mockllm/model", epochs=3)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 6  # 2 samples * 3 epochs


def test_eval_sample_records_turn_count_and_token_limit_usage():
    from typing import Generator

    from inspect_ai.model import get_model
    from inspect_ai.model._model_output import ModelOutput, ModelUsage
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util._limit import TokenLimit

    def repeat_forever(
        output: ModelOutput,
    ) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    @solver
    def generate_three_times():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            output = ModelOutput.from_content("mockllm/model", "hello")
            output.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
            model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
            for _ in range(3):
                state.output = await model.generate("hi")
            return state

        return solve

    # an "output"-metered limit so token_limit_usage (metered output tokens)
    # is distinguishable from total tokens
    task = Task(
        dataset=[Sample(input="s1")],
        solver=generate_three_times(),
        token_limit=TokenLimit(tokens=1000, type="output"),
    )
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]

    # three top-level generate() calls -> three turns
    assert sample.turn_count == 3
    # output-metered usage is 3 turns * 5 output tokens (not the 45 total)
    assert sample.token_limit_usage == 15
    # the configured ceiling and metering type are persisted alongside
    assert sample.token_limit == 1000
    assert sample.token_limit_type == "output"
    # the summary carries the same values
    summary = sample.summary()
    assert summary.turn_count == 3
    assert summary.token_limit_usage == 15
    assert summary.token_limit == 1000
    assert summary.token_limit_type == "output"


def test_eval_sample_token_limit_fields_none_without_limit():
    task = Task(dataset=[Sample(input="s1")])
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]

    # turns are counted regardless of configured limits
    assert sample.turn_count == 1
    # but token limit fields are None when no ceiling is configured
    assert sample.token_limit is None
    assert sample.token_limit_type is None
    assert sample.token_limit_usage is None
    # and so are the other per-sample limit ceilings
    assert sample.message_limit is None
    assert sample.time_limit is None


def test_eval_sample_records_message_and_time_limits():
    task = Task(
        dataset=[Sample(input="s1")],
        message_limit=10,
        time_limit=600,
    )
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]

    # the configured ceilings are persisted on the sample record
    assert sample.message_limit == 10
    assert sample.time_limit == 600
    # the summary carries the same values
    summary = sample.summary()
    assert summary.message_limit == 10
    assert summary.time_limit == 600


def test_dynamic_token_limit_updates_active_sample() -> None:
    from typing import Generator

    from inspect_ai.log._samples import sample_active
    from inspect_ai.model import get_model
    from inspect_ai.model._model_output import ModelOutput, ModelUsage
    from inspect_ai.solver import Generate, TaskState, solver

    observed: list[tuple[int | None, str | None, int | None]] = []

    def repeat_forever(
        output: ModelOutput,
    ) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    def observe() -> None:
        active = sample_active()
        assert active is not None
        observed.append(
            (active.token_limit, active.token_limit_type, active.token_limit_usage)
        )

    @solver
    def toggle_token_limit():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            output = ModelOutput.from_content("mockllm/model", "hello")
            output.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
            model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
            state.output = await model.generate("hi")
            observe()  # unlimited: whole group is None
            state.token_limit = 1000
            observe()  # enabling pushes ceiling, type, and current metered usage
            state.token_limit = None
            observe()  # disabling clears the group again
            return state

        return solve

    task = Task(dataset=[Sample(input="s1")], solver=toggle_token_limit())
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"

    assert observed == [
        (None, None, None),
        (1000, "all", 15),
        (None, None, None),
    ]


def test_eval_sample_limit_values_reflect_final_retry_attempt() -> None:
    from typing import Generator

    from inspect_ai.model import get_model
    from inspect_ai.model._model_output import ModelOutput, ModelUsage
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util._limit import TokenLimit, token_limit_usage, turn_count

    attempts: list[int] = []
    live_values_attempt2: list[tuple[int | None, int | None]] = []

    def repeat_forever(
        output: ModelOutput,
    ) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    @solver
    def fail_then_succeed():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            output = ModelOutput.from_content("mockllm/model", "hello")
            output.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
            model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
            attempts.append(len(attempts) + 1)
            if attempts[-1] == 1:
                # attempt 1: 2 generates then error
                for _ in range(2):
                    state.output = await model.generate("hi")
                raise RuntimeError("boom")
            # attempt 2: 5 generates then succeed
            for _ in range(5):
                state.output = await model.generate("hi")
                live_values_attempt2.append((turn_count(), token_limit_usage()))
            return state

        return solve

    task = Task(
        dataset=[Sample(input="s1")],
        solver=fail_then_succeed(),
        token_limit=TokenLimit(tokens=100000, type="output"),
    )
    log = eval(task, model="mockllm/model", retry_on_error=1)[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert attempts == [1, 2]

    # regression: attempt 1's limit snapshot must not leak into the retry --
    # live values advance during attempt 2 rather than freezing at (2, 10)
    assert live_values_attempt2 == [(1, 5), (2, 10), (3, 15), (4, 20), (5, 25)]
    # and the logged sample reflects the successful attempt, not attempt 1
    assert sample.turn_count == 5
    assert sample.token_limit_usage == 25


def _peak_model_concurrency(max_tasks: int | None) -> int:
    """Run one task against two models and return the peak concurrent models.

    A `record` solver brackets its work with enter/exit markers; the peak depth
    of overlapping enter/exit pairs is how many models ran at once.
    """
    from inspect_ai.solver import Generate, TaskState, solver

    events: list[str] = []

    @solver
    def record():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            events.append("enter")
            await anyio.sleep(0.2)
            events.append("exit")
            return state

        return solve

    task = Task(dataset=[Sample(input="x", target="y")], solver=[record()], name="t")
    eval(
        task,
        model=["mockllm/model", "mockllm/model2"],
        max_tasks=max_tasks,
        display="none",
    )

    depth = peak = 0
    for e in events:
        depth += 1 if e == "enter" else -1
        peak = max(peak, depth)
    return peak


@pytest.mark.parametrize("vscode", [False, True])
def test_eval_display_follows_display_arg_across_evals(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    vscode: bool,
) -> None:
    import inspect_ai._display.core.rich as display_rich

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: vscode)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())

    eval(task, model="mockllm/model", display="plain", log_dir=str(tmp_path))
    assert "Log:" in capsys.readouterr().out

    eval(task, model="mockllm/model", display="none", log_dir=str(tmp_path))
    assert capsys.readouterr().out == ""

    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))
    assert "Log:" in capsys.readouterr().out


def test_eval_display_plain_then_rich_shows_live_progress(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import rich

    import inspect_ai._display.core.rich as display_rich

    # a VS Code terminal, where rich_initialise leaves the console's colors
    # and terminal detection alone
    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: True)
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.delenv("TTY_INTERACTIVE", raising=False)
    rich.reconfigure()
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())

    eval(task, model="mockllm/model", display="plain", log_dir=str(tmp_path))
    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))

    # rich.live draws progress only on a terminal, and in place only when
    # interactive (plain turns both off)
    console = rich.get_console()
    assert console.is_terminal and console.is_interactive


@pytest.mark.parametrize("vscode", [False, True])
def test_eval_display_none_then_log_shows_log_output(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    vscode: bool,
) -> None:
    import inspect_ai._display.core.rich as display_rich
    from inspect_ai._util.logger import _logHandler

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: vscode)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())

    eval(task, model="mockllm/model", display="none", log_dir=str(tmp_path))
    capsys.readouterr()

    # logging is configured once per process, so set it up as an INFO first
    # eval with the default rich format would have
    handler = _logHandler["handler"]
    assert handler is not None
    monkeypatch.setattr(handler, "display_level", logging.INFO)
    monkeypatch.setattr(handler, "logger_format", "rich")
    caplog.set_level(logging.INFO)

    eval(task, model="mockllm/model", display="log", log_dir=str(tmp_path))
    assert "Running 1 tasks" in capsys.readouterr().out


@pytest.mark.parametrize(
    "first,second",
    [("rich", "plain"), ("plain", "rich"), ("plain", "none"), ("rich", "log")],
)
def test_eval_display_change_keeps_console_contexts(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    first: DisplayType,
    second: DisplayType,
) -> None:
    import rich
    from rich.theme import Theme

    import inspect_ai._display.core.rich as display_rich

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())
    eval(task, model="mockllm/model", display=first, log_dir=str(tmp_path))

    console = rich.get_console()
    console.record = True
    with console.use_theme(Theme({"note": "bold"})):
        console.print("recorded before the change")
        with console.capture() as capture:
            console.print("captured before the change")
            eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))
    # the "none" display's quiet console drops captured output, as it does in
    # a fresh process
    shown = second != "none"
    assert ("captured before the change" in capture.get()) == shown
    assert "recorded before the change" in console.export_text()

    # the capture no longer holds output back
    capsys.readouterr()
    console.print("after the change")
    assert ("after the change" in capsys.readouterr().out) == shown


def test_eval_display_change_keeps_console_settings_made_between_evals(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import rich

    import inspect_ai._display.core.rich as display_rich

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())
    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))

    rich.reconfigure(width=120, quiet=True)
    eval(task, model="mockllm/model", display="log", log_dir=str(tmp_path))

    console = rich.get_console()
    assert console.width == 120
    assert console.quiet


def test_eval_display_change_keeps_console_replaced_between_evals(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import io

    import rich

    import inspect_ai._display.core.rich as display_rich

    # a VS Code terminal, where the rich display keeps the user's console
    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: True)
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.delenv("TTY_COMPATIBLE", raising=False)
    monkeypatch.delenv("TTY_INTERACTIVE", raising=False)
    rich.reconfigure(force_terminal=True, force_interactive=True)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())
    eval(task, model="mockllm/model", display="plain", log_dir=str(tmp_path))

    # a console on a buffer is not a terminal, as plain also sets
    rich.reconfigure(file=io.StringIO())
    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))

    console = rich.get_console()
    assert not console.is_terminal
    assert not console.is_interactive


def test_eval_first_display_after_display_type_query_replaces_console(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util._display import display_type

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)

    # as get_model().generate() does outside an eval, without building a display
    display_type()
    rich.get_console().record = True
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())
    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))

    # the first display replaces the console, as in a process with no query
    assert not rich.get_console().record


@pytest.mark.parametrize(
    "first,second", [("plain", "rich"), ("rich", "plain"), ("rich", "rich")]
)
def test_eval_display_change_shows_input_screen_inside_capture(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    first: DisplayType,
    second: DisplayType,
) -> None:
    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util import input_screen

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)

    @solver
    def ask() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with input_screen() as console:
                console.print("PROMPT")
            return state

        return solve

    task = Task(dataset=[Sample(input="hi", target="hi")], solver=ask())
    eval(task, model="mockllm/model", display=first, log_dir=str(tmp_path))
    capsys.readouterr()

    # a capture kept across a display type change doesn't hide the prompt;
    # without a change it behaves as before
    with rich.get_console().capture() as capture:
        eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))
    changed = first != second
    assert ("PROMPT" in capsys.readouterr().out) == changed
    assert ("PROMPT" in capture.get()) != changed


@pytest.mark.parametrize("vscode,second", [(False, "log"), (True, "rich")])
def test_display_change_after_full_scoring_detects_settings_for_redirected_stdout(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    vscode: bool,
    second: DisplayType,
) -> None:
    import io
    import sys

    import rich
    from rich.console import Console

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai import score
    from inspect_ai._display.core import active
    from inspect_ai._display.textual.display import TextualDisplay
    from inspect_ai.util import _display

    class TerminalOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: vscode)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name in ["TTY_COMPATIBLE", "TTY_INTERACTIVE", "FORCE_COLOR", "NO_COLOR"]:
        monkeypatch.delenv(name, raising=False)
    task = Task(dataset=[Sample(input="hi", target="hi")])
    [log] = eval(task, model="mockllm/model", display="none", log_dir=str(tmp_path))

    # a new process on a terminal scores with the full display, which shows
    # progress without setting the console up, then redirects stdout
    monkeypatch.setattr(active, "_active_display", None)
    monkeypatch.setattr(_display, "_display_type", None)
    monkeypatch.setattr(display_rich, "_console_settings", None)
    monkeypatch.setattr(display_rich, "_reconfigure_in_place", False)
    monkeypatch.setattr(sys, "stdout", TerminalOutput())
    monkeypatch.setattr(rich.get_console(), "__dict__", Console().__dict__)
    score(log, match(), display="full")
    assert isinstance(active.active_display(), TextualDisplay)

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))

    console = rich.get_console()
    assert console.color_system is None
    assert not console.is_interactive


@pytest.mark.parametrize("to_terminal", [False, True])
@pytest.mark.parametrize(
    "first,vscode,second",
    [
        ("plain", False, "log"),
        ("plain", True, "rich"),
        ("log", True, "rich"),
        ("log", True, "conversation"),
    ],
)
def test_eval_display_change_detects_settings_for_redirected_stdout(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    first: DisplayType,
    vscode: bool,
    second: DisplayType,
    to_terminal: bool,
) -> None:
    import io
    import sys

    import rich

    import inspect_ai._display.core.rich as display_rich

    class TerminalOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: vscode)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name in ["TTY_COMPATIBLE", "TTY_INTERACTIVE", "FORCE_COLOR", "NO_COLOR"]:
        monkeypatch.delenv(name, raising=False)
    task = Task(dataset=[Sample(input="hi", target="hi")])

    # an eval with stdout on a terminal (or a buffer), then stdout redirected
    # to a buffer (or a terminal) for a display that keeps the console's color
    # and interactive settings
    first_output = io.StringIO() if to_terminal else TerminalOutput()
    second_output = TerminalOutput() if to_terminal else io.StringIO()
    monkeypatch.setattr(sys, "stdout", first_output)
    rich.reconfigure()
    eval(task, model="mockllm/model", display=first, log_dir=str(tmp_path))
    monkeypatch.setattr(sys, "stdout", second_output)
    eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))

    console = rich.get_console()
    assert (console.color_system is not None) == to_terminal
    assert console.is_interactive == to_terminal


@pytest.mark.parametrize("second", ["rich", "conversation"])
def test_eval_display_change_restores_cursor_after_captured_eval(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    second: DisplayType,
) -> None:
    import io

    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util import input_screen

    class TerminalOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name in ["TTY_COMPATIBLE", "TTY_INTERACTIVE", "FORCE_COLOR", "NO_COLOR"]:
        monkeypatch.delenv(name, raising=False)

    @solver
    def ask() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with input_screen() as console:
                console.print("PROMPT")
            return state

        return solve

    task = Task(dataset=[Sample(input="hi", target="hi")], solver=ask())
    eval(task, model="mockllm/model", display="plain", log_dir=str(tmp_path))

    output = TerminalOutput()
    rich.reconfigure(file=output)
    with rich.get_console().capture():
        eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))

    # whatever the terminal saw leaves the cursor visible
    shown = output.getvalue()
    assert shown.rfind("\x1b[?25l") < shown.rfind("\x1b[?25h") or (
        "\x1b[?25l" not in shown
    )


def test_eval_display_change_shows_input_cursor_inside_capture(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import io

    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util import input_screen

    class TerminalOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name in ["TTY_COMPATIBLE", "TTY_INTERACTIVE", "FORCE_COLOR", "NO_COLOR"]:
        monkeypatch.delenv(name, raising=False)

    @solver
    def ask() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with rich.get_console().capture():
                with input_screen() as console:
                    console.print("PROMPT")
            return state

        return solve

    task = Task(dataset=[Sample(input="hi", target="hi")], solver=ask())
    eval(task, model="mockllm/model", display="plain", log_dir=str(tmp_path))

    output = TerminalOutput()
    rich.reconfigure(file=output)
    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))

    # the progress display hides the cursor, and the input screen shows it
    # again on the terminal before its prompt
    shown = output.getvalue().split("PROMPT")[0]
    assert shown.rfind("\x1b[?25h") > shown.rfind("\x1b[?25l")


@pytest.mark.parametrize("record_event", [True, False])
@pytest.mark.parametrize("first,second", [("plain", "rich"), ("rich", "rich")])
def test_eval_display_change_keeps_recording_through_input_screen(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    first: DisplayType,
    second: DisplayType,
    record_event: bool,
) -> None:
    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util import input_screen

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)

    @solver
    def ask() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with input_screen(record_event=record_event) as console:
                console.print("PROMPT")
            return state

        return solve

    task = Task(dataset=[Sample(input="hi", target="hi")], solver=ask())
    eval(task, model="mockllm/model", display=first, log_dir=str(tmp_path))

    console = rich.get_console()
    console.record = True
    console.print("EARLIER")
    [log] = eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))

    if first == second:
        # without a change the input screen ends the recording, as before
        assert not console.record
        return

    # the recording kept across the change keeps its contents and gains the
    # interaction, which the event holds on its own
    assert console.record
    recorded = console.export_text()
    assert "EARLIER" in recorded and "PROMPT" in recorded
    assert log.samples
    inputs = [e for e in log.samples[0].events if e.event == "input"]
    if record_event:
        assert len(inputs) == 1
        assert "PROMPT" in inputs[0].input and "EARLIER" not in inputs[0].input
    else:
        assert not inputs


def test_eval_display_change_after_log_display_keeps_console(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import rich

    import inspect_ai._display.core.rich as display_rich

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())

    # the log display doesn't set the console up, the plain display after it
    # sets only its display settings
    eval(task, model="mockllm/model", display="log", log_dir=str(tmp_path))
    rich.get_console().record = True
    eval(task, model="mockllm/model", display="plain", log_dir=str(tmp_path))

    assert rich.get_console().record


def test_eval_display_change_detects_settings_for_the_console_output(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import io

    import rich

    import inspect_ai._display.core.rich as display_rich

    class TerminalOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name in ["TTY_COMPATIBLE", "TTY_INTERACTIVE", "FORCE_COLOR", "NO_COLOR"]:
        monkeypatch.delenv(name, raising=False)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())
    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))

    # a terminal of the user's own, while stdout is pytest's capture
    rich.reconfigure(file=TerminalOutput())
    eval(task, model="mockllm/model", display="conversation", log_dir=str(tmp_path))

    console = rich.get_console()
    assert console.is_interactive
    assert console.color_system is not None


@pytest.mark.parametrize("first,second", [("rich", "plain"), ("plain", "none")])
def test_eval_display_change_keeps_console_options_set_between_evals(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    first: DisplayType,
    second: DisplayType,
) -> None:
    import io

    import rich
    from rich.theme import Theme

    import inspect_ai._display.core.rich as display_rich

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())
    eval(task, model="mockllm/model", display=first, log_dir=str(tmp_path))

    output = io.StringIO()
    rich.reconfigure(file=output, theme=Theme({"note": "bold"}), soft_wrap=True)
    eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))

    console = rich.get_console()
    assert console.file is output
    assert console.soft_wrap
    assert str(console.get_style("note")) == "bold"


def _display_state() -> dict[str, Any]:
    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai._display.core.active import active_display

    console = rich.get_console()
    return {name: getattr(console, name) for name in display_rich._DISPLAY_SETTINGS} | {
        "display": type(active_display()).__name__
    }


_DISPLAY_TYPES: list[DisplayType] = ["plain", "rich", "none", "log"]


@pytest.mark.parametrize("vscode", [False, True])
@pytest.mark.parametrize(
    "first,second",
    [(a, b) for a in _DISPLAY_TYPES for b in _DISPLAY_TYPES if a != b],
)
def test_eval_display_change_matches_fresh_display(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    vscode: bool,
    first: DisplayType,
    second: DisplayType,
) -> None:
    import rich
    from rich.console import Console

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai._display.core import active
    from inspect_ai.util import _display

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: vscode)
    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())

    eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))
    fresh = _display_state()

    # start again as a new process, then change from the first display
    monkeypatch.setattr(active, "_active_display", None)
    monkeypatch.setattr(_display, "_display_type", None)
    monkeypatch.setattr(display_rich, "_console_settings", None)
    monkeypatch.setattr(display_rich, "_reconfigure_in_place", False)
    monkeypatch.setattr(rich.get_console(), "__dict__", Console().__dict__)
    eval(task, model="mockllm/model", display=first, log_dir=str(tmp_path))
    eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))

    assert _display_state() == fresh


def test_score_without_display_keeps_display_type(
    fresh_display: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from inspect_ai import score
    from inspect_ai.util._display import display_type

    task = Task(dataset=[Sample(input="hi", target="hi")], scorer=match())
    [log] = eval(task, model="mockllm/model", display="none", log_dir=str(tmp_path))
    capsys.readouterr()

    score(log, match(), action="append")
    assert display_type() == "none"
    assert capsys.readouterr().out == ""


def test_display_type_change_during_eval_keeps_running_display(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util._display import display_type, init_display_type

    # outside VS Code, where rich_initialise gives the running display its own
    # console state
    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)

    @solver
    def change_display() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # as eval(display="log") does when called from another thread
            init_display_type("log")
            return state

        return solve

    task = Task(dataset=[Sample(input="hi")], solver=change_display())
    log = eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))[0]
    assert log.status == "success"
    assert display_type() == "rich"
    assert "Ignoring display type 'log'" in caplog.text


def test_display_type_change_after_display_type_query_inside_status(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util._display import display_type

    # a VS Code terminal, where the rich display keeps the console
    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: True)
    monkeypatch.setenv("INSPECT_DISPLAY", "plain")

    # as get_model().generate() does outside an eval, without building a display
    display_type()
    task = Task(dataset=[Sample(input="hi", target="hi")])
    with rich.get_console().status("working"):
        log = eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))
    assert log[0].status == "success"
    assert display_type() == "rich"


@pytest.mark.parametrize("second", ["plain", "none"])
def test_display_type_change_inside_screen_keeps_terminal_cleanup(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    second: DisplayType,
) -> None:
    import io

    import rich

    import inspect_ai._display.core.rich as display_rich
    from inspect_ai.util._display import display_type

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    task = Task(dataset=[Sample(input="hi", target="hi")])
    eval(task, model="mockllm/model", display="rich", log_dir=str(tmp_path))

    output = io.StringIO()
    rich.reconfigure(file=output, force_terminal=True)
    with rich.get_console().screen():
        eval(task, model="mockllm/model", display=second, log_dir=str(tmp_path))

    # the screen leaves the alternate screen and shows the cursor on exit
    assert output.getvalue().endswith("\x1b[?1049l\x1b[?25h")
    assert display_type() == "rich"
    assert f"Ignoring display type '{second}'" in caplog.text


def test_display_type_change_warning_names_requested_type_on_trio(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import rich

    from inspect_ai.util import _display

    task = Task(dataset=[Sample(input="hi", target="hi")])
    eval(task, model="mockllm/model", display="plain", log_dir=str(tmp_path))

    # trio runs "full" as "rich", which the warning shouldn't name instead
    monkeypatch.setattr(_display, "configured_async_backend", lambda: "trio")
    with rich.get_console().status("working"):
        _display.init_display_type("full")

    assert _display.display_type() == "plain"
    assert "Ignoring display type 'full'" in caplog.text


@pytest.mark.parametrize("inner_display", ["plain", "full", None])
def test_display_type_change_during_score_keeps_running_display(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    inner_display: DisplayType | None,
) -> None:
    import inspect_ai._display.core.rich as display_rich
    from inspect_ai import score
    from inspect_ai.util._display import display_type

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)

    task = Task(dataset=[Sample(input="hi", target="hi")])
    [log] = eval(task, model="mockllm/model", display="none", log_dir=str(tmp_path))

    @scorer(metrics=[accuracy()])
    def nested_score() -> Scorer:
        async def score_sample(state: TaskState, target: Target) -> Score:
            await anyio.to_thread.run_sync(
                lambda: score(log, match(), display=inner_display)
            )
            return Score(value=1)

        return score_sample

    scored = score(log, nested_score(), display="rich")
    assert scored.results is not None
    assert scored.results.scores[-1].name == "nested_score"
    assert display_type() == "rich"
    # the warning names the requested type (not the worker thread's "plain"),
    # and without a display argument the worker thread asks for the current type
    if inner_display is None:
        assert "Ignoring display type" not in caplog.text
    else:
        assert f"Ignoring display type '{inner_display}'" in caplog.text


@pytest.mark.parametrize("utility", ["convert", "chunked", "bundle"])
@pytest.mark.parametrize("first", ["rich", "conversation", "full", "none", "log"])
def test_display_type_change_during_log_utility_progress(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    first: DisplayType,
    utility: str,
) -> None:
    import inspect_ai._display.core.rich as display_rich
    import inspect_ai.log._bundle as bundle
    import inspect_ai.log._convert as convert
    import inspect_ai.log._recorders.chunked.convert as chunked
    from inspect_ai._display import display
    from inspect_ai.util._display import display_type, init_display_type

    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)

    log_dir = tmp_path / "logs"
    task = Task(dataset=[Sample(input="hi", target="hi")])
    eval(task, model="mockllm/model", display=first, log_dir=str(log_dir))

    def change_display(module: Any, name: str) -> None:
        original = getattr(module, name)

        def during_progress(*args: Any, **kwargs: Any) -> Any:
            # as eval(display="plain") does when started on another thread
            init_display_type("plain")
            display()
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, during_progress)

    output_dir = str(tmp_path / "output")
    if utility == "convert":
        change_display(convert, "write_eval_log")
        convert.convert_eval_logs(str(log_dir), "json", output_dir)
    elif utility == "chunked":
        change_display(chunked, "_convert_log_file")
        chunked.convert_eval_logs_to_chunked(str(log_dir), output_dir)
    else:
        change_display(bundle, "write_log_listing")
        bundle.bundle_log_dir(str(log_dir), output_dir)
    assert len(os.listdir(output_dir)) > 0

    # the Rich backed displays have a live progress display open, the log
    # display doesn't
    if first == "log":
        assert display_type() == "plain"
    else:
        assert display_type() == first
        assert "Ignoring display type 'plain'" in caplog.text


def test_max_tasks_bounds_concurrent_models_single_task():
    # Regression for #4195: a single task definition fanned across models must
    # honor max_tasks. max_tasks=1 runs model-by-model; unset runs them all.
    assert _peak_model_concurrency(max_tasks=1) == 1
    assert _peak_model_concurrency(max_tasks=None) == 2


@pytest.mark.anyio
async def test_no_concurrent_eval_async():
    tasks = [
        Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
        for i in range(0, 2)
    ]

    with pytest.raises(RuntimeError):
        await tg_collect(
            [
                functools.partial(eval_async, task, model="mockllm/model")
                for task in tasks
            ]
        )


def _raise_wrapped() -> NoReturn:
    raise RuntimeError("wrapped")


@solver
def _fail_while_handling() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        try:
            raise ValueError("context")
        except ValueError:
            _raise_wrapped()

    return solve


async def test_eval_async_debug_errors_keeps_error_context(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="wrapped") as excinfo:
        await eval_async(
            Task(dataset=[Sample(input="x")], solver=_fail_while_handling()),
            model="mockllm/model",
            log_dir=str(tmp_path),
            debug_errors=True,
            ctl_server=False,
        )
    error = excinfo.value
    assert repr(error.__context__) == "ValueError('context')"
    assert not error.__suppress_context__
    text = "".join(traceback.format_exception(error))
    assert "Exception Group Traceback" not in text
    assert text.count("RuntimeError: wrapped") == 1


def test_eval_config_override():
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        message_limit=10,
        epochs=Epochs(2, "at_least_1"),
        fail_on_error=True,
        scorer=match(),
    )

    log = eval(deepcopy(task), model="mockllm/model")[0]
    assert log.eval.config.message_limit == 10
    assert log.eval.config.epochs == 2
    assert log.eval.config.epochs_reducer == ["at_least_1"]
    assert log.eval.config.fail_on_error is True

    log = eval(
        deepcopy(task),
        message_limit=5,
        epochs=Epochs(5, "at_least_3"),
        fail_on_error=0.5,
        model="mockllm/model",
    )[0]
    assert log.eval.config.message_limit == 5
    assert log.eval.config.epochs == 5
    assert log.eval.config.epochs_reducer == ["at_least_3"]
    assert log.eval.config.fail_on_error == 0.5


def test_eval_config_overrides_do_not_mutate_reused_task():
    from inspect_ai.model._model_data.model_data import ModelCost, ModelInfo
    from inspect_ai.model._model_info import clear_model_info_cache, set_model_info

    set_model_info(
        "mockllm/model",
        ModelInfo(
            cost=ModelCost(
                input=1.0,
                output=1.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    task = Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())

    try:
        log = eval(
            task,
            model="mockllm/model",
            epochs=Epochs(2, "mean"),
            message_limit=10,
            token_limit=500,
            turn_limit=3,
            time_limit=60,
            working_limit=60,
            cost_limit=5.0,
            fail_on_error=False,
            continue_on_fail=True,
            score_on_error=True,
        )[0]
    finally:
        clear_model_info_cache()

    assert log.eval.config.epochs == 2
    assert log.eval.config.epochs_reducer == ["mean"]
    assert log.eval.config.message_limit == 10
    assert log.eval.config.token_limit == 500
    assert log.eval.config.turn_limit == 3
    assert log.eval.config.time_limit == 60
    assert log.eval.config.working_limit == 60
    assert log.eval.config.cost_limit == 5.0
    assert log.eval.config.fail_on_error is False
    assert log.eval.config.continue_on_fail is True
    assert log.eval.config.score_on_error is True

    assert task.epochs is None
    assert task.epochs_reducer is None
    assert task.message_limit is None
    assert task.token_limit is None
    assert task.token_limit_type is None
    assert task.turn_limit is None
    assert task.time_limit is None
    assert task.working_limit is None
    assert task.cost_limit is None
    assert task.fail_on_error is None
    assert task.continue_on_fail is None
    assert task.score_on_error is None

    followup = eval(task, model="mockllm/model")[0]
    assert followup.eval.config.epochs == 1
    assert followup.eval.config.epochs_reducer is None
    assert followup.eval.config.message_limit is None
    assert followup.eval.config.token_limit is None
    assert followup.eval.config.token_limit_type is None
    assert followup.eval.config.turn_limit is None
    assert followup.eval.config.time_limit is None
    assert followup.eval.config.working_limit is None
    assert followup.eval.config.cost_limit is None
    assert followup.eval.config.fail_on_error is True
    assert followup.eval.config.continue_on_fail is False
    assert followup.eval.config.score_on_error is False


def test_eval_level_message_limit_not_reused_by_task_object():
    from inspect_ai.solver import Generate, TaskState, solver

    @solver
    def two_generates():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state = await generate(state)
            state.messages.append(state.user_prompt)
            return await generate(state)

        return solve

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[two_generates()],
        scorer=match(numeric=True),
    )

    limited = eval(task, model="mockllm/model", message_limit=1, fail_on_error=False)[0]
    assert limited.samples is not None
    assert limited.samples[0].limit is not None
    assert limited.samples[0].limit.type == "message"
    assert task.message_limit is None

    followup = eval(task, model="mockllm/model")[0]
    assert followup.eval.config.message_limit is None
    assert followup.samples is not None
    assert followup.samples[0].limit is None


def test_eval_approval_override():
    eval_approval = ApprovalPolicyConfig(
        approvers=[
            ApproverPolicyConfig(name="human", tools="human_tool"),
            ApproverPolicyConfig(name="auto", tools="auto_tool"),
        ]
    )
    task = Task(dataset=[Sample(input="Say Hello", target="Hello")], approval="auto")
    log = eval(
        deepcopy(task),
        model="mockllm/model",
        approval=eval_approval,
    )[0]
    assert log.eval.config.approval == eval_approval


def test_eval_sandbox_init_when_first_task_has_no_sandbox():
    """Check that Sandbox initialization runs when ANY task has a sandbox, not just the first.

    Startup is asserted via a spy rather than a docker task whose init
    crashes when skipped: a local sandbox keeps the regression coverage
    (the gating logic is sandbox-type agnostic) without docker's ~40s of
    container lifecycle in CI.
    """
    from inspect_ai._eval.run import SandboxManager

    with mock.patch.object(
        SandboxManager, "start", autospec=True, side_effect=SandboxManager.start
    ) as start_spy:
        results = eval(
            tasks=[
                Task(dataset=[Sample(input="x")], name="no_sandbox"),
                Task(
                    dataset=[Sample(input="x")], sandbox="local", name="local_sandbox"
                ),
            ],
            model="mockllm/model",
            max_tasks=2,
        )
    assert len(results) == 2
    for r in results:
        assert r.status == "success", f"{r.eval.task}: {r.error}"
    start_spy.assert_called_once()


# -- unconsumed task_args warning (#4194) ------------------------------------
# task_args only apply to tasks resolved by specification (name, file,
# TaskInfo, task function/class, or cwd auto-discovery). When every task is a
# Task instance passed directly, task_args are silently ignored — eval() and
# eval_set() should warn.

TASK_ARGS_WARNING_SNIPPET = "will not be applied"


@task
def task_args_warning_check(task_arg: str = "default") -> Task:
    return Task(dataset=[Sample(input=f"{task_arg}: test input")])


def _task_args_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if TASK_ARGS_WARNING_SNIPPET in r.message]


def test_task_instance_with_task_args_warns(caplog) -> None:
    log = eval(
        task_args_warning_check(),
        task_args={"task_arg": "custom"},
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    records = _task_args_warnings(caplog)
    assert len(records) == 1, "expected exactly one unconsumed task_args warning"
    assert "task_arg" in records[0].message


def test_task_instance_multiple_models_warns_once(caplog) -> None:
    # resolve_tasks runs once per model; the warning is gated to the first
    # model so it fires exactly once regardless of the model count
    logs = eval(
        task_args_warning_check(),
        task_args={"task_arg": "custom"},
        model=["mockllm/model", "mockllm/model"],
    )
    assert all(log.status == "success" for log in logs)
    assert len(_task_args_warnings(caplog)) == 1


def test_string_task_with_task_args_no_warning(caplog) -> None:
    log = eval(
        "task_args_warning_check",
        task_args={"task_arg": "custom"},
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    # args actually applied
    assert log.eval.task_args["task_arg"] == "custom"
    assert not _task_args_warnings(caplog)


def test_task_instance_without_task_args_no_warning(caplog) -> None:
    log = eval(task_args_warning_check(), model="mockllm/model")[0]
    assert log.status == "success"
    assert not _task_args_warnings(caplog)


def test_eval_set_task_instance_warns_once(caplog) -> None:
    # eval_set re-enters resolution internally with ResolvedTask objects;
    # the warning must fire exactly once, not per resolution pass
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=task_args_warning_check(),
            task_args={"task_arg": "custom"},
            model="mockllm/model",
            log_dir=log_dir,
        )
    assert success
    records = _task_args_warnings(caplog)
    assert len(records) == 1, (
        f"expected exactly one unconsumed task_args warning, got {len(records)}"
    )


class _SeedTasks(TaskSource):
    def __init__(self, count: int) -> None:
        self._count = count

    def initial_tasks(self) -> list[Task]:
        return [
            Task(dataset=[Sample(input=f"t{i}")], name=f"t{i}")
            for i in range(self._count)
        ]

    async def next_tasks(self) -> list[Task] | None:
        return None


@task_source(name="task_args_warning_source")
def task_args_warning_source(count: int = 1) -> TaskSource:
    return _SeedTasks(count)


def test_task_source_with_task_args_no_warning(caplog) -> None:
    # task_args are consumed by the source (resolve_task_source) to build its
    # seed; resolving the seed Task instances must not false-warn (#4194)
    logs = eval(
        "task_args_warning_source",
        task_args={"count": 2},
        model="mockllm/model",
        display="none",
    )
    assert all(log.status == "success" for log in logs)
    assert len(logs) == 2  # count applied by the source -> two seed tasks
    assert not _task_args_warnings(caplog)


# A failed log write must not tear down the whole run. Log writes at task
# start (the log_start() header flush) and the error-status log_finish() are
# the only exceptions that escape task_run(). If log storage (e.g. S3) is
# unreachable at that moment, the failure previously propagated out of
# _run_task() and crashed the entire eval — cancelling every sibling task. It
# should instead surface as an errored EvalLog so the task can be retried like
# any other task error.


@task
def log_write_failure_task() -> Task:
    return Task(
        dataset=[Sample(id=1, input="x", target="y")], name="log_write_failure_task"
    )


def _skew_error() -> ClientError:
    return ClientError(
        cast(
            Any,
            {
                "Error": {
                    "Code": "RequestTimeTooSkewed",
                    "Message": "The difference between the request time and the "
                    "current time is too large.",
                },
                "ResponseMetadata": {"RequestId": "request-1"},
            },
        ),
        "PutObject",
    )


def test_failed_log_start_returns_errored_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A permanently failing log_start yields an errored log, not a crash."""

    async def failing_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> None:
        raise _skew_error()

    monkeypatch.setattr(TaskLogger, "log_start", failing_log_start)

    logs = eval(
        log_write_failure_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )

    assert len(logs) == 1
    assert logs[0].status == "error"
    assert logs[0].error is not None
    assert "RequestTimeTooSkewed" in logs[0].error.message
    assert logs[0].location  # the path the failed write was destined for


async def test_running_sample_buffer_row_carries_its_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The realtime row opened for a running sample records when it started.

    Crash recovery dates a still-running sample from its row, and decides by
    that start whether the row is newer than a record the log inherited, so
    a row without one would lose to the inherited record (#5343 review).
    """
    from inspect_ai.log._recorders.buffer import database as database_module
    from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase

    monkeypatch.setattr(database_module, "resolve_db_dir", lambda _: tmp_path / "db")
    buffers: list[SampleBufferDatabase] = []
    init = TaskLogger.init

    async def track_init(logger: TaskLogger) -> None:
        await init(logger)
        assert logger.buffer_db is not None
        buffers.append(logger.buffer_db)

    monkeypatch.setattr(TaskLogger, "init", track_init)
    rows_while_running: list[str | None] = []

    @solver
    def inspect_row() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            samples = buffers[-1].get_samples()
            assert samples is not None and samples != "NotModified"
            (row,) = samples.samples
            assert row.completed_at is None
            rows_while_running.append(row.started_at)
            return state

        return solve

    try:
        admitted_no_earlier_than = datetime_now_utc()
        logs = await eval_async(
            Task(dataset=[Sample(id=1, input="x", target="x")], solver=inspect_row()),
            model="mockllm/model",
            log_dir=str(tmp_path / "logs"),
            ctl_server=False,
        )
        assert logs[0].status == "success"
        (started_at,) = rows_while_running
        assert started_at is not None
        # sub-second precision: a start truncated to the second would read
        # earlier than the moment the eval was launched
        assert datetime_from_iso_format_safe(started_at) >= admitted_no_earlier_than
        assert logs[0].samples is not None
        (sample,) = logs[0].samples
        assert sample.started_at is not None and started_at <= sample.started_at
    finally:
        for buffer in buffers:
            buffer.cleanup()


async def test_sample_failing_before_it_starts_keeps_its_admission_time(
    tmp_path: Path,
) -> None:
    """A sample whose input cannot be materialized is still dated.

    Execution never began, so there is no run start to record; the logged
    failure takes the sample's admission time instead, so crash recovery can
    order it against a record the log inherited for the same key.
    """
    from inspect_ai.model import ChatMessageUser, ContentImage

    admitted_no_earlier_than = datetime_now_utc()
    logs = await eval_async(
        Task(
            dataset=[
                Sample(
                    id=1,
                    input=[
                        ChatMessageUser(
                            content=[ContentImage(image=str(tmp_path / "missing.png"))]
                        )
                    ],
                    target="x",
                )
            ]
        ),
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        fail_on_error=False,
        ctl_server=False,
    )
    assert logs[0].status == "success"
    assert logs[0].samples is not None
    (sample,) = logs[0].samples
    assert sample.error is not None
    assert sample.started_at is not None
    assert datetime_from_iso_format_safe(sample.started_at) >= admitted_no_earlier_than


@pytest.mark.parametrize("task_retry_attempts", [0, 1])
@pytest.mark.parametrize("recovery_source", ["database", "filestore"])
async def test_terminal_log_write_failure_preserves_recovery(
    task_retry_attempts: int,
    recovery_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from test_helpers.buffer import simulate_crashed_buffer_db

    from inspect_ai.log import read_eval_log_async
    from inspect_ai.log._recorders.buffer import database as database_module
    from inspect_ai.log._recorders.buffer.database import DbPhase, SampleBufferDatabase
    from inspect_ai.log._recorders.eval import EvalRecorder, ZipLogFile
    from inspect_ai.log._recover import recover_eval_log_async
    from inspect_ai.model import ModelOutput, get_model

    monkeypatch.setattr(database_module, "resolve_db_dir", lambda _: tmp_path / "db")
    loggers: list[TaskLogger] = []
    buffers: list[SampleBufferDatabase] = []
    entries: list[ZipLogFile] = []
    init = TaskLogger.init
    flush = ZipLogFile.flush

    async def track_init(logger: TaskLogger) -> None:
        await init(logger)
        loggers.append(logger)
        assert logger.buffer_db is not None
        buffers.append(logger.buffer_db)
        assert isinstance(logger.recorder, EvalRecorder)
        entries.extend(logger.recorder.data.values())

    async def fail_final_write(log: ZipLogFile, fsync: bool = False) -> None:
        # the completion's shared-buffer upload is requested but not yet due
        # (log_shared=3600): the terminal close must drain it, or another
        # host has nothing to recover from
        if fsync:
            await anyio.lowlevel.checkpoint()
            raise OSError("persistent final write failure")
        await flush(log, fsync=fsync)

    monkeypatch.setattr(TaskLogger, "init", track_init)
    monkeypatch.setattr(ZipLogFile, "flush", fail_final_write)
    try:
        logs = await eval_async(
            Task(dataset=[Sample(id=1, input="x", target="saved")], scorer=match()),
            model=get_model(
                "mockllm/model",
                custom_outputs=[ModelOutput.from_content("mockllm/model", "saved")]
                * (task_retry_attempts + 1),
            ),
            log_dir=str(tmp_path / "logs"),
            log_buffer=100,
            log_shared=3600 if recovery_source == "filestore" else 0,
            task_retry_attempts=task_retry_attempts,
            ctl_server=False,
        )
        assert logs[0].status == "error"
        assert logs[0].error is not None
        assert "persistent final write failure" in logs[0].error.message
        assert len(buffers) == task_retry_attempts + 1
        logger = loggers[-1]
        written = await read_eval_log_async(logger.location)
        assert written.status == "started"
        assert not written.samples
        assert logger.buffer_db is None
        assert isinstance(logger.recorder, EvalRecorder)
        assert not logger.recorder.data
        assert not logger._stale_flush_stops
        assert all(entry._temp_file.closed and entry._zip is None for entry in entries)
        buffer = buffers[-1]
        assert buffer._db_phase is DbPhase.CLOSED and not buffer._connections
        assert buffer._sync_thread is None
        assert buffer.db_path.exists()
        filestore = buffer._sync_filestore

        if recovery_source == "database":
            assert filestore is None
            # Recovery ignores databases owned by a still-live process.
            simulate_crashed_buffer_db(buffer)
        else:
            assert filestore is not None and filestore.read_manifest() is not None
        # Restore storage for recovery; the missing DB simulates another machine.
        monkeypatch.setattr(ZipLogFile, "flush", flush)
        recovered_log = await recover_eval_log_async(
            logger.location,
            _db_dir=tmp_path
            / ("db" if recovery_source == "database" else "missing-db"),
        )
        assert recovered_log.location is not None
        recovered = await read_eval_log_async(recovered_log.location)
        assert recovered.samples is not None
        (sample,) = recovered.samples
        assert sample.id == 1
        assert sample.completed_at is not None
        assert sample.error is None
        assert sample.output.completion == "saved"
        assert sample.scores is not None and sample.scores["match"].value == "C"
        assert sample.events
    finally:
        for buffer in buffers:
            buffer.cleanup()


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_unserializable_score_metadata_does_not_abort_eval(
    tmp_path: Path, log_format: Literal["eval", "json"]
) -> None:
    """Score metadata the log writer cannot serialize degrades, end to end.

    The same `Score` objects are logged in the sample record and again as
    reductions at log finish, so stripping the record alone would still abort
    the eval at finish (leaving the log `started` with no results). The
    results must follow the logged record: metrics are still computed from
    the values, the reductions are written, and the record and reductions
    agree on the stripped scores.
    """
    from inspect_ai.scorer import Score, Target, accuracy, scorer
    from inspect_ai.solver import TaskState

    deep: dict[str, Any] = {"a": 1}
    for _ in range(1000):
        deep = {"a": deep}

    @scorer(metrics=[accuracy()])
    def deep_metadata():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1, answer="x", metadata={"deep": deep})

        return score

    task = Task(dataset=[Sample(id=1, input="x", target="x")], scorer=deep_metadata())
    log = eval(
        task, model="mockllm/model", log_dir=str(tmp_path), log_format=log_format
    )[0]

    assert log.status == "success", log.error
    assert log.results is not None
    assert log.results.scores[0].metrics["accuracy"].value == 1
    assert log.samples is not None and len(log.samples) == 1
    sample = log.samples[0]
    assert sample.scores is not None
    assert sample.scores["deep_metadata"].value == 1
    assert sample.scores["deep_metadata"].answer == "x"
    assert sample.scores["deep_metadata"].metadata is None
    assert sample.error is not None
    assert "score metadata" in sample.error.message
    assert log.reductions is not None
    (reduced,) = log.reductions[0].samples
    assert reduced.value == 1
    assert reduced.metadata is None


@pytest.mark.parametrize("sample_id", ["²", "①"])
async def test_json_retry_preserves_unicode_sample_id(
    sample_id: str, tmp_path: Path
) -> None:
    attempts = 0

    @solver
    def fail_once() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("first attempt fails")
            return state

        return solve

    logs = await eval_async(
        Task(dataset=[Sample(id=sample_id, input="x")], solver=fail_once()),
        model="mockllm/model",
        log_dir=str(tmp_path),
        log_format="json",
        task_retry_attempts=1,
        ctl_server=False,
    )
    assert attempts == 2
    assert logs[0].status == "success"
    assert logs[0].samples is not None
    (sample,) = logs[0].samples
    assert sample.id == sample_id
    assert sample.error_retries is not None and len(sample.error_retries) == 1
    assert "first attempt fails" in sample.error_retries[0].message


@pytest.mark.parametrize("failure_stage", ["seed", "checkpoint", "start", "flush"])
@pytest.mark.parametrize("log_format", ["eval", "json"])
@pytest.mark.parametrize("failure_mode", ["error", "cancel", "debug"])
async def test_terminal_retry_startup_releases_recorder(
    failure_stage: str,
    log_format: Literal["eval", "json"],
    failure_mode: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import inspect_ai._eval.task.run as task_run_module
    import inspect_ai.log._samples as samples_module
    from inspect_ai._eval.task import PreviousTask
    from inspect_ai.log import EvalSample, EvalSpec, list_eval_logs, read_eval_log_async
    from inspect_ai.log._recorders.eval import EvalRecorder, ZipLogFile
    from inspect_ai.log._recorders.json import JSONRecorder
    from inspect_ai.log._recorders.recorder import Recorder, SeedSamples
    from inspect_ai.util import CheckpointConfig, TurnInterval
    from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer

    monkeypatch.setattr(
        samples_module, "create_checkpointer", lambda **kwargs: _NoopCheckpointer()
    )
    loaded: list[SeedSamples] = []
    closed: list[SeedSamples] = []
    failed_loggers: list[TaskLogger] = []
    entries: list[ZipLogFile | JSONRecorder.JSONLogFile] = []
    load = SeedSamples.load
    close = SeedSamples.close
    seed = Recorder.log_seed_samples
    start = TaskLogger.log_start
    init = TaskLogger.init

    async def track_init(logger: TaskLogger) -> None:
        await init(logger)
        failed_loggers.append(logger)
        assert isinstance(logger.recorder, EvalRecorder | JSONRecorder)
        entries.extend(logger.recorder.data.values())

    async def track_load(source: SeedSamples, prior: str | list[EvalSample]) -> None:
        await load(source, prior)
        loaded.append(source)

    async def track_close(source: SeedSamples) -> None:
        await anyio.lowlevel.checkpoint()
        await close(source)
        closed.append(source)

    async def fail_startup() -> None:
        assert loaded
        if failure_mode == "cancel":
            scope.cancel()
            await anyio.lowlevel.checkpoint()
        raise OSError("simulated terminal startup failure")

    async def seed_and_fail(
        recorder: Recorder,
        spec: EvalSpec,
        prior: str | list[EvalSample],
        keep: set[tuple[str | int, int]] | None,
        *,
        on_sample: Callable[[str | int, int], None] | None = None,
    ) -> None:
        await seed(recorder, spec, prior, keep, on_sample=on_sample)
        if failure_stage == "seed":
            await fail_startup()

    async def copy_checkpoints(
        *, source_eval_dir: str, destination_eval_dir: str
    ) -> None:
        if failure_stage == "checkpoint":
            await fail_startup()

    async def start_and_fail(logger: TaskLogger, *args: Any, **kwargs: Any) -> None:
        if logger.prior_seeded and failure_stage == "start":
            await fail_startup()
        await start(logger, *args, **kwargs)
        if logger.prior_seeded and failure_stage == "flush":
            await fail_startup()

    @solver
    def fail_sample() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            raise RuntimeError("first attempt fails")

        return solve

    def retry_startup_task() -> Task:
        return Task(
            dataset=[Sample(id=1, input="x" * 100_000, target="y")],
            solver=fail_sample(),
            checkpoint=CheckpointConfig(trigger=TurnInterval(every=1)),
        )

    monkeypatch.setattr(SeedSamples, "load", track_load)
    monkeypatch.setattr(SeedSamples, "close", track_close)
    monkeypatch.setattr(Recorder, "log_seed_samples", seed_and_fail)
    monkeypatch.setattr(task_run_module, "copy_resume_payloads", copy_checkpoints)
    monkeypatch.setattr(TaskLogger, "log_start", start_and_fail)
    # JSON priors exercise the cached-body path for both destination formats.
    prior = (
        await eval_async(
            retry_startup_task(),
            model="mockllm/model",
            log_dir=str(tmp_path),
            log_format="json",
            ctl_server=False,
        )
    )[0]
    assert prior.location is not None
    monkeypatch.setattr(TaskLogger, "init", track_init)

    async def retry() -> None:
        result = await eval_async(
            PreviousTask(
                id=prior.eval.task_id,
                task=retry_startup_task(),
                task_args={},
                model=None,
                model_roles=None,
                sandbox=None,
                log=await read_eval_log_async(prior.location, header_only=True),
                log_info=list_eval_logs(str(tmp_path))[0],
            ),
            model="mockllm/model",
            log_dir=str(tmp_path),
            log_format=log_format,
            debug_errors=failure_mode == "debug",
            ctl_server=False,
        )
        if failure_mode == "error":
            assert result[0].status == "error"
            assert result[0].error is not None
            assert "simulated terminal startup failure" in result[0].error.message

    with anyio.CancelScope() as scope:
        if failure_mode == "debug":
            error_type = RuntimeError if failure_stage == "checkpoint" else OSError
            with pytest.raises(error_type, match="simulated terminal startup failure"):
                await retry()
        else:
            await retry()

    assert scope.cancel_called == (failure_mode == "cancel")
    assert len(loaded) == 1
    assert closed == loaded
    assert not loaded[0]._samples and not loaded[0].keys
    assert loaded[0]._reader is None
    assert len(failed_loggers) == len(entries) == 1
    for logger in failed_loggers:
        assert isinstance(logger.recorder, EvalRecorder | JSONRecorder)
        assert not logger.recorder._seed_sources
        assert not logger.recorder.data
        assert logger.buffer_db is None
    for entry in entries:
        if isinstance(entry, ZipLogFile):
            assert entry._temp_file.closed
            assert entry._zip is None
    logs = list_eval_logs(str(tmp_path))
    assert len(logs) == (2 if failure_stage == "flush" else 1)
    if failure_stage == "flush":
        written = await read_eval_log_async(failed_loggers[0].location)
        assert written.status == "started"
        assert written.samples is not None and len(written.samples) == 1
        assert written.samples[0].error == (prior.samples or [])[0].error


def test_failed_log_start_is_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transient log_start failure is retried and the task completes."""
    calls = {"n": 0}
    original_log_start = TaskLogger.log_start

    async def flaky_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            # push the retry's `created` (second resolution) past the failed
            # attempt's so the retry gets a different log location and must
            # cope with the failed attempt's log never having been written
            await anyio.sleep(1.1)
            raise _skew_error()
        return await original_log_start(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_start", flaky_log_start)

    logs = eval(
        log_write_failure_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
    )

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert calls["n"] == 2


def test_abandoned_attempt_not_traced_as_task_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An attempt abandoned by a task drain/cancel is not a task error.

    The attempt-start bail (``TaskRetryAbandonedError``) is an
    operator-requested outcome, so the dispatcher's "Run Task" trace action
    must record a clean exit rather than an ``error`` event with a
    stacktrace (which would show up in ``inspect trace dump`` as a failure).
    """
    import inspect_ai._eval.task.run as task_run_module
    from inspect_ai._util.constants import TRACE

    monkeypatch.setattr(task_run_module, "task_retry_abandoned", lambda _: True)
    caplog.set_level(TRACE, logger="inspect_ai._eval.run")

    logs = eval(
        log_write_failure_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )

    assert logs == []
    run_task_events = [
        getattr(r, "event")
        for r in caplog.records
        if getattr(r, "action", None) == "Run Task"
    ]
    assert run_task_events == ["enter", "exit"]


async def test_retry_sample_source_tolerates_missing_log_file(tmp_path: Path) -> None:
    """A retry whose prior log was never written yields no reusable samples.

    When a task fails in log_start() its log file never reaches disk, but the
    errored EvalLog still carries the destination path as its location. The
    retry's sample source must treat the missing file as "no prior sample"
    rather than propagating FileNotFoundError (which would error the retry).
    """
    from inspect_ai._eval.task.run import eval_log_sample_source
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.dataset import MemoryDataset
    from inspect_ai.log import EvalConfig, EvalDataset, EvalLog, EvalSpec
    from inspect_ai.log._file import EvalLogInfo

    missing_log = str(tmp_path / "never-written.eval")
    eval_log = EvalLog(
        status="error",
        eval=EvalSpec(
            created="2026-07-10T00:00:00+00:00",
            task="log_write_failure_task",
            dataset=EvalDataset(samples=1),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        location=missing_log,
    )
    log_info = EvalLogInfo(
        name=missing_log,
        type="file",
        size=0,
        mtime=None,
        task="log_write_failure_task",
        task_id="task-id",
        suffix=None,
    )
    source = eval_log_sample_source(
        eval_log, log_info, MemoryDataset([Sample(id=1, input="x", target="y")])
    )

    async with AsyncFilesystem():
        assert await source.lookup(1, 1) is None


def _retry_source_log_info(location: str) -> Any:
    from inspect_ai.log._file import EvalLogInfo

    return EvalLogInfo(
        name=location,
        type="file",
        size=0,
        mtime=None,
        task="retry_seed_task",
        task_id="task-id",
        suffix=None,
    )


def _write_prior_eval_log(log_dir: Path) -> Any:
    """Run a one-sample eval and return its log."""
    task = Task(
        dataset=[Sample(id=1, input="Say hello", target="hello")], scorer=match()
    )
    log = eval(task, model="mockllm/model", log_dir=str(log_dir))[0]
    assert log.status == "success" and log.location
    return log


def test_unseeded_retry_bounds_concurrent_prior_lookups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unseeded retry attempt's prior-log lookups stay bounded.

    With sample logging off nothing is seeded, so the reuse sweep falls back
    to reading the prior log per planned sample. Every planned sample's
    run_sample starts at once, so without a bound a large remote retry opens
    one body read per sample concurrently (61 for 61 prior records).
    """
    import inspect_ai._eval.task.run as task_run_module
    from inspect_ai.log._file import read_eval_log_sample_async as original_read

    monkeypatch.setattr(task_run_module, "PRIOR_LOOKUP_CONCURRENCY", 2)
    reads = {"in_flight": 0, "max_in_flight": 0, "total": 0}

    async def slow_read(*args: Any, **kwargs: Any) -> Any:
        reads["in_flight"] += 1
        reads["total"] += 1
        reads["max_in_flight"] = max(reads["max_in_flight"], reads["in_flight"])
        try:
            await anyio.sleep(0.02)
            return await original_read(*args, **kwargs)
        finally:
            reads["in_flight"] -= 1

    monkeypatch.setattr(task_run_module, "read_eval_log_sample_async", slow_read)

    runs: list[int] = []

    @solver(name=f"unseeded_lookup_solver_{id(runs)}")
    def fail_last_once() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            runs.append(int(str(state.sample_id)))
            if state.sample_id == 8 and runs.count(8) == 1:
                raise RuntimeError("first run fails")
            return state

        return solve

    unseeded_task = Task(
        dataset=[Sample(id=i, input="x", target="y") for i in range(1, 9)],
        solver=[fail_last_once()],
        name="unseeded_lookup_task",
    )
    logs = eval(
        unseeded_task,
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
        retry_on_error=0,
        log_samples=False,
        max_samples=8,
    )
    assert len(logs) == 1 and logs[0].status == "success"
    # the retry looked every planned sample up in the prior log ...
    assert reads["total"] == 8
    # ... at most PRIOR_LOOKUP_CONCURRENCY at a time
    assert reads["max_in_flight"] <= 2, reads


def test_retry_sample_source_seed_set_only_when_eligible(tmp_path: Path) -> None:
    """The seed a retry attempt's log is filled from follows the reuse eligibility checks.

    A prior log file that passes them seeds by location; an in-memory prior
    log seeds from its samples; a dataset that GREW (a strict superset with
    stable ids) also seeds — the prior samples are reused and only the newly
    added ones run (top-up); a prior that fails a check (dataset shrank,
    shuffled without ids) yields no seed at all — the attempt then runs
    everything fresh, as it reuses nothing.
    """
    from inspect_ai._eval.task.run import eval_log_sample_source
    from inspect_ai.dataset import MemoryDataset

    prior_log = _write_prior_eval_log(tmp_path / "logs")
    log_info = _retry_source_log_info(prior_log.location)
    dataset = MemoryDataset([Sample(id=1, input="x", target="y")])

    file_source = eval_log_sample_source(prior_log, log_info, dataset)
    assert file_source.seed is not None
    assert file_source.seed.source == prior_log.location

    memory_source = eval_log_sample_source(prior_log, None, dataset)
    assert memory_source.seed is not None
    assert isinstance(memory_source.seed.source, list)
    assert [s.id for s in memory_source.seed.source] == [1]

    # a grown dataset (strict superset with stable ids) seeds: prior samples
    # are reused and only the newly added samples run (the top-up path)
    bigger = MemoryDataset(
        [Sample(id=1, input="x", target="y"), Sample(id=2, input="x", target="y")]
    )
    bigger_source = eval_log_sample_source(prior_log, log_info, bigger)
    assert bigger_source.seed is not None
    assert bigger_source.seed.source == prior_log.location

    # a shrunk dataset is not a superset (a successor would drop scored
    # samples), so it yields no seed and re-runs everything
    smaller = MemoryDataset([])
    assert eval_log_sample_source(prior_log, log_info, smaller).seed is None

    shuffled = MemoryDataset([Sample(input="x", target="y")], shuffled=True)
    assert eval_log_sample_source(prior_log, log_info, shuffled).seed is None


def test_retry_sample_source_classify_resolves_seeded_records(tmp_path: Path) -> None:
    """`seed.classify` resolves a record read back from the seeded log like `lookup` does."""
    from inspect_ai._eval.task.run import (
        InvalidatedPrior,
        PreviousError,
        eval_log_sample_source,
    )
    from inspect_ai.dataset import MemoryDataset
    from inspect_ai.log import EvalError, EvalSample
    from inspect_ai.log._edit import ProvenanceData

    prior_log = _write_prior_eval_log(tmp_path / "logs")
    source = eval_log_sample_source(
        prior_log,
        _retry_source_log_info(prior_log.location),
        MemoryDataset([Sample(id=1, input="x", target="y")]),
    )
    seed = source.seed
    assert seed is not None

    clean = EvalSample(id=1, epoch=1, input="x", target="y")
    errored = clean.model_copy(
        update={
            "error": EvalError(
                message="RuntimeError('boom')", traceback="", traceback_ansi=""
            )
        }
    )
    invalidated = clean.model_copy(
        update={"invalidation": ProvenanceData(author="test", reason="bad")}
    )

    async def check() -> None:
        assert await seed.classify(1, 1, clean) is clean
        resolution = await seed.classify(1, 1, errored)
        assert isinstance(resolution, PreviousError) and resolution.sample is errored
        assert isinstance(await seed.classify(1, 1, invalidated), InvalidatedPrior)
        assert await seed.classify(1, 1, None) is None

    anyio.run(check)


def test_eval_raising_early_stopping_hook_keeps_sample_counted() -> None:
    """A raising `EarlyStopping.complete_sample` cannot leave a sample uncounted.

    Terminal state is recorded before the metrics/early-stopping await
    (design/sample-lifecycle.md): the hook raise still tears the eval down,
    but the errored-with-scores sample that triggered it has already reached
    its terminal bucket and the eval its finish stamp — with metrics-first
    ordering it landed in no bucket at all, so the dying eval could never
    reach `total`. The counters are observed from inside the hook (the
    registry is cleared at the run boundary, so there is nothing to read
    after `eval()` returns).
    """
    from inspect_ai._control.eval_state import clear_all_eval_states, get_eval_states
    from inspect_ai.log._log import EvalSpec
    from inspect_ai.scorer import SampleScore, Score, Target, accuracy, scorer
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util import EarlyStop

    @solver
    def always_boom():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            raise RuntimeError("solver boom")

        return solve

    @scorer(metrics=[accuracy()])
    def always_one():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1)

        return score

    observed: list[tuple[tuple[int, int, int], bool]] = []

    class RaisingEarlyStopping:
        async def start_task(
            self, task: EvalSpec, samples: list[Sample], epochs: int
        ) -> str:
            return "raiser"

        async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
            return None

        async def complete_sample(
            self, id: str | int, epoch: int, scores: dict[str, SampleScore]
        ) -> None:
            (state,) = get_eval_states()
            observed.append(
                (
                    (state.completed, state.errored, state.cancelled),
                    state.completed_at is not None,
                )
            )
            raise RuntimeError("hook failure")

        async def complete_task(self) -> dict[str, Any]:
            return {}

    clear_all_eval_states()
    try:
        log = eval(
            Task(
                dataset=[Sample(id="s1", input="x", target="y")],
                solver=always_boom(),
                scorer=always_one(),
                early_stopping=RaisingEarlyStopping(),
            ),
            model="mockllm/model",
            # score_on_error scores the errored sample, so its terminal
            # report reaches the metrics/early-stopping hook
            score_on_error=True,
            fail_on_error=False,
        )[0]
    finally:
        clear_all_eval_states()

    assert log.status == "error"
    assert log.error is not None and "hook failure" in log.error.message
    # the sample was in its terminal bucket, and the eval finish-stamped,
    # before the hook ran
    assert observed == [((0, 1, 0), True)]


def test_retry_attempt_dying_in_checkpoint_copy_leaves_no_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A retry that fails in its checkpoint startup copy is not the next source.

    The copy runs before the attempt's first log write, so the attempt
    leaves no log; the following attempt retries from the log the dead
    attempt was retrying (the newest log that exists), not from the dead
    attempt's possibly partial checkpoint dir.
    """
    import inspect_ai._eval.task.run as task_run_module
    import inspect_ai.log._samples as samples_module
    from inspect_ai.log import list_eval_logs
    from inspect_ai.solver import Generate, Solver, TaskState, solver
    from inspect_ai.util import CheckpointConfig, TurnInterval
    from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer

    # the checkpoint config is what gives a retry a prior checkpoints dir to
    # copy; the per-sample checkpointer itself (restic) is not under test
    monkeypatch.setattr(
        samples_module, "create_checkpointer", lambda **kwargs: _NoopCheckpointer()
    )

    copies: list[tuple[str, str]] = []

    async def flaky_copy(*, source_eval_dir: str, destination_eval_dir: str) -> None:
        copies.append((source_eval_dir, destination_eval_dir))
        if len(copies) == 1:
            raise OSError("simulated copy failure")

    monkeypatch.setattr(task_run_module, "copy_resume_payloads", flaky_copy)

    attempts = {"n": 0}

    @solver
    def fail_first() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("first attempt fails")
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id=1, input="x", target="x")],
            solver=fail_first(),
            checkpoint=CheckpointConfig(trigger=TurnInterval(every=1)),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=2,
    )

    assert len(logs) == 1
    assert logs[0].status == "success"
    # attempt 1 errored (has a log); attempt 2 died in the copy (no log);
    # attempt 3 succeeded (has a log)
    assert len(list_eval_logs(str(tmp_path))) == 2
    # both retries sourced attempt 1's checkpoints dir: attempt 3 fell back
    # to the log attempt 2 was retrying rather than attempt 2's own dir
    assert len(copies) == 2
    assert copies[0][0] == copies[1][0]


def _committed_checkpoint_json(checkpoint_id: int) -> str:
    from datetime import datetime, timezone

    from inspect_ai.util._checkpoint._layout.schemas import (
        Checkpoint,
        SnapshotDetails,
    )

    return Checkpoint(
        checkpoint_id=checkpoint_id,
        trigger="turn",
        turn=checkpoint_id,
        created_at=datetime(2026, 5, 17, 18, 0, tzinfo=timezone.utc),
        duration_ms=10,
        size_bytes=100,
        host=SnapshotDetails(snapshot_id="snap", size_bytes=100, duration_ms=10),
        sandboxes={},
    ).model_dump_json()


@task
def _retry_precedence_task(counter_file: str) -> Task:
    """Fails its sample on the first attempt only.

    eval_retry re-creates the task from the registry (re-importing this
    module), so the attempt counter lives in a file named by a task arg.
    """
    from inspect_ai.solver import Generate, Solver, TaskState, solver
    from inspect_ai.util import CheckpointConfig, TurnInterval

    @solver
    def fail_first() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            counter = Path(counter_file)
            attempts = int(counter.read_text() or "0") if counter.exists() else 0
            counter.write_text(str(attempts + 1))
            if attempts == 0:
                raise RuntimeError("first attempt fails")
            return state

        return solve

    return Task(
        dataset=[Sample(id="s", input="x", target="x")],
        solver=fail_first(),
        checkpoint=CheckpointConfig(trigger=TurnInterval(every=1)),
    )


def test_retry_resumes_from_own_checkpoint_or_discards_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_sample's resume decision on a retry, without docker or restic.

    An errored prior sample with a committed checkpoint in the copied dir
    resumes (checkpoint outranks the error seed); an invalidated prior
    with the same checkpoint runs fresh and its copied dir is deleted
    first, so provisioning starts from an empty dir.
    """
    import inspect_ai.log._samples as samples_module
    from inspect_ai import eval_retry
    from inspect_ai.log import ProvenanceData, invalidate_samples
    from inspect_ai.util._checkpoint._layout.eval_checkpoints_dir import (
        eval_checkpoints_dir,
    )
    from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer

    seen: list[object] = []

    def fake_create_checkpointer(**kwargs: Any) -> _NoopCheckpointer:
        seen.append(kwargs["resume_checkpoint"])
        return _NoopCheckpointer()

    monkeypatch.setattr(samples_module, "create_checkpointer", fake_create_checkpointer)

    first = eval(
        _retry_precedence_task(counter_file=str(tmp_path / "attempts.txt")),
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
    )[0]
    assert first.status == "error"

    # a committed checkpoint the (noop) checkpointer never wrote itself
    sample_dir = Path(eval_checkpoints_dir(first.location, None)) / "s__1"
    sample_dir.mkdir(parents=True)
    (sample_dir / "ckpt-00001.json").write_text(_committed_checkpoint_json(1))

    # errored prior + committed checkpoint → resume
    retried = eval_retry(first, log_dir=str(tmp_path / "logs"))[0]
    assert retried.status == "success"
    assert seen[-1] is not None and getattr(seen[-1], "attempt") == "resume"

    # invalidated prior + the same checkpoint → fresh, copied dir deleted
    invalidated = invalidate_samples(first, "all", ProvenanceData(author="test"))
    retried = eval_retry(invalidated, log_dir=str(tmp_path / "logs"))[0]
    assert retried.status == "success"
    assert seen[-1] is None
    assert not (Path(eval_checkpoints_dir(retried.location, None)) / "s__1").exists()


@contextmanager
def _registered_hook(
    hook_type: type[Hooks],
    name: str,
    description: str,
) -> Iterator[list[Hooks]]:
    from inspect_ai._util import registry as registry_module
    from inspect_ai.hooks import _hooks

    original_registry = registry_module._registry.copy()
    try:
        _hooks.hooks(name=name, description=description)(hook_type)
        registered = [
            hook for hook in _hooks.get_all_hooks() if isinstance(hook, hook_type)
        ]
        assert len(registered) == 1
        yield registered
    finally:
        # Restore only this fixture's entries; preserve native plugin loads.
        for key, value in list(registry_module._registry.items()):
            if isinstance(value, hook_type):
                if key in original_registry:
                    previous = original_registry[key]
                    registry_module.registry_add(
                        previous, registry_module.registry_info(previous)
                    )
                else:
                    del registry_module._registry[key]
    assert not any(isinstance(hook, hook_type) for hook in _hooks.get_all_hooks())


@pytest.mark.parametrize("sample_outcome", ["complete", "retry", "limit", "scoring"])
def test_eval_closes_sample_event_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sample_outcome: Literal["complete", "retry", "limit", "scoring"],
) -> None:
    import gc
    import warnings

    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

    from inspect_ai.event import InfoEvent, ScoreEvent
    from inspect_ai.hooks import _hooks
    from inspect_ai.hooks._hooks import SampleEvent
    from inspect_ai.log import transcript
    from inspect_ai.log._samples import sample_active
    from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer

    receivers: list[MemoryObjectReceiveStream[SampleEvent]] = []
    events: list[str] = []
    attempts = 0
    original_start = _hooks.start_sample_event_emitter

    def track_start() -> None:
        original_start()
        active = sample_active()
        assert active is not None and active.event_receive is not None
        receivers.append(active.event_receive)

    class Recorder(Hooks):
        async def on_sample_event(self, data: SampleEvent) -> None:
            if isinstance(data.event, InfoEvent):
                events.append(str(data.event.data))
            elif isinstance(data.event, ScoreEvent):
                events.append("score")

    try:
        with (
            _registered_hook(
                Recorder,
                f"event_stream_owner_test_{sample_outcome}",
                "Record sample events in lifecycle tests.",
            ) as registered,
            monkeypatch.context() as patch,
        ):
            patch.setattr(_hooks, "get_all_hooks", lambda: registered)
            patch.setattr(_hooks, "start_sample_event_emitter", track_start)

            @solver
            def emit_then_finish() -> Solver:
                async def solve(state: TaskState, generate: Generate) -> TaskState:
                    nonlocal attempts
                    attempts += 1
                    transcript().info(f"attempt-{attempts}")
                    if sample_outcome == "retry" and attempts == 1:
                        raise RuntimeError("retry sample")
                    if sample_outcome == "limit":
                        await anyio.sleep_forever()
                    return await generate(state)

                return solve

            @scorer(metrics=[accuracy()])
            def emit_while_scoring() -> Scorer:
                async def score(state: TaskState, target: Target) -> Score:
                    transcript().info("scoring")
                    return Score(value=1)

                return score

            task = Task(
                dataset=[Sample(input="hello")],
                solver=emit_then_finish(),
                scorer=emit_while_scoring() if sample_outcome == "scoring" else None,
                time_limit=1 if sample_outcome == "limit" else None,
            )
            gc.collect()
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                log = eval(
                    task,
                    model="mockllm/model",
                    display="none",
                    log_dir=str(tmp_path),
                    retry_on_error=1,
                )[0]
                assert log.status == "success", log.error
                assert attempts == (2 if sample_outcome == "retry" else 1)
                expected_events = [
                    f"attempt-{number}" for number in range(1, attempts + 1)
                ]
                if sample_outcome == "scoring":
                    expected_events.extend(["scoring", "score"])
                assert events == expected_events
                assert len(receivers) == attempts
                for receive in receivers:
                    stats = receive.statistics()
                    assert stats.open_send_streams == stats.open_receive_streams == 0
                del receive
                assert log.samples is not None
                if sample_outcome == "scoring":
                    assert log.results is not None
                    assert log.results.scores[0].metrics["accuracy"].value == 1
                    assert log.samples[0].scores is not None
                    assert log.samples[0].scores["emit_while_scoring"].value == 1
                    assert any(
                        isinstance(event, ScoreEvent) for event in log.samples[0].events
                    )
                if sample_outcome == "limit":
                    assert log.samples[0].limit is not None
                    assert log.samples[0].limit.type == "time"
                receivers.clear()
                gc.collect()
                probe_start = len(caught)
                probe_send, probe_receive = anyio.create_memory_object_stream[
                    SampleEvent
                ]()
                probe_send.close()
                probe_id = id(probe_receive)
                del probe_receive
                gc.collect()
                probe_warnings = [
                    item for item in caught[probe_start:] if id(item.source) == probe_id
                ]
                assert len(probe_warnings) == 1
                probe_warning = probe_warnings[0]
                assert issubclass(probe_warning.category, ResourceWarning)
                assert isinstance(probe_warning.source, MemoryObjectReceiveStream)
                probe_warning.source.close()
                caught.remove(probe_warning)
            assert not [
                item
                for item in caught
                if issubclass(item.category, ResourceWarning)
                and isinstance(
                    item.source, (MemoryObjectReceiveStream, MemoryObjectSendStream)
                )
            ]
    finally:
        for receive in receivers:
            receive.close()
        receivers.clear()


async def test_eval_scoring_hook_cancellation_closes_sample_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from anyio.streams.memory import MemoryObjectReceiveStream

    from inspect_ai.hooks import _hooks
    from inspect_ai.hooks._hooks import SampleEvent, SampleScoring
    from inspect_ai.log import list_eval_logs_async, read_eval_log_async
    from inspect_ai.log._samples import sample_active

    reached = anyio.Event()
    cancelled = anyio.Event()
    receivers: list[MemoryObjectReceiveStream[SampleEvent]] = []
    original_start = _hooks.start_sample_event_emitter

    class ScoringHook(Hooks):
        async def on_sample_scoring(self, data: SampleScoring) -> None:
            reached.set()
            try:
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                cancelled.set()
                raise

    def track_start() -> None:
        original_start()
        active = sample_active()
        assert active is not None and active.event_receive is not None
        receivers.append(active.event_receive)

    try:
        with (
            _registered_hook(
                ScoringHook,
                "event_stream_scoring_cancel_test",
                "Cancel a native scoring hook.",
            ) as registered,
            monkeypatch.context() as patch,
        ):
            patch.setattr(_hooks, "get_all_hooks", lambda: registered)
            patch.setattr(_hooks, "start_sample_event_emitter", track_start)
            with anyio.CancelScope() as scope:
                async with anyio.create_task_group() as tg:

                    async def cancel_at_scoring() -> None:
                        await reached.wait()
                        scope.cancel()

                    tg.start_soon(cancel_at_scoring)
                    await eval_async(
                        Task(dataset=[Sample(input="hello")]),
                        model="mockllm/model",
                        log_dir=str(tmp_path),
                    )
                    tg.cancel_scope.cancel()
            assert scope.cancel_called
            assert reached.is_set() and cancelled.is_set()
            assert len(receivers) == 1
            for receive in receivers:
                stats = receive.statistics()
                assert stats.open_send_streams == stats.open_receive_streams == 0
            # eval_async can consume cancellation after producing a native log.
            logs = await list_eval_logs_async(str(tmp_path))
            assert len(logs) == 1
            log = await read_eval_log_async(logs[0])
            assert log.status == "cancelled"
            assert not log.samples
    finally:
        for receive in receivers:
            receive.close()
