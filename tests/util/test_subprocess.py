import os
import shutil
import time
from pathlib import Path
from random import random

import psutil
import pytest

from inspect_ai.util import subprocess


@pytest.mark.anyio
async def test_subprocess_execute():
    result = await subprocess(["python3", "-c", "print('foo')"])
    assert result.stdout.strip() == "foo"


@pytest.mark.anyio
async def test_subprocess_fail():
    result = await subprocess(["cat", "phantom.txt"])
    assert result.success is False


@pytest.mark.anyio
async def test_subprocess_stdin():
    input = "tell me a story"
    result = await subprocess(
        ["python3", "-c", "import sys; print(sys.stdin.read())"], input=input
    )
    assert result.stdout.strip() == input


@pytest.mark.anyio
async def test_subprocess_binary():
    input = "tell me a story".encode()
    result = await subprocess(
        ["python3", "-c", "import sys; print(sys.stdin.read())"],
        text=False,
        input=input,
    )
    assert result.stdout.decode().strip() == input.decode()


@pytest.mark.anyio
async def test_subprocess_cwd():
    parent_dir = Path(os.getcwd()).parent.as_posix()
    result = await subprocess(
        ["python3", "-c", "import os; print(os.getcwd())"], cwd=parent_dir
    )
    assert result.stdout.strip() == parent_dir


@pytest.mark.anyio
async def test_subprocess_env():
    ENV_VAR = "TEST_SUBPROCESS_ENV"
    ENV_VALUE = "test value"
    result = await subprocess(
        ["python3", "-c", f"import os; print(os.getenv('{ENV_VAR}'))"],
        env={ENV_VAR: ENV_VALUE},
    )
    assert result.stdout.strip() == ENV_VALUE


@pytest.mark.anyio
async def test_subprocess_timeout():
    # The random() serves as adding a unique "signature" to the subprocess command
    timeout_duration = 10 + random()
    subprocess_cmds = ["sleep", str(timeout_duration)]
    subprocess_pattern = " ".join(subprocess_cmds)
    assert not _process_found(subprocess_pattern), (
        f"There is already a process matching {subprocess_cmds}; the test isn't going to work"
    )

    with pytest.raises(TimeoutError):
        await subprocess(subprocess_cmds, timeout=1)

    assert not _process_found(subprocess_pattern), "Process is still running"


@pytest.mark.anyio
@pytest.mark.slow
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
async def test_subprocess_which_ignores_sigterm_timeout():
    timeout_duration = 10 + random()
    subprocess_cmds = ["bash", "-c", f"trap '' TERM; sleep {timeout_duration}"]
    subprocess_pattern = " ".join(subprocess_cmds)
    assert not _process_found(subprocess_pattern), (
        f"There is already a process matching {subprocess_cmds}; the test isn't going to work"
    )
    start_time = time.time()

    with pytest.raises(TimeoutError):
        await subprocess(subprocess_cmds, timeout=1)

    assert not _process_found(subprocess_pattern), "Process is still running"
    # process takes ~10s. subprocess() should return well within 5s
    # (1s + 2s grace period + 2s tolerance). If not, it is likely that it was not killed
    # and the process ran to completion.
    assert time.time() - start_time < 5, "Process was not killed in time"


def _process_found(pattern: str) -> bool:
    return any(
        pattern in " ".join(p.info["cmdline"] or [])
        for p in psutil.process_iter(["cmdline"])
    )
