"""`resolve_eval_env` reads what `inspect eval` reads, and reads it the same way.

Two claims. The cheap one is that every override field is accounted for. The
one that earns the module's existence is that the table is not a *second*
reading of inspect's environment but a mirror of the CLI's — so the centrepiece
here invokes `inspect eval-set` itself under an environment and asserts the
resolver reaches the same values. A table maintained by eye would drift on the
next option added upstream; this fails instead.
"""

import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

import inspect_ai._cli.eval as cli_eval
from inspect_ai._eval.eval_set_env import (
    _FALSE,
    _TRUE,
    ASSEMBLED,
    ENV_VARIABLES,
    GENERATE_CONFIG_VARIABLES,
    NOT_FROM_ENV,
    resolve_eval_env,
)
from inspect_ai._eval.eval_set_overrides import EvalSetOverrides
from inspect_ai._eval.evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE
from inspect_ai._util.error import PrerequisiteError

TASK = "tests/test_eval_config.py@eval_config_task"


# --- the surface is accounted for -------------------------------------------


def test_every_override_field_is_decided_about() -> None:
    """A field in neither table is one nobody decided about.

    `NOT_FROM_ENV` exists so that *not* reading a variable is a recorded
    decision rather than an omission — without it this test could only ever
    check the fields somebody remembered.
    """
    assert set(ENV_VARIABLES).isdisjoint(NOT_FROM_ENV)
    assert set(ENV_VARIABLES).isdisjoint(ASSEMBLED)
    assert set(ENV_VARIABLES) | set(NOT_FROM_ENV) | ASSEMBLED == set(
        EvalSetOverrides.model_fields
    )


def test_the_generate_config_variables_are_the_identity_neutral_set() -> None:
    # the same partition that decides what `generate_config` may carry at all,
    # so a field leaving the exclusion set cannot keep a variable here
    assert set(GENERATE_CONFIG_VARIABLES) == GENERATE_CONFIG_FIELDS_TO_EXCLUDE


# --- the names are the CLI's ------------------------------------------------


def _declared(command: click.Command | None = None) -> set[str]:
    """Every `INSPECT_*` variable an eval command binds to an option.

    `eval-set` by default, because that is the command a driven run *is* —
    `eval-retry` spells three of these without the `NO_` infix, and honouring
    those would mean reading a variable `inspect eval-set` ignores.
    """
    names: set[str] = set()
    for parameter in (command or cli_eval.eval_set_command).params:
        envvar = getattr(parameter, "envvar", None)
        if isinstance(envvar, str):
            names.add(envvar)
        elif isinstance(envvar, (list, tuple)):
            names.update(str(name) for name in envvar)
    return names


def test_the_eval_retry_spellings_are_not_read() -> None:
    """The three variables that named the same settings under a different command.

    Discovered by the agreement test rather than by reading: `eval-retry` binds
    `INSPECT_EVAL_SCORE` to its `--no-score`, so reading it here would have made
    a Steward run honour a variable `inspect eval-set` does not.
    """
    retry_only = _declared(cli_eval.eval_retry_command) - _declared()
    read_here = {name for variable in ENV_VARIABLES.values() for name in variable.names}

    assert "INSPECT_EVAL_SCORE" in retry_only
    assert not (read_here & retry_only), sorted(read_here & retry_only)


def test_every_variable_named_here_is_one_the_cli_declares() -> None:
    """No invented names, and no typos.

    Upstream has at least one live typo in this surface
    (`INSPECT_EVAL_RETRY_ATTEMPS`), which is the standing proof that these
    names cannot be derived from the field names by rule.
    """
    declared = _declared()
    named = {name for variable in ENV_VARIABLES.values() for name in variable.names} | {
        f"INSPECT_EVAL_{field.upper()}" for field in GENERATE_CONFIG_VARIABLES
    }

    assert named <= declared, sorted(named - declared)


def test_no_variable_the_cli_declares_for_a_field_is_missed() -> None:
    """The direction that actually rots.

    `INSPECT_EVAL_SCORE` and `INSPECT_EVAL_LOG_SAMPLES` are both bound to
    `--no-*` flags, so a table written from the field names alone silently
    drops them — and a dropped variable is one an operator sets and Steward
    ignores.
    """
    declared = _declared()
    missed: dict[str, set[str]] = {}
    for field, variable in ENV_VARIABLES.items():
        upper = field.upper()
        candidates = {
            f"INSPECT_EVAL_{upper}",
            f"INSPECT_{upper}",
            f"INSPECT_EVAL_NO_{upper}",
        } & declared
        if absent := candidates - set(variable.names):
            missed[field] = absent

    assert not missed, missed


def test_a_field_we_decided_not_to_read_is_not_read() -> None:
    for field in NOT_FROM_ENV:
        assert field not in ENV_VARIABLES
        # and its reason says something, since the reason is the whole record
        assert len(NOT_FROM_ENV[field]) > 40


def test_the_notification_variable_is_never_read_as_a_value() -> None:
    """The one whose failure would be a leaked secret rather than a wrong run.

    `--notification` disables click's auto-env binding on purpose:
    INSPECT_EVAL_NOTIFICATION holds the Apprise URL that `notification=True`
    reads, so a runner reading it as the option's value both means the wrong
    thing and copies a credential into whatever it persists.
    """
    assert "notification" in NOT_FROM_ENV
    assert resolve_eval_env({"INSPECT_EVAL_NOTIFICATION": "slack://T/B/xoxb"}) is None


# --- the conversions are the CLI's ------------------------------------------


@pytest.mark.parametrize("text", sorted(_TRUE | _FALSE))
def test_the_boolean_vocabulary_is_clicks(text: str) -> None:
    """`_flag` reproduces `click.BOOL` rather than importing it, so pin the two together."""

    @click.command()
    @click.option("--flag", type=bool, is_flag=True, envvar="PROBE")
    def probe(flag: bool) -> None:
        click.echo(str(flag))

    result = CliRunner().invoke(probe, [], env={"PROBE": text})
    expected = result.output.strip() == "True"

    from inspect_ai._eval.eval_set_env import _flag

    assert _flag(text, "PROBE") is expected


def test_a_value_click_would_refuse_is_refused_here() -> None:
    from inspect_ai._eval.eval_set_env import _flag

    with pytest.raises(PrerequisiteError, match="INSPECT_EVAL_TRACE"):
        _flag("perhaps", "INSPECT_EVAL_TRACE")


# --- the resolver agrees with the CLI ---------------------------------------


def _cli_kwargs(env: dict[str, str]) -> dict[str, Any]:
    """What `inspect eval-set` would pass to `eval_set()` under this environment."""
    captured: dict[str, Any] = {}

    def record(*args: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    with patch.object(cli_eval, "eval_set", record):
        result = CliRunner().invoke(
            cli_eval.eval_set_command,
            [TASK, "--model", "mockllm/model"],
            env={**env, "INSPECT_LOG_DIR": "/tmp/eval-set-env-test"},
        )
    assert captured, result.output or result.exception
    return captured


# each row is one environment, and the fields it is expected to decide. The
# expectation is asserted against the CLI *and* against the resolver, so a row
# cannot encode a wrong belief about either
AGREEMENT: list[tuple[str, dict[str, str], list[str]]] = [
    ("a range the CLI spells with a dash", {"INSPECT_EVAL_LIMIT": "10-20"}, ["limit"]),
    ("a plain count", {"INSPECT_EVAL_LIMIT": "5"}, ["limit"]),
    (
        "comma-separated ids",
        {"INSPECT_EVAL_SAMPLE_ID": "alpha,beta"},
        ["sample_id"],
    ),
    ("comma-separated tags", {"INSPECT_EVAL_TAGS": "smoke,nightly"}, ["tags"]),
    (
        "a flag whose name says the opposite of its meaning",
        {"INSPECT_EVAL_SCORE_DISPLAY": "true"},
        ["score_display"],
    ),
    ("the negated score flag", {"INSPECT_EVAL_NO_SCORE": "1"}, ["score"]),
    (
        "the negated log-samples flag",
        {"INSPECT_EVAL_NO_LOG_SAMPLES": "1"},
        ["log_samples"],
    ),
    ("a bare int", {"INSPECT_EVAL_MAX_SAMPLES": "20"}, ["max_samples"]),
    (
        "a flag that is also an int, given as a flag",
        {"INSPECT_EVAL_LOG_SHARED": "true"},
        ["log_shared"],
    ),
    (
        "a flag that is also an int, given as an int",
        {"INSPECT_EVAL_RETRY_ON_ERROR": "3"},
        ["retry_on_error"],
    ),
    (
        "shuffle, whose flag value is a sentinel",
        {"INSPECT_EVAL_SAMPLE_SHUFFLE": "true"},
        ["sample_shuffle"],
    ),
    (
        "shuffle with a seed",
        {"INSPECT_EVAL_SAMPLE_SHUFFLE": "42"},
        ["sample_shuffle"],
    ),
    (
        "metadata, which is YAML per entry",
        {"INSPECT_EVAL_METADATA": "a=1 b=two"},
        ["metadata"],
    ),
    ("a sandbox type", {"INSPECT_EVAL_SANDBOX": "docker"}, ["sandbox"]),
    (
        "a sandbox type with a config",
        {"INSPECT_EVAL_SANDBOX": "docker:compose.yaml"},
        ["sandbox"],
    ),
]


@pytest.mark.parametrize(
    ("env", "fields"),
    [(env, fields) for _, env, fields in AGREEMENT],
    ids=[case for case, _, _ in AGREEMENT],
)
def test_the_resolver_and_the_cli_reach_the_same_value(
    env: dict[str, str], fields: list[str]
) -> None:
    """The claim the whole module rests on.

    Not "the resolver produces something sensible" but "the resolver produces
    what `inspect eval-set` produces", which is the only definition of correct
    available — the names and their conversions belong to the CLI.
    """
    from_cli = _cli_kwargs(env)
    resolved = resolve_eval_env(env)

    assert resolved is not None
    for field in fields:
        assert getattr(resolved, field) == from_cli[field], field


def test_epochs_carry_their_reducers() -> None:
    """`epochs` is three variables assembled into one value, so it sits outside the table."""
    resolved = resolve_eval_env(
        {"INSPECT_EVAL_EPOCHS": "4", "INSPECT_EVAL_EPOCHS_REDUCER": "mean,max"}
    )
    assert resolved is not None
    assert resolved.epochs is not None and not isinstance(resolved.epochs, int)
    assert (resolved.epochs.epochs, resolved.epochs.reducer) == (4, ["mean", "max"])

    from_cli = _cli_kwargs(
        {"INSPECT_EVAL_EPOCHS": "4", "INSPECT_EVAL_EPOCHS_REDUCER": "mean,max"}
    )
    assert from_cli["epochs"].epochs == 4

    bare = resolve_eval_env({"INSPECT_EVAL_EPOCHS": "4"})
    assert bare is not None and bare.epochs == 4


# --- the resolver's own rules -----------------------------------------------


def test_silence_is_no_document_at_all() -> None:
    assert resolve_eval_env({}) is None
    assert resolve_eval_env({"PATH": "/usr/bin"}) is None


def test_a_variable_exported_empty_says_nothing() -> None:
    # how a shell profile sets a variable it has no value for, and how click
    # reads one for every option that takes a value
    assert resolve_eval_env({"INSPECT_EVAL_MAX_SAMPLES": "  "}) is None


def test_the_first_variable_set_is_the_one_read() -> None:
    # click consults an option's `envvar` list in order, and the table records
    # that order rather than choosing one
    assert ENV_VARIABLES["log_shared"].names[0] == "INSPECT_LOG_SHARED"
    resolved = resolve_eval_env(
        {"INSPECT_LOG_SHARED": "30", "INSPECT_EVAL_LOG_SHARED": "10"}
    )
    assert resolved is not None and resolved.log_shared == 30


REFUSED: list[tuple[str, dict[str, str], str]] = [
    ("a count that is not one", {"INSPECT_EVAL_MAX_SAMPLES": "lots"}, "MAX_SAMPLES"),
    ("a range that is not one", {"INSPECT_EVAL_LIMIT": "ten"}, "LIMIT"),
    ("a boolean that is not one", {"INSPECT_EVAL_TRACE": "perhaps"}, "TRACE"),
]


@pytest.mark.parametrize(
    ("env", "names"),
    [(env, names) for _, env, names in REFUSED],
    ids=[case for case, _, _ in REFUSED],
)
def test_a_value_that_cannot_mean_anything_names_its_variable(
    env: dict[str, str], names: str
) -> None:
    with pytest.raises(PrerequisiteError, match=names):
        resolve_eval_env(env)


# --- generate config ---------------------------------------------------------


def test_the_identity_neutral_generate_config_variables_are_collected() -> None:
    resolved = resolve_eval_env(
        {"INSPECT_EVAL_MAX_CONNECTIONS": "40", "INSPECT_EVAL_MAX_RETRIES": "2"}
    )
    assert resolved is not None and resolved.generate_config is not None
    assert resolved.generate_config.max_connections == 40
    assert resolved.generate_config.max_retries == 2


def test_a_generate_config_file_cannot_smuggle_in_an_identity_bearing_field(
    tmp_path: Path,
) -> None:
    """The rule the whole override surface rests on, at the one door that takes a file.

    A file is the only place a caller can name a generate-config field without
    naming a variable for it, so it is the only place the exclusion set has to
    be re-checked.
    """
    config = tmp_path / "generate.yaml"
    config.write_text("temperature: 0.5\n")

    with pytest.raises(PrerequisiteError, match=re.escape("temperature")):
        resolve_eval_env({"INSPECT_EVAL_GENERATE_CONFIG": config.as_posix()})


def test_a_generate_config_variable_beats_the_file(tmp_path: Path) -> None:
    config = tmp_path / "generate.yaml"
    config.write_text("max_connections: 10\n")

    resolved = resolve_eval_env(
        {
            "INSPECT_EVAL_GENERATE_CONFIG": config.as_posix(),
            "INSPECT_EVAL_MAX_CONNECTIONS": "40",
        }
    )
    assert resolved is not None and resolved.generate_config is not None
    assert resolved.generate_config.max_connections == 40
