from __future__ import annotations

import asyncio
import glob
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import TabbedContent, TabPane

from inspect_ai._display.core.display import (
    TaskCancelled,
    TaskDisplayMetric,
    TaskError,
    TaskProfile,
    TaskSpec,
    TaskSuccess,
    TaskWithResult,
)
from inspect_ai._display.core.rich import rich_initialise
from inspect_ai._display.textual.theme import inspect_dark, inspect_light
from inspect_ai._display.textual.widgets.console import ConsoleView
from inspect_ai._display.textual.widgets.footer import AppFooter
from inspect_ai._display.textual.widgets.samples import SamplesView
from inspect_ai._display.textual.widgets.tasks import TasksView
from inspect_ai._display.textual.widgets.titlebar import AppTitlebar
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log import EvalConfig
from inspect_ai.log._samples import ActiveSample
from inspect_ai.log._transcript import Transcript
from inspect_ai.model import GenerateConfig, ModelName

from textual.screen import ModalScreen
from textual.widgets import Input, Label

from inspect_ai._event_bus.protocol import (
    CancelSampleCommand,
    EvalCompleteMessage,
    MetricsUpdateMessage,
    PrintMessage,
    ProgressUpdateMessage,
    SampleCancelledMessage,
    SampleCompleteMessage,
    SampleEndMessage,
    SampleStartMessage,
    ServerMessage,
    SnapshotMessage,
    TaskCompleteMessage,
    TaskInfo,
    TaskStartMessage,
    InputRequestedMessage,
    InputResolvedMessage,
    InputResponseCommand,
    SampleInfo,
    parse_server_message,
    to_json_line,
)


def find_socket() -> str | None:
    pattern = os.path.join(tempfile.gettempdir(), "inspect-*.sock")
    sockets = glob.glob(pattern)
    if not sockets:
        return None
    return max(sockets, key=os.path.getmtime)


def _task_info_to_profile(info: TaskInfo) -> TaskProfile:
    return TaskProfile(
        name=info.name,
        file=None,
        model=ModelName(info.model),
        dataset=info.dataset,
        scorer=info.scorer,
        samples=info.samples,
        steps=info.steps,
        eval_config=EvalConfig(),
        task_args={},
        generate_config=GenerateConfig(),
        tags=info.tags,
        log_location=info.log_location,
    )


class RemoteActiveSample(ActiveSample):
    _cancel_callback: Any = None

    def interrupt(self, action: str) -> None:
        if self._cancel_callback:
            self._cancel_callback(str(self.sample.id))


def _make_active_sample(
    sample_id: str, task_name: str, model: str,
    cancel_callback: Any = None,
) -> RemoteActiveSample:
    sample = Sample(id=sample_id, input=f"Sample {sample_id}")
    active = RemoteActiveSample(
        task=task_name,
        log_location="",
        model=model,
        sample=sample,
        epoch=1,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=Transcript(),
        sandboxes={},
    )
    active.started = datetime.now(timezone.utc).timestamp()
    active._cancel_callback = cancel_callback
    return active




class InputModal(ModalScreen[str | None]):
    DEFAULT_CSS = """
    #input-dialog {
        width: 70;
        height: auto;
        max-height: 12;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
        align: center middle;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_modal", "Dismiss"),
    ]

    def __init__(self, prompt: str, request_id: str) -> None:
        super().__init__()
        self._prompt = prompt
        self._request_id = request_id

    def compose(self) -> ComposeResult:
        with Vertical(id="input-dialog"):
            yield Label(f"Agent asks: {self._prompt}")
            yield Input(placeholder="Type your response...", id="human-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


class RemoteTaskScreenApp(App[None]):
    CSS_PATH = "../textual/app.tcss"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Detach"),
        Binding("r", "respond_to_input", "Respond"),
    ]

    def __init__(self, socket_path: str) -> None:
        super().__init__()
        self._socket_path = socket_path
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._task_displays: dict[str, Any] = {}
        self._tasks: list[TaskWithResult] = []
        self._active_samples: dict[str, ActiveSample] = {}
        self._current_task_name = ""
        self._current_model = ""
        self._pending_input_id: str | None = None
        self._pending_input_prompt: str = ""
        rich_initialise()

    def compose(self) -> ComposeResult:
        yield AppTitlebar()
        yield AppFooter()

        with TabbedContent(id="tabs", initial="tasks"):
            with TabPane("Tasks", id="tasks"):
                yield TasksView()
            with TabPane("Running Samples", id="samples"):
                yield SamplesView()
            with TabPane("Console", id="console"):
                yield ConsoleView()

    def on_mount(self) -> None:
        self.register_theme(inspect_dark)
        self.register_theme(inspect_light)
        self.theme = "inspect-dark"

        header = self.query_one(AppTitlebar)
        header.title = f"Remote: {self._socket_path}"

        self.begin_capture_print(self)
        self.run_worker(self._connect_and_listen(), exclusive=True)
        self.set_interval(1, self._update_samples_view)

    def _update_samples_view(self) -> None:
        active = [s for s in self._active_samples.values() if s.completed is None]
        try:
            self.query_one(SamplesView).set_samples(active)
        except Exception:
            pass

    async def _connect_and_listen(self) -> None:
        try:
            reader, self._writer = await asyncio.open_unix_connection(self._socket_path)
            self._connected = True
            self._write_console("Connected to eval")

            while True:
                line = await reader.readline()
                if not line:
                    self._write_console("[Connection closed by server]")
                    break
                try:
                    msg = parse_server_message(line)
                    self._handle_message(msg)
                except Exception as e:
                    self._write_console(f"[Parse error: {e}]")

        except (ConnectionRefusedError, FileNotFoundError) as e:
            self._write_console(f"[Connection failed: {e}]")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._write_console(f"[Error: {e}]")
        finally:
            self._connected = False

    def _handle_message(self, msg: ServerMessage) -> None:
        if isinstance(msg, SnapshotMessage):
            self._handle_snapshot(msg)

        elif isinstance(msg, TaskStartMessage):
            self._handle_task_start(msg.task)

        elif isinstance(msg, SampleCompleteMessage):
            key = self._task_key(msg.task_name, msg.model)
            td = self._task_displays.get(key)
            if td:
                td.sample_complete(msg.complete, msg.total)

        elif isinstance(msg, MetricsUpdateMessage):
            key = self._task_key(msg.task_name, msg.model)
            td = self._task_displays.get(key)
            if td:
                metrics = [
                    TaskDisplayMetric(
                        scorer=m.scorer, name=m.name, value=m.value, reducer=m.reducer
                    )
                    for m in msg.metrics
                    if m.value is not None
                ]
                if metrics:
                    td.update_metrics(metrics)

        elif isinstance(msg, TaskCompleteMessage):
            key = self._task_key(msg.task_name, msg.model)
            td = self._task_displays.get(key)
            if td:
                from inspect_ai.log import EvalResults, EvalStats
                if msg.status == "success":
                    result = TaskSuccess(
                        samples_completed=msg.samples_completed,
                        stats=EvalStats(),
                        results=EvalResults(),
                    )
                elif msg.status == "cancelled":
                    result = TaskCancelled(
                        samples_completed=msg.samples_completed,
                        stats=EvalStats(),
                    )
                else:
                    result = TaskError(
                        samples_completed=msg.samples_completed,
                        exc_type=RuntimeError,
                        exc_value=RuntimeError(msg.error or "Unknown error"),
                        traceback=None,
                    )
                td.complete(result)

        elif isinstance(msg, EvalCompleteMessage):
            header = self.query_one(AppTitlebar)
            header.title = "Eval complete — press q to detach"
            self._write_console("═══ Eval complete ═══")

        elif isinstance(msg, PrintMessage):
            self._write_console(msg.message)

        elif isinstance(msg, SampleCancelledMessage):
            reason = f" ({msg.reason})" if msg.reason else ""
            self._write_console(f"Sample cancelled: {msg.sample_id}{reason}")
            self._active_samples.pop(msg.sample_id, None)

        elif isinstance(msg, SampleStartMessage):
            self._write_console(f"Sample started: {msg.sample_id}")
            active = _make_active_sample(
                msg.sample_id, self._current_task_name, self._current_model,
                cancel_callback=self._send_cancel,
            )
            self._active_samples[msg.sample_id] = active

        elif isinstance(msg, SampleEndMessage):
            scores_str = ""
            if msg.scores:
                scores_str = " — " + ", ".join(
                    f"{k}={v}" for k, v in msg.scores.items()
                )
            self._write_console(f"Sample ended: {msg.sample_id}{scores_str}")
            s = self._active_samples.get(msg.sample_id)
            if s:
                s.complete()

        elif isinstance(msg, InputRequestedMessage):
            self._pending_input_id = msg.request_id
            self._pending_input_prompt = msg.prompt
            self._write_console(f"")
            self._write_console(f"━━━ ⏸ AGENT WAITING FOR INPUT ━━━")
            self._write_console(f"  {msg.prompt}")
            self._write_console(f"  Press 'r' to respond")
            self._write_console(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        elif isinstance(msg, InputResolvedMessage):
            if self._pending_input_id == msg.request_id:
                self._write_console("✓ Input resolved")
                self._pending_input_id = None
                self._pending_input_prompt = ""
                try:
                    self.pop_screen()
                except Exception:
                    pass

        elif isinstance(msg, ProgressUpdateMessage):
            key = self._task_key(msg.task_name, msg.model)
            td = self._task_displays.get(key)
            if td:
                td.progress_bar.update(total=msg.steps_total, progress=msg.steps_complete)

    def _handle_snapshot(self, msg: SnapshotMessage) -> None:
        if not msg.tasks:
            self._write_console("Connected — no tasks started yet")
            return

        tasks_view = self.query_one(TasksView)
        specs = [
            TaskSpec(name=t.task_name, model=ModelName(t.model))
            for t in msg.tasks
        ]
        tasks_view.init_tasks(specs)

        for t in msg.tasks:
            self._current_task_name = t.task_name
            self._current_model = t.model
            profile = TaskProfile(
                name=t.task_name,
                file=None,
                model=ModelName(t.model),
                dataset="",
                scorer="",
                samples=t.samples_total,
                steps=t.steps_total,
                eval_config=EvalConfig(),
                task_args={},
                generate_config=GenerateConfig(),
                tags=None,
                log_location="",
            )
            task_wr = TaskWithResult(profile, None)
            self._tasks.append(task_wr)
            td = tasks_view.add_task(task_wr)
            key = self._task_key(t.task_name, t.model)
            self._task_displays[key] = td

            if t.samples_complete > 0:
                td.sample_complete(t.samples_complete, t.samples_total)

            if t.metrics:
                metrics = [
                    TaskDisplayMetric(
                        scorer=m.scorer, name=m.name, value=m.value, reducer=m.reducer
                    )
                    for m in t.metrics
                    if m.value is not None
                ]
                if metrics:
                    td.update_metrics(metrics)

        if msg.active_samples:
            for s in msg.active_samples:
                active = _make_active_sample(
                    str(s.sample_id),
                    s.task_name or self._current_task_name,
                    s.model or self._current_model,
                    cancel_callback=self._send_cancel,
                )
                if s.started_at:
                    active.started = s.started_at
                self._active_samples[str(s.sample_id)] = active

        if hasattr(msg, 'pending_inputs') and msg.pending_inputs:
            for pi in msg.pending_inputs:
                self._pending_input_id = pi.request_id
                self._pending_input_prompt = pi.prompt
                self._write_console(f"")
                self._write_console(f"━━━ ⏸ AGENT WAITING FOR INPUT ━━━")
                self._write_console(f"  {pi.prompt}")
                self._write_console(f"  Press 'r' to respond")
                self._write_console(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        self._write_console(
            f"Snapshot: {len(msg.tasks)} task(s), "
            f"{len(msg.active_samples)} running samples, "
            f"{len(msg.recent_events)} recent events"
        )

    def _handle_task_start(self, info: TaskInfo) -> None:
        self._current_task_name = info.name
        self._current_model = info.model
        tasks_view = self.query_one(TasksView)
        profile = _task_info_to_profile(info)

        specs = [TaskSpec(name=info.name, model=ModelName(info.model))]
        if not self._task_displays:
            tasks_view.init_tasks(specs)

        task_wr = TaskWithResult(profile, None)
        self._tasks.append(task_wr)
        td = tasks_view.add_task(task_wr)
        key = self._task_key(info.name, info.model)
        self._task_displays[key] = td

        header = self.query_one(AppTitlebar)
        header.title = f"{info.name} ({info.model})"

    def _task_key(self, task_name: str, model: str) -> str:
        return f"{task_name}::{model}"

    def _write_console(self, text: str) -> None:
        try:
            self.query_one(ConsoleView).write_ansi(text)
        except Exception:
            pass

    def _send_cancel(self, sample_id: str) -> None:
        if self._writer and self._connected:
            data = to_json_line(CancelSampleCommand(sample_id=sample_id))
            self._writer.write(data)
            self._write_console(f"Cancel requested: {sample_id}")

    def action_respond_to_input(self) -> None:
        if not self._pending_input_id:
            self._write_console("No pending input request")
            return
        def on_response(text: str | None) -> None:
            if text and self._writer and self._connected and self._pending_input_id:
                cmd = InputResponseCommand(request_id=self._pending_input_id, text=text)
                self._writer.write(to_json_line(cmd))
                self._write_console(f"Response sent: {text}")
                self._pending_input_id = None
                self._pending_input_prompt = ""
        self.push_screen(InputModal(self._pending_input_prompt, self._pending_input_id), callback=on_response)

    async def action_quit(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self.exit()

    def on_print(self, event: Any) -> None:
        text = event.text
        if text.endswith("\n"):
            text = text[:-1]
        self._write_console(text)


def main(socket_path: str | None = None) -> None:
    if socket_path is None:
        socket_path = find_socket()
        if socket_path is None:
            print("No running inspect eval found. Specify a socket path.")
            sys.exit(1)

    if not os.path.exists(socket_path):
        print(f"Socket not found: {socket_path}")
        sys.exit(1)

    app = RemoteTaskScreenApp(socket_path)
    app.run()
