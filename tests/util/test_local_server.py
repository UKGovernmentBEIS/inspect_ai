import io
import itertools
import json
import logging
import subprocess
import time
from typing import Any, cast

import httpx
import pytest

from inspect_ai._util import local_server
from inspect_ai._util.local_server import _server_arg_to_cli_key


def test_server_arg_to_cli_key_converts_top_level_underscores() -> None:
    assert _server_arg_to_cli_key("tensor_parallel_size") == "tensor-parallel-size"


def test_server_arg_to_cli_key_preserves_dotted_nested_underscores() -> None:
    assert (
        _server_arg_to_cli_key("speculative_config.num_speculative_tokens")
        == "speculative-config.num_speculative_tokens"
    )


def test_server_arg_to_cli_key_preserves_multiple_nested_segments() -> None:
    assert (
        _server_arg_to_cli_key("speculative_config.draft_model.num_speculative_tokens")
        == "speculative-config.draft_model.num_speculative_tokens"
    )


SECRET = "sk-very-secret-value"


class _FakeProcess:
    pid = 12345

    def __init__(
        self,
        returncode: int | None = None,
        stdout: io.StringIO | None = None,
        stderr: io.StringIO | None = None,
    ) -> None:
        self._returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def poll(self) -> int | None:
        return self._returncode


def _start_with_mocks(
    monkeypatch: pytest.MonkeyPatch,
    process: _FakeProcess,
    timeout: int | None = None,
    server_args: dict[str, Any] | None = None,
) -> tuple[list[list[str]], str]:
    popen_calls: list[list[str]] = []

    def fake_popen(command: list[str], **kwargs: Any) -> _FakeProcess:
        popen_calls.append(list(command))
        return process

    def fake_get(*args: Any, **kwargs: Any) -> Any:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr(local_server, "terminate_process", lambda p: None)
    monkeypatch.setattr("time.sleep", lambda s: None)

    with pytest.raises(RuntimeError) as excinfo:
        local_server.start_local_server(
            ["vllm", "serve", "my-model", "--host", "0.0.0.0", "--api-key", SECRET],
            host="0.0.0.0",
            port=31234,
            api_key=SECRET,
            server_type="vLLM",
            timeout=timeout,
            server_args=server_args,
            env={"CUDA_VISIBLE_DEVICES": "0", "HF_TOKEN": SECRET},
        )
    return popen_calls, str(excinfo.value)


def test_start_failure_does_not_expose_api_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=local_server.__name__)
    popen_calls, error = _start_with_mocks(
        monkeypatch, _FakeProcess(returncode=1), server_args={"hf_token": SECRET}
    )

    # the real command still carries the secrets
    assert len(popen_calls) == 1
    assert popen_calls[0].count(SECRET) == 2
    assert "--api-key" in popen_calls[0]

    # but neither the log nor the error does
    assert "Started server with command" in caplog.text
    assert SECRET not in caplog.text
    assert "exited unexpectedly" in error
    assert SECRET not in error
    assert "--api-key ***" in error
    assert "--hf-token ***" in error
    assert "HF_TOKEN=***" in error
    assert "CUDA_VISIBLE_DEVICES=0" in error
    assert "vllm serve my-model" in error


def test_start_timeout_does_not_expose_api_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=local_server.__name__)
    # each clock read advances past the timeout
    times = itertools.count(start=0.0, step=100.0)
    monkeypatch.setattr("time.time", lambda: next(times))
    popen_calls, error = _start_with_mocks(
        monkeypatch, _FakeProcess(returncode=None), timeout=10
    )

    assert SECRET in popen_calls[0]
    assert "did not become ready" in error
    assert "--api-key ***" in error
    assert SECRET not in error
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "command,expected",
    [
        (["serve", "--api-key", "abc"], ["serve", "--api-key", "***"]),
        (["serve", "--api-key=abc"], ["serve", "--api-key=***"]),
        (["serve", "--hf-token", "abc"], ["serve", "--hf-token", "***"]),
        (["serve", "--admin_password", "abc"], ["serve", "--admin_password", "***"]),
        (["serve", "--client.secret=abc"], ["serve", "--client.secret=***"]),
        # unrelated flags are untouched
        (
            ["serve", "--max-num-batched-tokens", "8192", "--port", "1"],
            ["serve", "--max-num-batched-tokens", "8192", "--port", "1"],
        ),
        (["serve", "--ssl-keyfile", "k.pem"], ["serve", "--ssl-keyfile", "k.pem"]),
        # a valueless secret-named flag does not hide the next flag
        (["serve", "--api-key", "--port", "1"], ["serve", "--api-key", "--port", "1"]),
    ],
)
def test_redact_command(command: list[str], expected: list[str]) -> None:
    assert local_server.redact_command(command) == expected


def test_server_output_does_not_expose_api_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=local_server.__name__)
    stdout = io.StringIO(f"stdout args: api_key='{SECRET}'\n")
    stderr = io.StringIO(f"stderr non-default args: {{'api_key': '{SECRET}'}}\n")
    process = _FakeProcess(stdout=stdout, stderr=stderr)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: process)

    local_server.execute_shell_command(["vllm", "serve", "m", "--api-key", SECRET])

    # the reader threads close each stream once they reach its end
    deadline = time.monotonic() + 10
    while not (stdout.closed and stderr.closed):
        assert time.monotonic() < deadline
        time.sleep(0.01)

    assert "stdout args" in caplog.text
    assert "stderr non-default args" in caplog.text
    assert SECRET not in caplog.text


def test_short_secret_masked_only_as_quoted_value() -> None:
    redact = local_server._output_redactor(["test"])
    assert redact("non-default args: {'api_key': 'test'}") == (
        "non-default args: {'api_key': '***'}"
    )
    assert redact('api_key="test"') == 'api_key="***"'
    assert redact("running test suite on latest") == "running test suite on latest"


def test_secret_containing_another_secret_masked_whole() -> None:
    redact = local_server._output_redactor(["abcdefgh", "abcdefghXYZ"])
    assert redact("key abcdefghXYZ") == "key ***"


def test_default_api_key_masked_in_output() -> None:
    redact = local_server._output_redactor(["inspectai"])
    assert redact("api_key=inspectai") == "api_key=***"


def test_env_server_args_log_does_not_expose_secrets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=local_server.__name__)
    monkeypatch.setenv(
        "VLLM_DEFAULT_SERVER_ARGS",
        json.dumps({"hf_token": SECRET, "nested": {"api-key": SECRET}, "seed": 7}),
    )
    args = local_server.merge_env_server_args(
        "VLLM_DEFAULT_SERVER_ARGS", {}, logging.getLogger(local_server.__name__)
    )

    # the real args keep the secrets
    assert args["hf_token"] == SECRET
    assert args["nested"]["api-key"] == SECRET
    assert "Loaded server args" in caplog.text
    assert "'seed': 7" in caplog.text
    assert SECRET not in caplog.text


def test_env_server_args_parse_failure_does_not_echo_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=local_server.__name__)
    monkeypatch.setenv("SGLANG_DEFAULT_SERVER_ARGS", f"{{hf_token: {SECRET}")
    args = local_server.merge_env_server_args(
        "SGLANG_DEFAULT_SERVER_ARGS", {}, logging.getLogger(local_server.__name__)
    )

    assert args == {}
    assert "Failed to parse SGLANG_DEFAULT_SERVER_ARGS" in caplog.text
    assert SECRET not in caplog.text


def test_secret_note_shown_when_only_env_is_masked() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        local_server.wait_for_server(
            "http://localhost:1",
            cast("subprocess.Popen[str]", _FakeProcess(returncode=1)),
            full_command=["serve", "m"],
            env={"HF_TOKEN": SECRET},
        )
    error = str(excinfo.value)
    assert "HF_TOKEN=***" in error
    assert "Secret values are shown as ***" in error
    assert SECRET not in error
