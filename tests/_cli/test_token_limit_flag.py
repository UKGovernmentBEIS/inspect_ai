"""Tests for the `--token-limit` CLI option parsing.

The flag uses :func:`token_limit_flag_callback` so the parsed value is an
``int | TokenLimit | None`` union that maps cleanly into the ``token_limit``
parameter on ``eval()`` / ``eval_set()``: plain ints (and ``k``/``m``/``b``
suffixed forms) meter all tokens, while the ``output:`` prefix yields a
``TokenLimit`` metering only output tokens.
"""

import click
from click.testing import CliRunner

from inspect_ai._cli.util import token_limit_flag_callback
from inspect_ai.util._limit import TokenLimit


def _build_cmd() -> click.Command:
    """Minimal click command that mirrors the real --token-limit option."""

    @click.command()
    @click.option(
        "--token-limit",
        type=str,
        callback=token_limit_flag_callback,
        envvar="INSPECT_EVAL_TOKEN_LIMIT",
    )
    def cmd(token_limit: int | TokenLimit | None) -> None:
        # echo the parsed value back through stdout so the test can read it
        click.echo(repr(token_limit))

    return cmd


def _parsed(args: list[str], env: dict[str, str] | None = None) -> object:
    """Run the test command and eval its echoed repr back to a Python value."""
    runner = CliRunner()
    result = runner.invoke(_build_cmd(), args, env=env, standalone_mode=False)
    assert result.exit_code == 0, result.output
    return eval(result.output.strip())


def test_omitted_returns_none() -> None:
    assert _parsed([]) is None


def test_plain_int() -> None:
    assert _parsed(["--token-limit", "500000"]) == 500000


def test_magnitude_suffix() -> None:
    assert _parsed(["--token-limit", "1m"]) == 1_000_000


def test_output_prefix() -> None:
    assert _parsed(["--token-limit", "output:1m"]) == TokenLimit(
        tokens=1_000_000, type="output"
    )


def test_all_prefix_collapses_to_int() -> None:
    assert _parsed(["--token-limit", "all:500k"]) == 500_000


def test_formula() -> None:
    assert _parsed(["--token-limit", "(input*0.1)+output:1m"]) == TokenLimit(
        tokens=1_000_000, type="(input*0.1)+output"
    )


def test_invalid_formula_raises_bad_parameter() -> None:
    runner = CliRunner()
    result = runner.invoke(
        _build_cmd(), ["--token-limit", "input +:1m"], standalone_mode=False
    )
    assert isinstance(result.exception, click.BadParameter)


def test_envvar() -> None:
    assert _parsed([], env={"INSPECT_EVAL_TOKEN_LIMIT": "output:2k"}) == TokenLimit(
        tokens=2_000, type="output"
    )


def test_invalid_value_raises_bad_parameter() -> None:
    runner = CliRunner()
    result = runner.invoke(
        _build_cmd(), ["--token-limit", "xyz"], standalone_mode=False
    )
    assert isinstance(result.exception, click.BadParameter)
    assert "token limit" in str(result.exception)


def test_invalid_type_prefix_raises_bad_parameter() -> None:
    runner = CliRunner()
    result = runner.invoke(
        _build_cmd(), ["--token-limit", "reasoning:1m"], standalone_mode=False
    )
    assert isinstance(result.exception, click.BadParameter)
