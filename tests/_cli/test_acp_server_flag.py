"""Tests for the `--acp-server` CLI option parsing.

The flag uses :func:`int_bool_or_str_flag_callback(True, None)` so the
parsed value is a `bool | int | str | None` union that maps cleanly
into ``EvalConfig.acp_server``.
"""

import click
from click.testing import CliRunner

from inspect_ai._cli.util import (
    int_bool_or_str_flag_callback,
    int_bool_or_str_retry_flag_callback,
)


def _build_cmd() -> click.Command:
    """Minimal click command that mirrors the real --acp-server option."""

    @click.command()
    @click.option(
        "--acp-server",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_bool_or_str_flag_callback(True, None),
        envvar="INSPECT_EVAL_ACP_SERVER",
    )
    def cmd(acp_server: bool | int | str | None) -> None:
        # echo the parsed value back through stdout so the test can read it
        click.echo(repr(acp_server))

    return cmd


def _parsed(args: list[str], env: dict[str, str] | None = None) -> object:
    """Run the test command and eval its echoed repr back to a Python value."""
    runner = CliRunner()
    result = runner.invoke(_build_cmd(), args, env=env, standalone_mode=False)
    assert result.exit_code == 0, result.output
    return eval(result.output.strip())


def test_bare_flag_enables() -> None:
    """`--acp-server` with no value → True (default-socket mode)."""
    assert _parsed(["--acp-server"]) is True


def test_explicit_true_enables() -> None:
    """`--acp-server=true` → True."""
    assert _parsed(["--acp-server=true"]) is True


def test_explicit_false_disables() -> None:
    """`--acp-server=false` → None (the configured false_value)."""
    assert _parsed(["--acp-server=false"]) is None


def test_integer_parses_as_port() -> None:
    """`--acp-server=12345` → int 12345 (TCP loopback port)."""
    assert _parsed(["--acp-server=12345"]) == 12345


def test_path_parses_as_string() -> None:
    """`--acp-server=/tmp/foo.sock` → string '/tmp/foo.sock' (socket path)."""
    assert _parsed(["--acp-server=/tmp/foo.sock"]) == "/tmp/foo.sock"


def test_omitted_returns_none() -> None:
    """Flag not provided → None (disabled)."""
    assert _parsed([]) is None


def test_env_var_integer() -> None:
    """`INSPECT_EVAL_ACP_SERVER=8000` env var → int 8000."""
    assert _parsed([], env={"INSPECT_EVAL_ACP_SERVER": "8000"}) == 8000


def test_env_var_true() -> None:
    """`INSPECT_EVAL_ACP_SERVER=true` env var → True."""
    assert _parsed([], env={"INSPECT_EVAL_ACP_SERVER": "true"}) is True


# ---------------------------------------------------------------------------
# Retry callback — distinguishes omitted (None → replay log) from explicit
# false (False → force disable). The standard callback would conflate
# them, leaving no way to turn ACP off on retry of a log that had it on.
# ---------------------------------------------------------------------------


def _build_retry_cmd() -> click.Command:
    @click.command()
    @click.option(
        "--acp-server",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=int_bool_or_str_retry_flag_callback(True),
        envvar="INSPECT_EVAL_ACP_SERVER",
    )
    def cmd(acp_server: bool | int | str | None) -> None:
        click.echo(repr(acp_server))

    return cmd


def _retry_parsed(args: list[str], env: dict[str, str] | None = None) -> object:
    runner = CliRunner()
    result = runner.invoke(_build_retry_cmd(), args, env=env, standalone_mode=False)
    assert result.exit_code == 0, result.output
    return eval(result.output.strip())


def test_retry_omitted_returns_none() -> None:
    """Flag not provided → None (so retry replays the original log value)."""
    assert _retry_parsed([]) is None


def test_retry_explicit_false_returns_false() -> None:
    """`--acp-server=false` → False (force disable, override the log)."""
    assert _retry_parsed(["--acp-server=false"]) is False


def test_retry_bare_flag_returns_true() -> None:
    """Bare `--acp-server` → True (force-enable default socket)."""
    assert _retry_parsed(["--acp-server"]) is True


def test_retry_integer_returns_int() -> None:
    """`--acp-server=9000` → int 9000 (overrides log)."""
    assert _retry_parsed(["--acp-server=9000"]) == 9000


def test_retry_env_var_false_returns_false() -> None:
    """Env var `INSPECT_EVAL_ACP_SERVER=false` → False (explicit disable)."""
    assert _retry_parsed([], env={"INSPECT_EVAL_ACP_SERVER": "false"}) is False
