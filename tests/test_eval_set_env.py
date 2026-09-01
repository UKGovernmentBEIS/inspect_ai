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
from inspect_ai._cli import main
from inspect_ai._eval.eval_set_env import (
    _FALSE,
    _TRUE,
    ASSEMBLED,
    DISPLAYS,
    ENV_VARIABLES,
    GENERATE_CONFIG_VARIABLES,
    LOG_FORMATS,
    LOG_LEVELS,
    NOT_FROM_ENV,
    resolve_eval_env,
)
from inspect_ai._eval.eval_set_overrides import EvalSetOverrides
from inspect_ai._eval.evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE
from inspect_ai._eval.task import Epochs
from inspect_ai._eval.task.task import resolve_epochs
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


# --- every variable, not a representative subset -----------------------------

# One value per variable, chosen to exercise whatever conversion it has rather
# than to be typical: a flag gets a truthy word, an int-or-flag gets the word
# meaning "the default", a comma list gets two items, a case-insensitive choice
# gets the wrong case. Where an option takes a free string the value is
# arbitrary and the row still earns its place, since it pins that nothing
# mangles it. Every name in `ENV_VARIABLES` appears, aliases included — the
# alias is exactly the kind of thing that goes unread.
EVERY: dict[str, str] = {
    "INSPECT_LOG_FORMAT": "EVAL",
    "INSPECT_EVAL_LOG_FORMAT": "json",
    "INSPECT_EVAL_NO_LOG_SAMPLES": "1",
    "INSPECT_EVAL_NO_LOG_REALTIME": "1",
    "INSPECT_EVAL_LOG_MODEL_API": "1",
    "INSPECT_EVAL_LOG_REFUSALS": "1",
    "INSPECT_EVAL_LOG_BUFFER": "25",
    "INSPECT_LOG_SHARED": "true",
    "INSPECT_EVAL_LOG_SHARED": "30",
    "INSPECT_LOG_LEVEL": "warning",
    "INSPECT_LOG_LEVEL_TRANSCRIPT": "DEBUG",
    "INSPECT_EVAL_LIMIT": "10-20",
    "INSPECT_EVAL_SAMPLE_ID": "alpha,beta",
    "INSPECT_EVAL_SAMPLE_SHUFFLE": "true",
    "INSPECT_EVAL_EPOCHS": "3",
    "INSPECT_EVAL_MAX_SAMPLES": "20",
    "INSPECT_EVAL_MAX_TASKS": "4",
    "INSPECT_EVAL_MAX_SUBPROCESSES": "5",
    "INSPECT_EVAL_MAX_SANDBOXES": "6",
    "INSPECT_EVAL_MAX_DATASET_MEMORY": "0",
    "INSPECT_EVAL_MODEL_COST_CONFIG": "costs.yaml",
    "INSPECT_EVAL_SANDBOX": "docker:compose.yaml",
    "INSPECT_EVAL_NO_SANDBOX_CLEANUP": "1",
    "INSPECT_EVAL_SANDBOX_PREBUILT": "1",
    "INSPECT_EVAL_CHECKPOINT": "turn:3",
    "INSPECT_EVAL_APPROVAL": "approval.yaml",
    "INSPECT_EVAL_RETRY_ON_ERROR": "true",
    "INSPECT_EVAL_SCORE_ON_ERROR": "1",
    "INSPECT_DEBUG_ERRORS": "1",
    "INSPECT_EVAL_NO_SCORE": "1",
    "INSPECT_EVAL_SCORE_DISPLAY": "true",
    "INSPECT_EVAL_TAGS": "smoke,nightly",
    "INSPECT_EVAL_METADATA": "a=1 b=two",
    "INSPECT_EVAL_TRACE": "1",
    # the generate-config half, whose values need the command body's pass too
    "INSPECT_EVAL_MAX_RETRIES": "3",
    "INSPECT_EVAL_TIMEOUT": "60",
    "INSPECT_EVAL_ATTEMPT_TIMEOUT": "30",
    "INSPECT_EVAL_STREAM_IDLE_TIMEOUT": "15",
    "INSPECT_EVAL_MAX_CONNECTIONS": "40",
    "INSPECT_EVAL_ADAPTIVE_CONNECTIONS": "true",
    "INSPECT_EVAL_BATCH": "true",
    "INSPECT_EVAL_CACHE": "7",
    "INSPECT_EVAL_CACHE_PROMPT": "true",
}

GENERATE_CONFIG_FIELD = {
    f"INSPECT_EVAL_{field.upper()}": field for field in GENERATE_CONFIG_VARIABLES
}

# `--display` is a group option on `inspect`, not an eval option, so the CLI
# reads INSPECT_DISPLAY and calls `init_display_type` with it instead of passing
# it to `eval_set()`. There is no kwarg to compare against, and the test below
# asserts that rather than the value.
NO_KWARG = {"INSPECT_DISPLAY": "display"}

# The reducer variables adjust `epochs` rather than carrying a field of their
# own, so they have no row of their own either; `test_the_reducer_flag...`
# covers them.
ADJUSTS_ANOTHER = {"INSPECT_EVAL_EPOCHS_REDUCER", "INSPECT_EVAL_NO_EPOCHS_REDUCER"}


def test_the_matrix_covers_every_variable_that_is_read() -> None:
    """The gap that let five divergences through.

    The first version of the agreement test used a representative subset, so it
    proved the cases somebody had already thought about — and `CACHE=7`,
    `BATCH=true`, `CACHE_PROMPT=true`, `LOG_FORMAT=EVAL` and the reducer flag
    were all wrong underneath it. A subset cannot find what nobody suspected,
    so the matrix is required to name every variable this module reads.
    """
    read = {name for variable in ENV_VARIABLES.values() for name in variable.names}
    read |= set(GENERATE_CONFIG_FIELD)

    covered = set(EVERY) | set(NO_KWARG) | ADJUSTS_ANOTHER
    assert read - covered == set(), sorted(read - covered)
    assert covered - read - ADJUSTS_ANOTHER == set(), sorted(covered - read)


@pytest.mark.parametrize(
    ("variable", "value"),
    sorted(EVERY.items()),
    ids=sorted(EVERY),
)
def test_every_variable_reaches_the_value_the_cli_reaches(
    variable: str, value: str
) -> None:
    """One environment per variable, compared against `inspect eval-set` itself.

    Per-variable rather than all at once, so a failure names the variable
    instead of the set — and so a value one option rejects cannot mask what
    another option answered.
    """
    field = GENERATE_CONFIG_FIELD.get(variable)
    for candidate, entry in ENV_VARIABLES.items():
        if variable in entry.names:
            field = candidate
            break
    assert field is not None, variable

    from_cli = _cli_kwargs({variable: value})
    resolved = resolve_eval_env({variable: value})
    assert resolved is not None, variable

    if variable in GENERATE_CONFIG_FIELD:
        config = resolved.generate_config
        assert config is not None, variable
        assert getattr(config, field) == from_cli[field], variable
    else:
        ours, theirs = getattr(resolved, field), from_cli[field]
        if field == "epochs":
            ours, theirs = _epochs_shape(ours), _epochs_shape(theirs)
        assert ours == theirs, variable


def _epochs_shape(value: int | Epochs | None) -> Any:
    """An epoch count in a form the two spellings of it can be compared in.

    The CLI always builds an `Epochs`, where the overrides document spells a
    plain count as an integer — the shape `eval_set(epochs=4)` itself takes,
    and what `_overridden_epochs` turns back into an `Epochs` on the way in. So
    the two differ in spelling and agree in meaning, which `resolve_epochs` is
    the function that says.
    """
    resolved = resolve_epochs(value)
    if resolved is None:
        return None
    return (resolved.epochs, [str(reducer) for reducer in resolved.reducer or []])


def test_the_display_variable_is_read_but_not_as_an_eval_set_argument() -> None:
    """`--display` is a group option, so the CLI never passes it to `eval_set()`.

    It initialises the display for the whole process instead. `eval_set()` does
    the same thing from its own `display` argument, but only where nothing has
    initialised one yet — which in a driven worker is the case, so honouring the
    variable through the overrides document reaches the same place by the other
    route. The agreement test cannot express that, so it is asserted here.
    """
    assert "display" not in _cli_kwargs({"INSPECT_DISPLAY": "plain"})
    resolved = resolve_eval_env({"INSPECT_DISPLAY": "PLAIN"})
    assert resolved is not None and resolved.display == "plain"


def test_a_generate_config_variable_the_cli_rejects_is_a_configuration_error() -> None:
    """Not an unhandled pydantic error, which a runner cannot present as one.

    `resolve_eval_env` is called by a runner at launch and again on every
    scheduled turn; a `ValidationError` escaping it crashes the turn where a
    `PrerequisiteError` degrades it.
    """
    with pytest.raises((PrerequisiteError, click.ClickException)):
        resolve_eval_env({"INSPECT_EVAL_CACHE_PROMPT": "TRUE"})


def test_the_reducer_flag_is_read_as_a_flag() -> None:
    # bound to `--no-epochs-reducer`, so its value decides rather than its
    # presence: exported false, it must leave the reducers alone
    off = resolve_eval_env(
        {"INSPECT_EVAL_EPOCHS": "3", "INSPECT_EVAL_NO_EPOCHS_REDUCER": "false"}
    )
    assert off is not None and off.epochs == 3

    on = resolve_eval_env(
        {"INSPECT_EVAL_EPOCHS": "3", "INSPECT_EVAL_NO_EPOCHS_REDUCER": "true"}
    )
    assert on is not None and not isinstance(on.epochs, int)
    assert on.epochs is not None and on.epochs.reducer == []


# --- the choice lists are the CLI's ------------------------------------------

CHOICES: list[tuple[str, tuple[str, ...]]] = [
    ("INSPECT_LOG_FORMAT", LOG_FORMATS),
    ("INSPECT_LOG_LEVEL", LOG_LEVELS),
    ("INSPECT_LOG_LEVEL_TRANSCRIPT", LOG_LEVELS),
    ("INSPECT_DISPLAY", DISPLAYS),
    ("INSPECT_EVAL_CACHE_PROMPT", ("auto", "true", "false")),
]


@pytest.mark.parametrize(
    ("variable", "choices"), CHOICES, ids=[variable for variable, _ in CHOICES]
)
def test_a_choice_list_is_the_one_the_option_declares(
    variable: str, choices: tuple[str, ...]
) -> None:
    """Reproduced rather than imported, so pin the two together.

    A choice added upstream and missing here would be refused from the
    environment while `inspect eval` accepted it — the first failure mode this
    module exists to prevent, arriving through the fix for the third.
    """
    declared: tuple[str, ...] | None = None
    for command in (cli_eval.eval_set_command, main.inspect):
        for parameter in command.params:
            envvar = getattr(parameter, "envvar", None)
            names = (
                [envvar]
                if isinstance(envvar, str)
                else [str(name) for name in envvar or ()]
            )
            if variable in names and isinstance(parameter.type, click.Choice):
                declared = tuple(str(choice) for choice in parameter.type.choices)
        if declared is not None:
            break

    assert declared is not None, variable
    assert set(declared) == set(choices), variable


def test_a_choice_the_cli_refuses_is_refused_here() -> None:
    # accepted, `log_level` would reach `eval_set()` as a level nothing knows;
    # `log_format` and `display` would escape as a pydantic error instead,
    # because the model types those two as `Literal`
    for variable in ("INSPECT_LOG_LEVEL", "INSPECT_LOG_FORMAT", "INSPECT_DISPLAY"):
        with pytest.raises(PrerequisiteError, match=variable):
            resolve_eval_env({variable: "chatty"})


# --- the option's constraints, not only its conversion -----------------------

CONSTRAINED: list[tuple[str, str]] = [
    # `--max-dataset-memory` is an `IntRange(min=0)`
    ("INSPECT_EVAL_MAX_DATASET_MEMORY", "-1"),
    # and the concurrency ceilings are refused below one
    ("INSPECT_EVAL_MAX_SAMPLES", "0"),
    ("INSPECT_EVAL_MAX_TASKS", "-2"),
    ("INSPECT_EVAL_LOG_BUFFER", "0"),
]


@pytest.mark.parametrize(
    ("variable", "value"), CONSTRAINED, ids=[name for name, _ in CONSTRAINED]
)
def test_a_value_the_option_constrains_is_refused_with_the_variable_named(
    variable: str, value: str
) -> None:
    """A converter answers *what does this text mean*, not *is it allowed*.

    Left to the reader of the persisted document, an out-of-range value is a
    manifest already committed and a fleet that fails one worker at a time
    hours later. And the message has to name the variable: `max_dataset_memory`
    names nothing the operator typed.
    """
    assert _cli_kwargs.__name__  # the CLI's own refusal is asserted below
    with pytest.raises(PrerequisiteError, match=variable):
        resolve_eval_env({variable: value})


@pytest.mark.parametrize(
    ("variable", "value"), CONSTRAINED, ids=[name for name, _ in CONSTRAINED]
)
def test_the_cli_refuses_the_same_values(variable: str, value: str) -> None:
    # the parity claim for the refusals, since the agreement test above can only
    # compare values that both sides accept
    result = CliRunner().invoke(
        cli_eval.eval_set_command, ["nonexistent.py"], env={variable: value}
    )
    assert result.exit_code != 0, variable


def test_a_choice_is_matched_as_click_matches_it() -> None:
    # `click.Choice` does not strip, so neither does this -- accepted here it
    # would be a value `inspect eval` refuses at the door
    with pytest.raises(PrerequisiteError, match="INSPECT_LOG_FORMAT"):
        resolve_eval_env({"INSPECT_LOG_FORMAT": " eval"})

    result = CliRunner().invoke(
        cli_eval.eval_set_command,
        ["nonexistent.py"],
        env={"INSPECT_LOG_FORMAT": " eval"},
    )
    assert result.exit_code != 0


# --- what cannot be said, said out loud --------------------------------------

CANNOT_DISABLE: list[tuple[str, str]] = [
    ("INSPECT_EVAL_SAMPLE_SHUFFLE", "sample_shuffle"),
    ("INSPECT_EVAL_RETRY_ON_ERROR", "retry_on_error"),
    ("INSPECT_EVAL_BATCH", "batch"),
    ("INSPECT_EVAL_CACHE", "cache"),
]


@pytest.mark.parametrize(
    ("variable", "field"), CANNOT_DISABLE, ids=[name for name, _ in CANNOT_DISABLE]
)
def test_an_explicit_false_reaches_the_same_nothing_the_cli_reaches(
    variable: str, field: str
) -> None:
    """Four settings that cannot be turned off from the environment, in either reader.

    Each option's callback maps `false` to a value the command body then drops
    as falsy, so `inspect eval-set` passes nothing for it — and so does this. A
    runner wanting *off* rather than *no opinion* has to say so in its own
    vocabulary; reading it differently here would diverge from the command this
    module exists to stand in for.

    Pinned as a test because it is the kind of parity that reads like a bug and
    would otherwise be "fixed" into a divergence.
    """
    assert resolve_eval_env({variable: "false"}) is None

    from_cli = _cli_kwargs({variable: "false"})
    reached = (
        from_cli.get("kwargs", {}).get(field)
        if field in ("batch", "cache")
        else from_cli.get(field)
    )
    assert reached is None, variable
