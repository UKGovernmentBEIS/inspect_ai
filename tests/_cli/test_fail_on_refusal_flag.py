"""Tests for the `--fail-on-refusal/--no-fail-on-refusal` CLI option.

The option is a boolean flag pair on `inspect eval` / `inspect eval-set` with a
`None` default, bound to `INSPECT_EVAL_FAIL_ON_REFUSAL`. An omitted flag must
reach `GenerateConfigArgs` as `None` (not `False`) so it does not clobber a
value from `--generate-config` or a task / model config, while an explicit
`--no-fail-on-refusal` must reach it as `False` so the CLI can turn the option
off for a run whose task or model config enables it.
"""

import click
from click.testing import CliRunner

from inspect_ai._cli import eval as cli_eval
from inspect_ai._util.generate_config_args import config_from_locals


def _option(command: click.Command, name: str) -> click.Option:
    for param in command.params:
        if isinstance(param, click.Option) and name in param.opts:
            return param
    raise AssertionError(f"{name} not declared on {command.name}")


def test_eval_and_eval_set_declare_the_flag_pair() -> None:
    for command in (cli_eval.eval_command, cli_eval.eval_set_command):
        option = _option(command, "--fail-on-refusal")
        assert option.is_flag
        assert "--no-fail-on-refusal" in option.secondary_opts
        assert option.default is None
        assert option.envvar == "INSPECT_EVAL_FAIL_ON_REFUSAL"


def _build_cmd() -> click.Command:
    """Minimal command mirroring the real option, echoing the resolved config value."""

    @click.command()
    @click.option(
        "--fail-on-refusal/--no-fail-on-refusal",
        type=bool,
        is_flag=True,
        default=None,
        envvar="INSPECT_EVAL_FAIL_ON_REFUSAL",
    )
    def cmd(fail_on_refusal: bool | None) -> None:
        config = config_from_locals(dict(locals()))
        click.echo(repr(config.get("fail_on_refusal")))

    return cmd


def _resolved(args: list[str], env: dict[str, str] | None = None) -> object:
    runner = CliRunner()
    result = runner.invoke(_build_cmd(), args, env=env, standalone_mode=False)
    assert result.exit_code == 0, result.output
    return eval(result.output.strip())


def test_flag_sets_true() -> None:
    assert _resolved(["--fail-on-refusal"]) is True


def test_negated_flag_sets_false() -> None:
    assert _resolved(["--no-fail-on-refusal"]) is False


def test_omitted_flag_is_none_not_false() -> None:
    assert _resolved([]) is None


def test_envvar_true_sets_true() -> None:
    assert _resolved([], env={"INSPECT_EVAL_FAIL_ON_REFUSAL": "true"}) is True


def test_envvar_false_sets_false() -> None:
    assert _resolved([], env={"INSPECT_EVAL_FAIL_ON_REFUSAL": "false"}) is False


def test_config_from_locals_passes_both_values_through() -> None:
    assert config_from_locals({"fail_on_refusal": False})["fail_on_refusal"] is False
    assert config_from_locals({"fail_on_refusal": True})["fail_on_refusal"] is True
    assert config_from_locals({"fail_on_refusal": None}).get("fail_on_refusal") is None
