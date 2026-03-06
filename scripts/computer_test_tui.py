#!/usr/bin/env python3
"""TUI for testing the sandbox computer use tool via Docker."""

from __future__ import annotations

import re
import subprocess

from computer_test import (
    DEFAULT_IMAGE,
    display_image,
    docker_exec,
    docker_port,
    docker_run,
    docker_stop,
)
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    RichLog,
    Select,
    Static,
)

# Action categories for dispatch logic
COORD_ACTIONS = {
    "mouse_move",
    "left_click",
    "right_click",
    "middle_click",
    "back_click",
    "forward_click",
    "double_click",
    "triple_click",
}
NO_ARG_ACTIONS = {"screenshot", "cursor_position", "left_mouse_down", "left_mouse_up"}

SCROLL_DIRECTIONS = ["up", "down", "left", "right"]

LAUNCH_NEW = "__launch_new__"


def list_running_containers() -> list[tuple[str, str]]:
    """Return (display_label, container_id) for running containers."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    containers = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            cid, name, image = parts[0], parts[1], parts[2]
            containers.append((f"{cid[:12]} {name} ({image})", cid))
    return containers


class ComputerTestApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #status-bar {
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    .row {
        height: auto;
        padding: 0 1;
    }
    .row Label {
        width: auto;
        padding: 0 1 0 0;
    }
    .row Input {
        width: 12;
    }
    #text-input {
        width: 1fr;
    }
    .row Button {
        min-width: 14;
    }
    #log {
        height: 1fr;
        border: solid $primary;
    }
    #container-select {
        width: 40;
    }
    #scroll-dir {
        width: 16;
    }
    .section-label {
        color: $text-muted;
        padding: 0 1 0 0;
        width: auto;
    }
    #log-container {
        height: 1fr;
    }
    #loading {
        height: 1;
        display: none;
    }
    #loading.visible {
        display: block;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+l", "focus_log", "Log"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.container_id: str | None = None
        self._attached = False
        self.show_images = False
        self._vnc_url: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        yield Static("No container", id="status-bar")

        # Connection row
        with Horizontal(classes="row"):
            yield Select(
                [("+  Launch new container", LAUNCH_NEW)],
                value=LAUNCH_NEW,
                id="container-select",
                allow_blank=False,
            )
            yield Button("Launch", id="btn-connect", variant="success")
            yield Button("Detach", id="btn-detach")
            yield Button("Terminate", id="btn-terminate", variant="error")
            yield Button("Images", id="btn-images")

        # Position inputs
        with Horizontal(classes="row"):
            yield Label("x")
            yield Input(placeholder="x", id="x", type="integer")
            yield Label("y")
            yield Input(placeholder="y", id="y", type="integer")
            yield Label("x2")
            yield Input(placeholder="x2", id="x2", type="integer")
            yield Label("y2")
            yield Input(placeholder="y2", id="y2", type="integer")

        # Mouse actions (most common first)
        with Horizontal(classes="row"):
            yield Label("Mouse:", classes="section-label")
            for action in [
                "left_click",
                "right_click",
                "double_click",
                "mouse_move",
                "triple_click",
                "middle_click",
                "left_click_drag",
                "cursor_position",
                "scroll",
            ]:
                yield Button(
                    action.replace("_", " "), id=f"btn-{action}", classes="action-btn"
                )

        with Horizontal(classes="row"):
            yield Label("", classes="section-label")
            for action in [
                "screenshot",
                "zoom",
                "left_mouse_down",
                "left_mouse_up",
                "back_click",
                "forward_click",
            ]:
                yield Button(
                    action.replace("_", " "), id=f"btn-{action}", classes="action-btn"
                )
            yield Label("scroll")
            yield Input(placeholder="amt", id="scroll_amount", type="integer")
            yield Select(
                [(d, d) for d in SCROLL_DIRECTIONS],
                prompt="dir",
                id="scroll-dir",
                allow_blank=True,
            )

        # Text inputs + actions
        with Horizontal(classes="row"):
            yield Label("text")
            yield Input(placeholder="text / key combo", id="text-input")
            yield Label("dur")
            yield Input(placeholder="sec", id="duration")

        with Horizontal(classes="row"):
            yield Label("Text:", classes="section-label")
            yield Button("type", id="btn-type", classes="action-btn")
            yield Button("key", id="btn-key", classes="action-btn")
            yield Button("hold key", id="btn-hold_key", classes="action-btn")
            yield Button("wait", id="btn-wait", classes="action-btn")

        with Vertical(id="log-container"):
            yield LoadingIndicator(id="loading")
            yield RichLog(id="log", wrap=True, highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_containers()

    def _log(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)

    def _update_status(self) -> None:
        bar = self.query_one("#status-bar", Static)
        if self.container_id:
            mode = "attached" if self._attached else "launched"
            vnc = f"  noVNC: {self._vnc_url}" if self._vnc_url else ""
            bar.update(f"Container: {self.container_id[:12]} ({mode}){vnc}")
        else:
            bar.update("No container")

    def _get(self, field_id: str) -> str:
        return self.query_one(f"#{field_id}", Input).value.strip()

    def _set(self, field_id: str, value: str) -> None:
        self.query_one(f"#{field_id}", Input).value = value

    def _update_connect_label(self) -> None:
        select = self.query_one("#container-select", Select)
        btn = self.query_one("#btn-connect", Button)
        is_launch = select.value == LAUNCH_NEW
        btn.label = "Launch" if is_launch else "Attach"
        btn.variant = "success" if is_launch else "primary"

    @work(thread=True)
    def _refresh_containers(self) -> None:
        containers = list_running_containers()
        options: list[tuple[str, str]] = [("+  Launch new container", LAUNCH_NEW)]
        options.extend(containers)
        default = containers[0][1] if containers else LAUNCH_NEW

        def _apply() -> None:
            select = self.query_one("#container-select", Select)
            select.set_options(options)
            select.value = default
            self._update_connect_label()

        self.call_from_thread(_apply)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "btn-connect":
            selected = self.query_one("#container-select", Select).value
            if selected == LAUNCH_NEW:
                self._do_launch()
            else:
                self._do_attach(str(selected))
        elif btn_id == "btn-detach":
            self._do_detach()
        elif btn_id == "btn-terminate":
            self._do_terminate()
        elif btn_id == "btn-images":
            self.show_images = not self.show_images
            state = "ON" if self.show_images else "OFF"
            self._log(f"Show images: {state}")
        elif btn_id.startswith("btn-"):
            action = btn_id[4:]
            self._dispatch_tool_action(action)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "container-select":
            self._update_connect_label()

    def _dispatch_tool_action(self, action: str) -> None:
        if not self.container_id:
            self._log("[red]No container. Launch or attach first.[/red]")
            return

        if action in NO_ARG_ACTIONS:
            self._run_action(action, [action])
        elif action in COORD_ACTIONS:
            x, y = self._get("x"), self._get("y")
            if not x or not y:
                self._log(f"[red]{action} requires x, y[/red]")
                return
            self._run_action(action, [action, "--coordinate", x, y])
        elif action in ("key", "type"):
            text = self._get("text-input")
            if not text:
                self._log(f"[red]{action} requires text[/red]")
                return
            self._run_action(action, [action, "--text", text])
        elif action == "hold_key":
            text, dur = self._get("text-input"), self._get("duration")
            if not text or not dur:
                self._log("[red]hold_key requires text and duration[/red]")
                return
            self._run_action(action, ["hold_key", "--text", text, "--duration", dur])
        elif action == "left_click_drag":
            x, y = self._get("x"), self._get("y")
            x2, y2 = self._get("x2"), self._get("y2")
            if not all([x, y, x2, y2]):
                self._log("[red]drag requires x, y, x2, y2[/red]")
                return
            self._run_action(
                action,
                [
                    "left_click_drag",
                    "--start_coordinate",
                    x,
                    y,
                    "--coordinate",
                    x2,
                    y2,
                ],
            )
        elif action == "scroll":
            amt = self._get("scroll_amount")
            direction = self.query_one("#scroll-dir", Select).value
            if not amt or direction == Select.BLANK:
                self._log("[red]scroll requires amount and direction[/red]")
                return
            cmd_tail = [
                "scroll",
                "--scroll_amount",
                amt,
                "--scroll_direction",
                str(direction),
            ]
            x, y = self._get("x"), self._get("y")
            if x and y:
                cmd_tail += ["--coordinate", x, y]
            self._run_action(action, cmd_tail)
        elif action == "wait":
            dur = self._get("duration")
            if not dur:
                self._log("[red]wait requires duration[/red]")
                return
            self._run_action(action, ["wait", "--duration", dur])
        elif action == "zoom":
            x, y = self._get("x"), self._get("y")
            x2, y2 = self._get("x2"), self._get("y2")
            if not all([x, y, x2, y2]):
                self._log("[red]zoom requires x, y, x2, y2[/red]")
                return
            self._run_action(action, ["zoom", "--region", x, y, x2, y2])

    def _set_busy(self, busy: bool) -> None:
        loading = self.query_one("#loading", LoadingIndicator)
        if busy:
            loading.add_class("visible")
        else:
            loading.remove_class("visible")
        for btn in self.query(".action-btn"):
            btn.disabled = busy

    @work(thread=True)
    def _run_action(self, action: str, cmd_tail: list[str]) -> None:
        assert self.container_id
        self.call_from_thread(self._set_busy, True)
        self.call_from_thread(self._log, f"[dim]> {action}[/dim]")
        try:
            result = docker_exec(self.container_id, cmd_tail)
            self.call_from_thread(self._handle_result, action, result)
        except Exception as e:
            self.call_from_thread(self._log, f"[red]Error: {e}[/red]")
        finally:
            self.call_from_thread(self._set_busy, False)

    def _handle_result(self, action: str, result: dict) -> None:
        if result.get("error"):
            self._log(f"[red]Error: {result['error']}[/red]")
            return
        output = result.get("output")
        if output:
            self._log(output)
        if result.get("base64_image"):
            if self.show_images:
                display_image(result["base64_image"])
            self._log("(screenshot returned)")

        # Auto-update x,y from cursor_position
        if action == "cursor_position" and output:
            m = re.match(r"X=(\d+),Y=(\d+)", output)
            if m:
                self._set("x", m.group(1))
                self._set("y", m.group(2))

    @work(thread=True)
    def _do_launch(self) -> None:
        if self.container_id:
            self.call_from_thread(
                self._log, "[red]Already connected. Detach/terminate first.[/red]"
            )
            return
        self.call_from_thread(self._log, f"Launching {DEFAULT_IMAGE}...")
        try:
            cid = docker_run(DEFAULT_IMAGE)
            host_port = docker_port(cid, 6080)
            vnc_url = f"http://localhost:{host_port}?view_only=true&autoconnect=true&resize=scale"
            self.container_id = cid
            self._attached = False
            self._vnc_url = vnc_url
            self.call_from_thread(self._update_status)
            self.call_from_thread(self._log, f"Container: {cid[:12]}")
            self.call_from_thread(self._log, f"noVNC: {vnc_url}")
            self.call_from_thread(self._refresh_containers)
        except subprocess.CalledProcessError as e:
            self.call_from_thread(self._log, f"[red]Failed to launch: {e.stderr}[/red]")

    def _do_attach(self, container: str) -> None:
        if self.container_id:
            self._log("[red]Already connected. Detach/terminate first.[/red]")
            return
        try:
            host_port = docker_port(container, 6080)
            vnc_url = f"http://localhost:{host_port}?view_only=true&autoconnect=true&resize=scale"
            self.container_id = container
            self._attached = True
            self._vnc_url = vnc_url
            self._update_status()
            self._log(f"Attached: {container[:12]}")
            self._log(f"noVNC: {vnc_url}")
        except subprocess.CalledProcessError:
            self._log(f"[red]Could not attach to '{container}'[/red]")

    def _do_detach(self) -> None:
        if not self.container_id:
            self._log("[red]No container[/red]")
            return
        self._log(f"Detached from {self.container_id[:12]}")
        self.container_id = None
        self._attached = False
        self._vnc_url = None
        self._update_status()
        self._refresh_containers()

    @work(thread=True)
    def _do_terminate(self) -> None:
        if not self.container_id:
            self.call_from_thread(self._log, "[red]No container[/red]")
            return
        if self._attached:
            self.call_from_thread(
                self._log,
                "[red]Container was attached, not launched. Use detach.[/red]",
            )
            return
        cid = self.container_id
        self.call_from_thread(self._log, "Terminating...")
        try:
            docker_stop(cid)
            self.container_id = None
            self._attached = False
            self._vnc_url = None
            self.call_from_thread(self._update_status)
            self.call_from_thread(self._log, f"Removed {cid[:12]}")
            self.call_from_thread(self._refresh_containers)
        except subprocess.CalledProcessError as e:
            self.call_from_thread(self._log, f"[red]{e.stderr}[/red]")

    def action_focus_log(self) -> None:
        self.query_one("#log", RichLog).focus()

    def action_quit(self) -> None:
        if self.container_id and not self._attached:
            # Best-effort cleanup
            try:
                docker_stop(self.container_id)
            except Exception:
                pass
        self.exit()


if __name__ == "__main__":
    ComputerTestApp().run()
