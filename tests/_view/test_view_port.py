import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest

from inspect_ai._view.view import view_acquire_port, view_port_pid_file

PORT = 7575

# acquires the port, then exits normally once a line arrives on stdin
VIEW_SERVER = """
import sys
from pathlib import Path
from inspect_ai._view.view import view_acquire_port
view_acquire_port(Path(sys.argv[1]), int(sys.argv[2]))
print("ready", flush=True)
sys.stdin.readline()
"""


@pytest.fixture
def other_process() -> Iterator[subprocess.Popen[bytes]]:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def view_server(tmp_path: Path) -> Iterator[subprocess.Popen[str]]:
    with subprocess.Popen(
        [sys.executable, "-c", VIEW_SERVER, str(tmp_path), str(PORT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as proc:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        yield proc
        proc.kill()


def test_stale_pid_file_does_not_terminate_unrelated_process(
    tmp_path: Path, other_process: subprocess.Popen[bytes]
) -> None:
    # a pid file left behind by a server that was killed, whose pid the OS
    # has since given to an unrelated process
    view_port_pid_file(tmp_path, PORT).write_text(str(other_process.pid))

    view_acquire_port(tmp_path, PORT)

    assert other_process.poll() is None


def test_reused_pid_with_other_start_time_is_not_terminated(
    tmp_path: Path, other_process: subprocess.Popen[bytes]
) -> None:
    create_time = psutil.Process(other_process.pid).create_time()
    view_port_pid_file(tmp_path, PORT).write_text(
        f"{other_process.pid} {create_time - 100}"
    )

    view_acquire_port(tmp_path, PORT)

    assert other_process.poll() is None


def test_running_view_server_is_terminated(
    tmp_path: Path, view_server: subprocess.Popen[str]
) -> None:
    view_acquire_port(tmp_path, PORT)

    assert view_server.wait(5) is not None
    assert view_port_pid_file(tmp_path, PORT).read_text().split()[0] == str(
        psutil.Process().pid
    )


def test_view_server_is_terminated_despite_small_clock_step(
    tmp_path: Path, view_server: subprocess.Popen[str]
) -> None:
    pid_file = view_port_pid_file(tmp_path, PORT)
    pid, create_time = pid_file.read_text().split()
    pid_file.write_text(f"{pid} {float(create_time) + 1}")

    view_acquire_port(tmp_path, PORT)

    assert view_server.wait(5) is not None


def test_legacy_pid_file_is_left_for_older_versions(tmp_path: Path) -> None:
    # older versions parse `ports/<port>` as a bare pid outside any error
    # handling, so writing our pid and start time there would crash them
    legacy_pid_file = tmp_path / "ports" / str(PORT)

    view_acquire_port(tmp_path, PORT)

    assert not legacy_pid_file.exists()


def test_own_pid_file_is_not_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminated: list[int] = []
    monkeypatch.setattr(
        psutil.Process, "terminate", lambda self: terminated.append(self.pid)
    )

    view_acquire_port(tmp_path, PORT)
    view_acquire_port(tmp_path, PORT)

    assert terminated == []


def test_exit_keeps_pid_file_taken_by_newer_server(
    tmp_path: Path, view_server: subprocess.Popen[str]
) -> None:
    pid_file = view_port_pid_file(tmp_path, PORT)
    pid_file.write_text("12345 1.0")

    assert view_server.stdin is not None
    view_server.stdin.write("exit\n")
    view_server.stdin.flush()
    assert view_server.wait(5) == 0

    assert pid_file.read_text() == "12345 1.0"


def test_exit_removes_own_pid_file(
    tmp_path: Path, view_server: subprocess.Popen[str]
) -> None:
    assert view_server.stdin is not None
    view_server.stdin.write("exit\n")
    view_server.stdin.flush()
    assert view_server.wait(5) == 0

    assert not view_port_pid_file(tmp_path, PORT).exists()
