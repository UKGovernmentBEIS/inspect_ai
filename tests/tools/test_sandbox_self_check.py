import os
import signal
import subprocess
import time

from inspect_ai.util._sandbox.self_check import _timeout_child_process_command


def test_timeout_child_process_command_spawns_marker_processes() -> None:
    parent_marker = "timeout_parent_probe"
    child_marker = "timeout_child_probe"
    process = subprocess.Popen(
        _timeout_child_process_command(parent_marker, child_marker, sleep_seconds=5),
        start_new_session=True,
    )

    try:
        ps_output = ""
        group_output = ""
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            ps_output = subprocess.run(
                ["ps", "-axo", "pid=,pgid=,command="],
                capture_output=True,
                check=True,
                text=True,
            ).stdout
            group_lines = []
            for line in ps_output.splitlines():
                columns = line.split(maxsplit=2)
                if len(columns) >= 3 and columns[1] == str(process.pid):
                    group_lines.append(line)
            group_output = "\n".join(group_lines)
            if parent_marker in group_output and any(
                child_marker in line and parent_marker not in line
                for line in group_lines
            ):
                break
            time.sleep(0.05)

        assert parent_marker in group_output
        assert any(
            child_marker in line and parent_marker not in line
            for line in group_output.splitlines()
        ), group_output
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
