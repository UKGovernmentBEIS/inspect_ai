#!/usr/bin/env python3
"""Interactive REPL for testing the sandbox computer use tool directly via Docker."""

from __future__ import annotations

import cmd
import json
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

DEFAULT_IMAGE = "aisiuk/inspect-computer-tool"
TOOL_PATH = "python3 /opt/inspect/tool/computer_tool.py"


def docker_run(image: str) -> str:
    """Launch container, return container ID."""
    result = subprocess.run(
        ["docker", "run", "-d", "--init", "-p", "5900", "-p", "6080", image],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def docker_port(container_id: str, port: int) -> int:
    """Get host port mapping for a container port."""
    result = subprocess.run(
        ["docker", "port", container_id, str(port)],
        capture_output=True,
        text=True,
        check=True,
    )
    # output like "0.0.0.0:61030" or ":::61030"
    return int(result.stdout.strip().split(":")[-1])


def docker_exec(container_id: str, cmd_tail: list[str], timeout: int = 180) -> dict:
    """Execute a computer tool command in the container, return parsed JSON."""
    full_cmd = ["docker", "exec", container_id] + TOOL_PATH.split() + cmd_tail
    result = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (rc={result.returncode}): {result.stderr}")
    return json.loads(result.stdout)


def docker_stop(container_id: str) -> None:
    subprocess.run(["docker", "stop", container_id], capture_output=True, check=True)
    subprocess.run(["docker", "rm", container_id], capture_output=True, check=True)


def display_image(b64_data: str) -> None:
    """Write base64 PNG to a temp file and open in default viewer."""
    import base64

    path = Path(tempfile.mktemp(suffix=".png"))
    path.write_bytes(base64.b64decode(b64_data))
    webbrowser.open(path.as_uri())


def handle_result(result: dict, show_images: bool) -> None:
    if result.get("error"):
        print(f"\033[91mError: {result['error']}\033[0m")
        return
    if result.get("output"):
        print(result["output"])
    if result.get("base64_image"):
        if show_images:
            display_image(result["base64_image"])
        else:
            print("(screenshot returned)")


def require_args(args: str, n: int, usage: str) -> list[str] | None:
    parts = args.split()
    if len(parts) < n:
        print(f"Usage: {usage}")
        return None
    return parts


class ComputerREPL(cmd.Cmd):
    prompt = "computer> "
    intro = "Computer Use Test Tool. Type 'help' for commands, 'launch' to start."

    def __init__(self, image: str = DEFAULT_IMAGE) -> None:
        super().__init__()
        self.image = image
        self.container_id: str | None = None
        self._attached = False
        self.show_images = False

    def _require_container(self) -> bool:
        if not self.container_id:
            print("No container running. Use 'launch' first.")
            return False
        return True

    def _exec(self, cmd_tail: list[str]) -> None:
        if not self._require_container():
            return
        assert self.container_id
        try:
            result = docker_exec(self.container_id, cmd_tail)
            handle_result(result, self.show_images)
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            print(f"\033[91m{e}\033[0m")

    # --- container lifecycle ---

    def do_launch(self, _args: str) -> None:
        """Launch the computer use container."""
        if self.container_id:
            print("Already connected. Use 'terminate' or 'detach' first.")
            return
        print(f"Launching {self.image}...")
        try:
            self.container_id = docker_run(self.image)
            self._attached = False
            host_port = docker_port(self.container_id, 6080)
            vnc_url = f"http://localhost:{host_port}?view_only=true&autoconnect=true&resize=scale"
            print(f"Container: {self.container_id[:12]}")
            print(f"noVNC: {vnc_url}")
        except subprocess.CalledProcessError as e:
            print(f"\033[91mFailed to launch: {e.stderr}\033[0m")
            self.container_id = None

    def do_attach(self, args: str) -> None:
        """Attach to an existing container.

        Usage: attach <container_id_or_name>

        Attaches to a running container and prints its noVNC URL.
        Use 'detach' to disconnect without stopping it.
        """
        if self.container_id:
            print("Already connected. Use 'terminate' or 'detach' first.")
            return
        if not args:
            print("Usage: attach <container_id_or_name>")
            return
        container = args.strip()
        try:
            host_port = docker_port(container, 6080)
            vnc_url = f"http://localhost:{host_port}?view_only=true&autoconnect=true&resize=scale"
            self.container_id = container
            self._attached = True
            print(f"Attached: {container}")
            print(f"noVNC: {vnc_url}")
        except subprocess.CalledProcessError:
            print(
                f"\033[91mCould not attach to '{container}'. Is it running with port 6080 exposed?\033[0m"
            )

    def do_detach(self, _args: str) -> None:
        """Detach from the current container without stopping it."""
        if not self._require_container():
            return
        assert self.container_id
        print(f"Detached from {self.container_id[:12]}")
        self.container_id = None
        self._attached = False

    def do_terminate(self, _args: str) -> None:
        """Stop and remove the container (or detach if attached)."""
        if not self._require_container():
            return
        assert self.container_id
        if self._attached:
            print(
                "Container was attached, not launched by us. Use 'detach' to disconnect,"
            )
            print("or use 'docker stop' directly if you really want to stop it.")
            return
        print("Terminating...")
        try:
            docker_stop(self.container_id)
            print(f"Removed {self.container_id[:12]}")
        except subprocess.CalledProcessError as e:
            print(f"\033[91m{e.stderr}\033[0m")
        self.container_id = None

    # --- no-arg actions ---

    def do_screenshot(self, _args: str) -> None:
        """Take a screenshot.

        Returns a screenshot of the current desktop state.
        """
        self._exec(["screenshot"])

    def do_cursor_position(self, _args: str) -> None:
        """Get the current (x, y) pixel coordinate of the cursor on the screen."""
        self._exec(["cursor_position"])

    def do_left_mouse_down(self, _args: str) -> None:
        """Press the left mouse button (without releasing)."""
        self._exec(["left_mouse_down"])

    def do_left_mouse_up(self, _args: str) -> None:
        """Release the left mouse button."""
        self._exec(["left_mouse_up"])

    # --- text-based actions ---

    def do_key(self, args: str) -> None:
        """Press a key or key-combination on the keyboard.

        Usage: key <text>

        Text can be any key name supported by xdotool's `key` such as:
          Return, Escape, BackSpace, Tab, Delete, Home, End, Prior, Next,
          Up, Down, Left, Right, F1-F12, Insert, Pause,
          Shift_L, Control_L, Alt_L, Caps_Lock, Num_Lock, Scroll_Lock,
          KP_0-KP_9, KP_Enter, KP_Add, KP_Subtract, KP_Multiply, KP_Divide

        Key combinations use +: ctrl+s, alt+Tab, ctrl+shift+t

        Examples: key Return | key ctrl+s | key alt+Tab
        """
        if not args:
            print("Usage: key <text>")
            return
        self._exec(["key", "--text", args])

    def do_hold_key(self, args: str) -> None:
        """Hold down a key or multiple keys for a specified duration (seconds).

        Usage: hold_key <text> <duration>

        Supports the same key syntax as 'key'.
        Example: hold_key shift 2
        """
        parts = require_args(args, 2, "hold_key <text> <duration>")
        if not parts:
            return
        self._exec(["hold_key", "--text", parts[0], "--duration", parts[1]])

    def do_type(self, args: str) -> None:
        """Type a string of text on the keyboard.

        Usage: type <text>

        Example: type The crux of the biscuit is the apostrophe!
        """
        if not args:
            print("Usage: type <text>")
            return
        self._exec(["type", "--text", args])

    # --- coordinate-based actions ---

    def _do_coord_action(self, action: str, args: str) -> None:
        parts = require_args(args, 2, f"{action} <x> <y>")
        if not parts:
            return
        self._exec([action, "--coordinate", parts[0], parts[1]])

    def do_mouse_move(self, args: str) -> None:
        """Move the cursor to a specified (x, y) pixel coordinate.

        Usage: mouse_move <x> <y>

        Example: mouse_move 100 200
        """
        self._do_coord_action("mouse_move", args)

    def do_left_click(self, args: str) -> None:
        """Click the left mouse button at a coordinate.

        Usage: left_click <x> <y>

        Icons require double_click to open; buttons/menus use left_click.
        """
        self._do_coord_action("left_click", args)

    def do_right_click(self, args: str) -> None:
        """Click the right mouse button (context menu) at a coordinate.

        Usage: right_click <x> <y>
        """
        self._do_coord_action("right_click", args)

    def do_middle_click(self, args: str) -> None:
        """Click the middle mouse button at a coordinate.

        Usage: middle_click <x> <y>
        """
        self._do_coord_action("middle_click", args)

    def do_back_click(self, args: str) -> None:
        """Click the 'back' mouse button at a coordinate.

        Usage: back_click <x> <y>
        """
        self._do_coord_action("back_click", args)

    def do_forward_click(self, args: str) -> None:
        """Click the 'forward' mouse button at a coordinate.

        Usage: forward_click <x> <y>
        """
        self._do_coord_action("forward_click", args)

    def do_double_click(self, args: str) -> None:
        """Double-click the left mouse button at a coordinate.

        Usage: double_click <x> <y>

        Use double_click to open desktop icons.
        """
        self._do_coord_action("double_click", args)

    def do_triple_click(self, args: str) -> None:
        """Triple-click the left mouse button at a coordinate.

        Usage: triple_click <x> <y>

        Typically selects an entire line of text.
        """
        self._do_coord_action("triple_click", args)

    # --- drag ---

    def do_left_click_drag(self, args: str) -> None:
        """Click and drag from one coordinate to another.

        Usage: left_click_drag <start_x> <start_y> <end_x> <end_y>

        Example: left_click_drag 100 200 300 400
        """
        parts = require_args(args, 4, "left_click_drag <sx> <sy> <ex> <ey>")
        if not parts:
            return
        self._exec(
            [
                "left_click_drag",
                "--start_coordinate",
                parts[0],
                parts[1],
                "--coordinate",
                parts[2],
                parts[3],
            ]
        )

    # --- scroll ---

    def do_scroll(self, args: str) -> None:
        """Scroll the screen by a number of 'clicks' in a direction.

        Usage: scroll <amount> <up|down|left|right> [<x> <y>]

        Optional coordinate positions the cursor before scrolling.
        Example: scroll 3 down | scroll 5 up 500 400
        """
        parts = require_args(args, 2, "scroll <amount> <direction> [<x> <y>]")
        if not parts:
            return
        cmd_args = [
            "scroll",
            "--scroll_amount",
            parts[0],
            "--scroll_direction",
            parts[1],
        ]
        if len(parts) >= 4:
            cmd_args += ["--coordinate", parts[2], parts[3]]
        self._exec(cmd_args)

    # --- wait ---

    def do_wait(self, args: str) -> None:
        """Wait for a specified duration (in seconds).

        Usage: wait <duration>

        Example: wait 3
        """
        if not args:
            print("Usage: wait <duration>")
            return
        self._exec(["wait", "--duration", args.split()[0]])

    # --- zoom ---

    def do_zoom(self, args: str) -> None:
        """Take a zoomed-in screenshot of a region at native resolution.

        Usage: zoom <x0> <y0> <x1> <y1>

        Region is specified as [x0, y0, x1, y1] bounding box coordinates.
        Example: zoom 100 100 500 400
        """
        parts = require_args(args, 4, "zoom <x0> <y0> <x1> <y1>")
        if not parts:
            return
        self._exec(["zoom", "--region", parts[0], parts[1], parts[2], parts[3]])

    # --- settings ---

    def do_show_images(self, _args: str) -> None:
        """Toggle displaying screenshots in the default image viewer.

        Off by default. When on, each screenshot opens in your system viewer.
        """
        self.show_images = not self.show_images
        state = "ON" if self.show_images else "OFF"
        print(f"Show images: {state}")

    # --- quit ---

    def do_quit(self, _args: str) -> bool:
        """Exit. Terminates launched containers; detaches from attached ones."""
        if self.container_id:
            if self._attached:
                self.do_detach("")
            else:
                self.do_terminate("")
        return True

    do_EOF = do_quit


def main() -> None:
    image = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMAGE
    repl = ComputerREPL(image)
    try:
        repl.cmdloop()
    except KeyboardInterrupt:
        print()
        if repl.container_id:
            repl.do_terminate("")


if __name__ == "__main__":
    main()
