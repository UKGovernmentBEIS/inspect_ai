import os
from pathlib import Path

import pytest

from inspect_ai.util import subprocess


@pytest.mark.asyncio
async def test_subprocess_execute():
    result = await subprocess(["python3", "-c", "print('foo')"])
    assert result.stdout.strip() == "foo"


@pytest.mark.asyncio
async def test_subprocess_fail():
    result = await subprocess(["cat", "phantom.txt"])
    assert result.success is False


@pytest.mark.asyncio
async def test_subprocess_stdin():
    input = "tell me a story"
    result = await subprocess(
        ["python3", "-c", "import sys; print(sys.stdin.read())"], input=input
    )
    assert result.stdout.strip() == input


@pytest.mark.asyncio
async def test_subprocess_binary():
    input = "tell me a story".encode()
    result = await subprocess(
        ["python3", "-c", "import sys; print(sys.stdin.read())"],
        text=False,
        input=input,
    )
    assert result.stdout.decode().strip() == input.decode()


@pytest.mark.asyncio
async def test_subprocess_cwd():
    parent_dir = Path(os.getcwd()).parent.as_posix()
    result = await subprocess(
        ["python3", "-c", "import os; print(os.getcwd())"], cwd=parent_dir
    )
    assert result.stdout.strip() == parent_dir


@pytest.mark.asyncio
async def test_subprocess_env():
    ENV_VAR = "TEST_SUBPROCESS_ENV"
    ENV_VALUE = "test value"
    result = await subprocess(
        ["python3", "-c", f"import os; print(os.getenv('{ENV_VAR}'))"],
        env={ENV_VAR: ENV_VALUE},
    )
    assert result.stdout.strip() == ENV_VALUE


@pytest.mark.asyncio
async def test_subprocess_timeout():
    result = await subprocess(["sleep", "2"], timeout=1)
    assert result.returncode == 1
