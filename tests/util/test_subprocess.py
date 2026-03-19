import logging
import os
import shutil
import sys
import time
from pathlib import Path
from random import random

import psutil
import pytest

from inspect_ai.util import subprocess
from inspect_ai.util._subprocess import _log_stream


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
@pytest.mark.skipif(
    sys.platform == "darwin", reason="Different termination behavior on MacOS"
)
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


@pytest.mark.anyio
async def test_subprocess_output_limit_under_limit():
    """Test that output under the limit is returned fully."""
    result = await subprocess(
        ["python3", "-c", "print('hello')"],
        output_limit=1000,
    )
    assert result.success is True
    assert result.stdout.strip() == "hello"


@pytest.mark.anyio
async def test_subprocess_output_limit_keeps_trailing():
    """Test that output_limit keeps trailing bytes, not leading."""
    # Generate output: "0" * 100 + "1" * 100 + ... + "9" * 100 = 1000 bytes total
    script = """
import sys
for i in range(10):
    sys.stdout.write(str(i) * 100)
    sys.stdout.flush()
"""
    result = await subprocess(
        ["python3", "-c", script],
        output_limit=250,
        text=False,
    )
    assert result.success is True
    # Should contain trailing digits (7s, 8s, 9s), not leading (0s, 1s)
    assert result.stdout[-100:] == b"9" * 100
    assert b"0" * 50 not in result.stdout  # Leading 0s should be gone


@pytest.mark.anyio
async def test_subprocess_output_limit_process_completes():
    """Test that process completes even when output exceeds limit."""
    # Script that produces output then a final marker
    script = """
import sys
for i in range(100):
    print("x" * 100)  # 10KB+ of output
print("COMPLETED")
"""
    result = await subprocess(
        ["python3", "-c", script],
        output_limit=500,
    )
    # Process should complete and return "COMPLETED" in trailing output
    assert "COMPLETED" in result.stdout
    assert result.success is True


@pytest.mark.anyio
async def test_subprocess_output_limit_binary():
    """Test output_limit with binary mode."""
    result = await subprocess(
        ["python3", "-c", "import sys; sys.stdout.buffer.write(b'x' * 100)"],
        text=False,
        output_limit=50,
    )
    assert result.success is True
    assert len(result.stdout) == 50
    assert result.stdout == b"x" * 50


@pytest.mark.anyio
async def test_subprocess_output_limit_no_limit():
    """Test that no output_limit returns all output."""
    script = "print('a' * 1000)"
    result = await subprocess(
        ["python3", "-c", script],
        output_limit=None,
    )
    assert result.success is True
    assert len(result.stdout.strip()) == 1000


@pytest.mark.anyio
async def test_subprocess_redirect_to_logger(monkeypatch, caplog):
    monkeypatch.setenv("INSPECT_SUBPROCESS_REDIRECT_TO_LOGGER", "1")
    with caplog.at_level(logging.INFO, logger="inspect_ai.util._subprocess"):
        result = await subprocess(
            [
                "python3",
                "-c",
                "import sys; print('from stdout'); print('from stderr', file=sys.stderr)",
            ],
            capture_output=False,
        )
    assert result.success is True
    assert result.stdout == ""
    assert result.stderr == ""
    messages = {r.message for r in caplog.records}
    assert "from stdout" in messages
    assert "from stderr" in messages


@pytest.mark.anyio
async def test_subprocess_redirect_to_logger_does_not_affect_capture(monkeypatch):
    monkeypatch.setenv("INSPECT_SUBPROCESS_REDIRECT_TO_LOGGER", "1")
    result = await subprocess(
        ["python3", "-c", "print('captured output')"],
        capture_output=True,
    )
    assert result.success is True
    assert result.stdout.strip() == "captured output"


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.anyio
async def test_log_stream_splits_across_chunks(caplog):
    stream = _FakeStream([b"line1\nli", b"ne2\nline3"])
    with caplog.at_level(logging.INFO, logger="inspect_ai.util._subprocess"):
        await _log_stream(stream)
    messages = [r.message for r in caplog.records]
    assert messages == ["line1", "line2", "line3"]


@pytest.mark.anyio
async def test_log_stream_trailing_without_newline(caplog):
    stream = _FakeStream([b"line1\nline2"])
    with caplog.at_level(logging.INFO, logger="inspect_ai.util._subprocess"):
        await _log_stream(stream)
    messages = [r.message for r in caplog.records]
    assert messages == ["line1", "line2"]


@pytest.mark.anyio
async def test_log_stream_empty_lines(caplog):
    stream = _FakeStream([b"a\n\nb\n"])
    with caplog.at_level(logging.INFO, logger="inspect_ai.util._subprocess"):
        await _log_stream(stream)
    messages = [r.message for r in caplog.records]
    assert messages == ["a", "", "b"]
