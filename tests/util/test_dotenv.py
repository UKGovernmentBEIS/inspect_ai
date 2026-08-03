"""Unit coverage for `init_dotenv()` .env precedence.

The CLI config tests in `tests/test_eval_config.py` run in-process via
`CliRunner`, which invokes `eval_command` directly and so never reaches
`init_dotenv()` (it lives in `main()`, the console entry point). These tests
exercise the `.env` precedence behavior directly so a regression in it is
caught regardless of how the CLI is driven. The real entry-point wiring
(`main()` -> `init_dotenv()` -> command) still has integration coverage via the
subprocess-based CLI tests (e.g. tests/log/test_eval_log_config.py).
"""

import inspect_ai._util.dotenv as dotenv_mod
from inspect_ai._util.dotenv import init_dotenv

_VAR = "INSPECT_TEST_DOTENV_VAR"


def test_dotenv_does_not_override_existing_env_outside_vscode(tmp_path, monkeypatch):
    """Outside vscode, a value already in the environment beats the .env file."""
    monkeypatch.setattr(dotenv_mod, "is_running_in_vscode", lambda: False)
    (tmp_path / ".env").write_text(f"{_VAR}=from_dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_VAR, "from_env")

    init_dotenv()

    assert dotenv_mod.os.environ[_VAR] == "from_env"


def test_dotenv_overrides_existing_env_in_vscode(tmp_path, monkeypatch):
    """In vscode, .env overrides the environment so session edits take effect."""
    monkeypatch.setattr(dotenv_mod, "is_running_in_vscode", lambda: True)
    (tmp_path / ".env").write_text(f"{_VAR}=from_dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_VAR, "from_env")

    init_dotenv()

    assert dotenv_mod.os.environ[_VAR] == "from_dotenv"


def test_dotenv_loads_var_absent_from_environment(tmp_path, monkeypatch):
    """A .env var not present in the environment is loaded regardless of mode."""
    monkeypatch.setattr(dotenv_mod, "is_running_in_vscode", lambda: False)
    (tmp_path / ".env").write_text(f"{_VAR}=from_dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_VAR, raising=False)

    init_dotenv()

    assert dotenv_mod.os.environ[_VAR] == "from_dotenv"
