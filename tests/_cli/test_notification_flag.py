"""Tests for the `--notification` CLI option parsing.

The option intentionally opts out of Click's `auto_envvar_prefix`
lookup (the root CLI sets `auto_envvar_prefix="INSPECT"`). Without
that opt-out, exporting `INSPECT_EVAL_NOTIFICATION` — the same env
var `build_apprise(True)` reads as the URL/config payload — would
also populate the option value, causing notifications to silently
enable (config-file path) or plain `inspect eval` to crash (URL
string that `build_apprise` then rejects as a non-file path).

These tests exercise the option through `CliRunner` with the same
`auto_envvar_prefix` the production CLI uses, so a regression that
re-introduces autoenv binding here would fail.
"""

import click
from click.testing import CliRunner

from inspect_ai._cli.eval import _notification_callback


def _build_group() -> click.Group:
    """`inspect eval`-shaped click group mirroring the real --notification option.

    Click derives the autoenv variable name from the full command
    path (`<PREFIX>_<CMD_PATH>_<OPT>`). The collision the production
    CLI hits is `INSPECT_EVAL_NOTIFICATION` — so the test command
    MUST be a subcommand named `eval` under a group invoked with
    `auto_envvar_prefix="INSPECT"`. A bare standalone command would
    auto-derive `INSPECT_NOTIFICATION` instead and miss the bug.
    """

    @click.command("eval")
    @click.option(
        "--notification",
        "notification",
        is_flag=False,
        flag_value="__bare__",
        default=None,
        callback=_notification_callback,
        allow_from_autoenv=False,
    )
    def eval_cmd(notification: bool | str | None) -> None:
        click.echo(repr(notification))

    @click.group()
    def root() -> None:
        pass

    root.add_command(eval_cmd)
    return root


def _parsed(args: list[str], env: dict[str, str] | None = None) -> object:
    """Invoke `eval <args>` under the real CLI's autoenv prefix."""
    runner = CliRunner()
    result = runner.invoke(
        _build_group(),
        ["eval", *args],
        env=env,
        auto_envvar_prefix="INSPECT",
        standalone_mode=False,
    )
    assert result.exit_code == 0, result.output
    return eval(result.output.strip())


def test_omitted_returns_none() -> None:
    """Flag not provided → None (notifications disabled)."""
    assert _parsed([]) is None


def test_bare_flag_returns_true() -> None:
    """`--notification` with no value → True (read from env var at runtime)."""
    assert _parsed(["--notification"]) is True


def test_explicit_true_returns_true() -> None:
    """`--notification=true` → True."""
    assert _parsed(["--notification=true"]) is True


def test_explicit_false_returns_none() -> None:
    """`--notification=false` → None (explicit disable)."""
    assert _parsed(["--notification=false"]) is None


def test_path_value_returns_string() -> None:
    """`--notification=/path/to/cfg.yml` → string for `build_apprise` to validate."""
    assert _parsed(["--notification=/tmp/cfg.yml"]) == "/tmp/cfg.yml"


def test_env_var_alone_does_not_set_notification() -> None:
    """Env var alone (no flag) must NOT populate the option via autoenv.

    Pinned regression: without `allow_from_autoenv=False`, Click's
    root-level `auto_envvar_prefix="INSPECT"` would auto-bind
    `INSPECT_EVAL_NOTIFICATION` to this option. That collides with
    the env var `build_apprise(True)` reads — exporting the URL
    would silently enable notifications, and an Apprise URL string
    would crash `build_apprise` as a non-file path.
    """
    assert _parsed([], env={"INSPECT_EVAL_NOTIFICATION": "slack://hook"}) is None
    assert _parsed([], env={"INSPECT_EVAL_NOTIFICATION": "/tmp/cfg.yml"}) is None


def test_env_var_with_bare_flag_still_returns_true() -> None:
    """With the bare flag, the env var is left for `build_apprise(True)` to read.

    The CLI shouldn't itself consume `INSPECT_EVAL_NOTIFICATION` —
    it just translates `--notification` to `True` and lets the
    runtime read the env var at apprise-build time.
    """
    assert (
        _parsed(["--notification"], env={"INSPECT_EVAL_NOTIFICATION": "slack://hook"})
        is True
    )
