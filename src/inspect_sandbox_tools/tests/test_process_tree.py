import asyncio
import sys

import psutil
import pytest
from inspect_sandbox_tools._util.process_tree import terminate_process_tree


async def _start_signal_test_process(handler: str) -> asyncio.subprocess.Process:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        (
            "import signal,subprocess,time; "
            f"signal.signal(signal.SIGTERM, {handler}); "
            "print('ready', flush=True); "
            "time.sleep(300)"
        ),
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert await asyncio.wait_for(process.stdout.readline(), timeout=5) == b"ready\n"
    return process


async def _ensure_stopped(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.kill()
        await process.wait()


@pytest.mark.asyncio
async def test_terminate_process_tree_is_idempotent_after_process_exit() -> None:
    process = await asyncio.create_subprocess_exec("true")
    await process.wait()

    await terminate_process_tree(process)


@pytest.mark.asyncio
async def test_terminate_process_tree_kills_group_after_root_exits() -> None:
    child_script = (
        "import signal,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); "
        "time.sleep(300)"
    )
    root_script = (
        "import subprocess,sys; "
        f"child=subprocess.Popen([sys.executable, '-c', {child_script!r}], "
        "stdout=subprocess.PIPE, text=True); "
        "assert child.stdout; child.stdout.readline(); "
        "print(child.pid, flush=True)"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        root_script,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None
    child_pid = int(await asyncio.wait_for(process.stdout.readline(), timeout=5))
    await process.wait()

    try:
        await terminate_process_tree(process, timeout=0.2, process_group=True)
        assert not psutil.pid_exists(child_pid)
    finally:
        if psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()


@pytest.mark.asyncio
async def test_terminate_process_tree_kills_known_descendant_after_root_exits() -> None:
    child_script = "import time; time.sleep(300)"
    root_script = (
        "import subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child_script!r}], "
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "print(child.pid, flush=True); "
        "time.sleep(300)"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        root_script,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None
    child_pid = int(await asyncio.wait_for(process.stdout.readline(), timeout=5))

    try:
        known_descendants = psutil.Process(process.pid).children(recursive=True)
        assert [child.pid for child in known_descendants] == [child_pid]

        process.terminate()
        await process.wait()
        await terminate_process_tree(
            process, timeout=0.2, known_descendants=known_descendants
        )

        assert not psutil.pid_exists(child_pid)
    finally:
        await _ensure_stopped(process)
        if psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()


@pytest.mark.asyncio
async def test_terminate_process_tree_propagates_cancellation_after_cleanup() -> None:
    process = await _start_signal_test_process("signal.SIG_IGN")
    try:
        terminate = asyncio.create_task(terminate_process_tree(process, timeout=30))
        await asyncio.sleep(0.05)
        terminate.cancel()

        with pytest.raises(asyncio.CancelledError):
            await terminate
        assert process.returncode is not None
    finally:
        await _ensure_stopped(process)


@pytest.mark.asyncio
async def test_terminate_process_tree_defers_cancellation_until_reparented_child_exits() -> (
    None
):
    child_script = (
        "import signal,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); "
        "time.sleep(300)"
    )
    root_script = (
        "import subprocess,sys; "
        f"child=subprocess.Popen([sys.executable, '-c', {child_script!r}], "
        "stdout=subprocess.PIPE, text=True); "
        "assert child.stdout; child.stdout.readline(); "
        "print(child.pid, flush=True)"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        root_script,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None
    child_pid = int(await asyncio.wait_for(process.stdout.readline(), timeout=5))
    await process.wait()

    try:
        terminate = asyncio.create_task(
            terminate_process_tree(process, timeout=30, process_group=True)
        )
        await asyncio.sleep(0.05)
        terminate.cancel()

        with pytest.raises(asyncio.CancelledError):
            await terminate
        assert not psutil.pid_exists(child_pid)
    finally:
        if psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()


@pytest.mark.asyncio
async def test_terminate_process_tree_finds_children_spawned_during_grace_period() -> (
    None
):
    handler = (
        "lambda *_: (print(subprocess.Popen(['sleep', '300'], "
        "start_new_session=True).pid, flush=True))"
    )
    process = await _start_signal_test_process(handler)
    assert process.stdout is not None
    child_pid: int | None = None
    try:
        terminate = asyncio.create_task(terminate_process_tree(process, timeout=0.2))
        child_pid = int(await asyncio.wait_for(process.stdout.readline(), timeout=5))
        await terminate

        assert process.returncode is not None
        assert not psutil.pid_exists(child_pid)
    finally:
        await _ensure_stopped(process)
        if child_pid is not None and psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()
