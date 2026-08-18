"""Tests for the `--ctl-server` CLI option parsing.

The flag uses :func:`ctl_server_flag_callback` so the parsed value is a
``bool | str | None`` union that maps cleanly into the ``ctl_server``
parameter on ``eval()`` / ``eval_set()`` / ``eval_retry()``: ``None``
(omitted) and ``True`` mean default-on, ``False`` disables the control
endpoint, ``"keep"`` additionally parks the process after the eval.
"""

import click
import pytest
from click.testing import CliRunner

from inspect_ai._cli.util import ctl_server_flag_callback


def _build_cmd() -> click.Command:
    """Minimal click command that mirrors the real --ctl-server option."""

    @click.command()
    @click.option(
        "--ctl-server",
        is_flag=False,
        flag_value="true",
        default=None,
        callback=ctl_server_flag_callback,
        envvar="INSPECT_EVAL_CTL_SERVER",
    )
    def cmd(ctl_server: bool | str | None) -> None:
        # echo the parsed value back through stdout so the test can read it
        click.echo(repr(ctl_server))

    return cmd


def _parsed(args: list[str], env: dict[str, str] | None = None) -> object:
    """Run the test command and eval its echoed repr back to a Python value."""
    runner = CliRunner()
    result = runner.invoke(_build_cmd(), args, env=env, standalone_mode=False)
    assert result.exit_code == 0, result.output
    return eval(result.output.strip())


def test_omitted_returns_none() -> None:
    """Flag not provided → None (default: control server on, no park)."""
    assert _parsed([]) is None


def test_bare_flag_enables() -> None:
    """`--ctl-server` with no value → True (explicit form of the default)."""
    assert _parsed(["--ctl-server"]) is True


def test_explicit_true_enables() -> None:
    """`--ctl-server=true` → True."""
    assert _parsed(["--ctl-server=true"]) is True


def test_explicit_false_disables() -> None:
    """`--ctl-server=false` → False (no control endpoint)."""
    assert _parsed(["--ctl-server=false"]) is False


def test_keep_value() -> None:
    """`--ctl-server=keep` → "keep" (on + park after the eval)."""
    assert _parsed(["--ctl-server=keep"]) == "keep"


def test_keep_alive_legacy_alias() -> None:
    """`--ctl-server=keep-alive` still resolves, normalizing to "keep"."""
    assert _parsed(["--ctl-server=keep-alive"]) == "keep"


def test_unknown_value_rejected() -> None:
    """Any other string is a usage error, not silently treated as `true`."""
    runner = CliRunner()
    result = runner.invoke(
        _build_cmd(), ["--ctl-server=keepalive"], standalone_mode=False
    )
    assert isinstance(result.exception, click.BadParameter)
    assert "keep" in result.exception.message


def test_env_var_keep() -> None:
    """`INSPECT_EVAL_CTL_SERVER=keep` env var → "keep"."""
    assert _parsed([], env={"INSPECT_EVAL_CTL_SERVER": "keep"}) == "keep"


def test_env_var_false() -> None:
    """`INSPECT_EVAL_CTL_SERVER=false` env var → False (CI-wide suppression)."""
    assert _parsed([], env={"INSPECT_EVAL_CTL_SERVER": "false"}) is False


@pytest.mark.parametrize("value", ["yes", "1"])
def test_truthy_aliases(value: str) -> None:
    """Conventional truthy spellings map to True (mirrors --acp-server)."""
    assert _parsed([f"--ctl-server={value}"]) is True


def test_cli_and_python_api_accept_the_same_values() -> None:
    """The callback delegates to resolve_ctl_server — one grammar, two surfaces.

    Every value the CLI accepts must resolve on the Python API path too (a
    user forwarding a CLI/env spelling to `eval(ctl_server=...)` must not get
    a rejection whose message claims the value is expected), and every value
    the CLI rejects must also be rejected by the resolver.
    """
    from typing import cast

    from inspect_ai._control.server import resolve_ctl_server

    for value in ("true", "yes", "1", "false", "no", "0", "keep-alive", "keep"):
        parsed = cast("bool | str | None", _parsed([f"--ctl-server={value}"]))
        # the CLI's parsed value round-trips through the resolver...
        enabled, keep_alive = resolve_ctl_server(parsed)
        # ...and matches resolving the raw spelling directly
        assert (enabled, keep_alive) == resolve_ctl_server(value)
