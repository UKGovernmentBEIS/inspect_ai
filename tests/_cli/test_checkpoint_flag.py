"""Tests for the `--checkpoint` CLI option wiring.

The flag uses Click's optional-value form (``is_flag=False`` +
``flag_value="default"``): a bare ``--checkpoint`` yields the sentinel
``"default"`` (enable checkpointing, defer the trigger), while
``--checkpoint=<shorthand>`` passes the value through verbatim. The
sentinel is resolved to the concrete default trigger
(``TokenInterval(every=500_000)``) at merge time, once a sample is in
hand. These tests cover the bare-flag → default → 500k seam that the
parse/merge unit tests exercise only as separate halves.
"""

import click
import pytest
from click.testing import CliRunner

from inspect_ai._cli.eval import eval_command, eval_retry_command
from inspect_ai.util._checkpoint import TokenInterval
from inspect_ai.util._checkpoint.config import merge_checkpoint_configs
from inspect_ai.util._checkpoint.parse_cli import parse_checkpoint


def _build_cmd() -> click.Command:
    """Minimal click command mirroring the real --checkpoint option."""

    @click.command()
    @click.option(
        "--checkpoint",
        is_flag=False,
        flag_value="default",
        default=None,
        envvar="INSPECT_EVAL_CHECKPOINT",
    )
    def cmd(checkpoint: str | None) -> None:
        click.echo(repr(checkpoint))

    return cmd


def _parsed(args: list[str], env: dict[str, str] | None = None) -> object:
    runner = CliRunner()
    result = runner.invoke(_build_cmd(), args, env=env, standalone_mode=False)
    assert result.exit_code == 0, result.output
    return eval(result.output.strip())


@pytest.mark.parametrize("command", [eval_command, eval_retry_command])
def test_real_option_uses_default_sentinel(command: click.Command) -> None:
    """Guard against drift: the real CLI option maps the bare flag to "default".

    The rebuilt command below mirrors this; this test ties the mirror to
    the actual `inspect eval` / `inspect eval retry` options.
    """
    param = next(p for p in command.params if p.name == "checkpoint")
    assert isinstance(param, click.Option)
    assert param.is_flag is False
    assert param.flag_value == "default"


def test_bare_flag_maps_to_default_sentinel() -> None:
    """`--checkpoint` with no value → the "default" sentinel string."""
    assert _parsed(["--checkpoint"]) == "default"


def test_explicit_shorthand_passes_through() -> None:
    assert _parsed(["--checkpoint=turn:5"]) == "turn:5"


def test_omitted_returns_none() -> None:
    assert _parsed([]) is None


def test_env_var_passes_through() -> None:
    assert _parsed([], env={"INSPECT_EVAL_CHECKPOINT": "token:500k"}) == "token:500k"


def test_bare_flag_resolves_to_500k_tokens() -> None:
    """End-to-end: bare `--checkpoint` enables and defaults to 500k tokens.

    The bare flag must NOT pin a trigger at the eval layer (so a sample
    can still supply one); the 500k default is filled in by the merge.
    """
    cfg = parse_checkpoint("default")
    assert cfg is not None and cfg.trigger is None  # enable, no trigger pinned
    out = merge_checkpoint_configs(eval_=cfg)
    assert out is not None
    assert out.trigger == TokenInterval(every=500_000)
