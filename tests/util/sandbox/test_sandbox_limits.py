import pytest

from inspect_ai.util._sandbox.limits import (
    OutputLimitExceededError,
    SandboxEnvironmentLimits,
    _human_readable_size,
    _parse_limit_env_var,
    reset_sandbox_limits,
    set_sandbox_limits,
    verify_read_file_size,
)


def test_default_limits():
    assert SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE == 10 * 1024**2
    assert SandboxEnvironmentLimits.MAX_READ_FILE_SIZE == 100 * 1024**2


def test_default_limit_strs():
    assert SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR == "10 MiB"
    assert SandboxEnvironmentLimits.MAX_READ_FILE_SIZE_STR == "100 MiB"


def test_set_and_reset_limits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INSPECT_SANDBOX_MAX_READ_FILE_SIZE", "1048576")
    monkeypatch.setenv("INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE", "2097152")
    tokens = set_sandbox_limits()
    assert SandboxEnvironmentLimits.MAX_READ_FILE_SIZE == 1048576
    assert SandboxEnvironmentLimits.MAX_READ_FILE_SIZE_STR == "1 MiB"
    assert SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE == 2097152
    assert SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR == "2 MiB"
    reset_sandbox_limits(tokens)
    assert SandboxEnvironmentLimits.MAX_READ_FILE_SIZE == 100 * 1024**2
    assert SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE == 10 * 1024**2


def test_set_limits_partial(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INSPECT_SANDBOX_MAX_READ_FILE_SIZE", "5242880")
    monkeypatch.delenv("INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE", raising=False)
    tokens = set_sandbox_limits()
    assert SandboxEnvironmentLimits.MAX_READ_FILE_SIZE == 5242880
    assert SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE == 10 * 1024**2
    reset_sandbox_limits(tokens)


def test_set_limits_no_env_vars(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INSPECT_SANDBOX_MAX_READ_FILE_SIZE", raising=False)
    monkeypatch.delenv("INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE", raising=False)
    tokens = set_sandbox_limits()
    assert tokens == []
    assert SandboxEnvironmentLimits.MAX_READ_FILE_SIZE == 100 * 1024**2


def test_human_readable_size():
    assert _human_readable_size(1024**3) == "1 GiB"
    assert _human_readable_size(2 * 1024**3) == "2 GiB"
    assert _human_readable_size(1024**2) == "1 MiB"
    assert _human_readable_size(10 * 1024**2) == "10 MiB"
    assert _human_readable_size(1024) == "1 KiB"
    assert _human_readable_size(500) == "500 bytes"
    assert _human_readable_size(1024**2 + 1) == f"{1024**2 + 1} bytes"


def test_parse_limit_env_var_valid():
    assert _parse_limit_env_var("TEST_VAR", "1048576") == 1048576


def test_parse_limit_env_var_non_numeric():
    with pytest.raises(ValueError, match="must be an integer"):
        _parse_limit_env_var("TEST_VAR", "200MB")


def test_parse_limit_env_var_zero():
    with pytest.raises(ValueError, match="must be a positive integer"):
        _parse_limit_env_var("TEST_VAR", "0")


def test_parse_limit_env_var_negative():
    with pytest.raises(ValueError, match="must be a positive integer"):
        _parse_limit_env_var("TEST_VAR", "-1")


def test_verify_read_file_size_under_limit(tmp_path):
    f = tmp_path / "small.txt"
    f.write_text("hello")
    verify_read_file_size(str(f))  # should not raise


def test_verify_read_file_size_over_custom_limit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("INSPECT_SANDBOX_MAX_READ_FILE_SIZE", "5")
    tokens = set_sandbox_limits()
    f = tmp_path / "big.txt"
    f.write_text("hello world")
    with pytest.raises(OutputLimitExceededError):
        verify_read_file_size(str(f))
    reset_sandbox_limits(tokens)
