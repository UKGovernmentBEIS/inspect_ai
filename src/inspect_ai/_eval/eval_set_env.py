"""Reading inspect's own environment variables into an overrides document.

An external runner drives `eval_set()` in capture and selection mode
(`eval_set_overrides.py` states the arrangement). Such a runner usually wants
the environment its operator already knows to keep working: `inspect eval`
documents `INSPECT_EVAL_MAX_SAMPLES` and the rest, and an operator who exports
one reasonably expects a driven run to honour it.

**Doing that outside inspect does not work, and the failure is silent.** The
variables are not values of the shape `eval_set()` takes — they are *click
inputs*, resolved through an option's `type`, its `callback`, and a
normalisation block in the command body that runs afterwards. A runner that
reads `os.environ` and validates against `EvalSetOverrides` gets a different
answer from `inspect eval` for at least seven of them, in three different ways:

- **Refused where inspect accepts.** `INSPECT_EVAL_LIMIT=10-20` is a range to
  `parse_samples_limit` and a malformed integer to anything else.
- **Accepted with a different meaning.** `INSPECT_EVAL_SAMPLE_ID=a,b` is two
  ids to `parse_sample_id` and one id with a comma in it to a plain string
  read. Nothing errors; one sample runs instead of two.
- **Accepted with the opposite meaning.** `INSPECT_EVAL_SCORE_DISPLAY` is bound
  to `--no-score-display`, so setting it *disables* the score display.
  `INSPECT_EVAL_SCORE` and `INSPECT_EVAL_LOG_SAMPLES` are likewise bound to
  `--no-score` and `--no-log-samples`.

So the reading belongs here, on the side that owns the names. `ENV_VARIABLES`
records what each field answers to and how the text converts; `NOT_FROM_ENV`
records the fields deliberately not read and why. Between them they
account for every field of `EvalSetOverrides`, which `test_eval_set_env.py`
asserts rather than trusts — along with the more important claim, that the
variable names and negations here are the ones `_cli/eval.py` actually
declares. A test can import both layers where this module cannot.

**The `eval_options` stack is what this mirrors** — the decorator `inspect
eval` and `inspect eval-set` share, a driven run being an eval set. `inspect
eval-retry` carries its own copy of several options under *different* variable
names: `INSPECT_EVAL_LOG_SAMPLES`, `INSPECT_EVAL_LOG_REALTIME` and
`INSPECT_EVAL_SCORE` where `eval_options` says `INSPECT_EVAL_NO_*`. Those are
deliberately **not** read here. Reading them would be the same bug in mirror
image — a runner honouring a variable that `inspect eval-set` ignores — and the
agreement test catches it, which is how they came to be excluded.

This module is deliberately not part of the public API: like the models it
returns, it is machinery for external runners (currently inspect_steward).
"""

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import yaml

from inspect_ai._util.config import resolve_args
from inspect_ai._util.constants import DEFAULT_LOG_SHARED, DEFAULT_RETRY_ON_ERROR
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.samples import parse_sample_id, parse_samples_limit
from inspect_ai.util._checkpoint.parse_cli import parse_checkpoint
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

from .eval_set_overrides import EvalSetOverrides, EvalSetOverridesEpochs

# --- reading one variable ----------------------------------------------------

# click's own boolean vocabulary for an `is_flag` option resolved from the
# environment (`click.types.BoolParamType`), reproduced rather than imported so
# that `_eval` does not depend on `_cli`. The test asserts the two agree.
_TRUE = {"1", "true", "t", "yes", "y", "on"}
_FALSE = {"0", "false", "f", "no", "n", "off", ""}


def _flag(text: str, variable: str) -> bool:
    """A flag's value, as click reads one from the environment."""
    lowered = text.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise PrerequisiteError(
        f"ERROR: {variable}={text!r} is not a valid boolean "
        f"(one of {', '.join(sorted(_TRUE | _FALSE - {''}))})."
    )


def _int_or_bool(true_value: int) -> Callable[[str, str], int]:
    """An option that is a bare flag or an integer (`int_or_bool_flag_callback`)."""

    def convert(text: str, variable: str) -> int:
        lowered = text.strip().lower()
        if lowered in ("true", "yes", "1"):
            return true_value
        if lowered in ("false", "no", "0"):
            return 0
        try:
            return int(text)
        except ValueError:
            raise PrerequisiteError(
                f"ERROR: {variable}={text!r} is not 'true', 'false', or an integer."
            ) from None

    return convert


def _integer(text: str, variable: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise PrerequisiteError(
            f"ERROR: {variable}={text!r} is not a valid integer."
        ) from None


def _text(text: str, variable: str) -> str:
    return text


def _only_true(text: str, variable: str) -> bool | None:
    """A flag whose body reads `True if flag else None` — off is no opinion."""
    return True if _flag(text, variable) else None


def _only_false(text: str, variable: str) -> bool | None:
    """A `--no-*` flag, whose body reads `False if no_flag else None`."""
    return False if _flag(text, variable) else None


def _negated(text: str, variable: str) -> bool:
    """A `--no-*` flag whose body reads `False if no_flag else True` (`score` alone)."""
    return not _flag(text, variable)


def _sample_shuffle(text: str, variable: str) -> bool | int | None:
    shuffle = _int_or_bool(-1)(text, variable)
    if shuffle == -1:
        return True
    return None if shuffle == 0 else shuffle


def _retry_on_error(text: str, variable: str) -> int | None:
    retries = _int_or_bool(DEFAULT_RETRY_ON_ERROR)(text, variable)
    return None if retries == 0 else retries


def _limit(text: str, variable: str) -> int | tuple[int, int] | None:
    try:
        return parse_samples_limit(text)
    except ValueError:
        raise PrerequisiteError(
            f"ERROR: {variable}={text!r} is not a sample count or a range (e.g. 10-20)."
        ) from None


def _sample_id(text: str, variable: str) -> list[str] | None:
    return parse_sample_id(text)


def _comma_separated(text: str, variable: str) -> list[str]:
    return text.split(",")


def _metadata(text: str, variable: str) -> dict[str, Any]:
    """`--metadata` is `multiple=True`, which click splits on whitespace.

    Each entry is then `parse_cli_args`: the value is YAML, so `a=1` is the
    integer one rather than the string, and a comma makes a list. An entry with
    no `=` is dropped rather than refused, which is what `parse_cli_args` does
    with one — this mirrors the CLI rather than improving on it.
    """
    entries: dict[str, Any] = {}
    for item in text.split():
        key, separator, raw = item.partition("=")
        if not separator:
            continue
        value: Any = yaml.safe_load(raw)
        if isinstance(value, str):
            parts = value.split(",")
            value = parts if len(parts) > 1 else parts[0]
        entries[key.replace("-", "_")] = value
    return entries


def _checkpoint(text: str, variable: str) -> Any:
    try:
        return parse_checkpoint(text)
    except ValueError as ex:
        raise PrerequisiteError(
            f"ERROR: {variable}={text!r} is not usable: {ex}"
        ) from ex


def _sandbox(text: str, variable: str) -> SandboxEnvironmentSpec:
    """`parse_sandbox`: a type, optionally `type:config`.

    Passing the text through would make `docker:compose.yaml` the *name* of a
    sandbox type, which resolves to nothing and fails at the point of use
    rather than here.
    """
    kind, separator, config = text.partition(":")
    return SandboxEnvironmentSpec(kind, config if separator else None)


# --- the table ---------------------------------------------------------------


class EnvVariable(NamedTuple):
    """What an override field answers to in the environment, and how it reads."""

    names: tuple[str, ...]
    """Variables inspect's CLI binds, in the order click consults them."""

    convert: Callable[[str, str], Any]
    """Text and the variable it came from, to the field's value (`None` for *no opinion*)."""


ENV_VARIABLES: dict[str, EnvVariable] = {
    # --- where output goes ---------------------------------------------------
    "log_format": EnvVariable(("INSPECT_LOG_FORMAT", "INSPECT_EVAL_LOG_FORMAT"), _text),
    "log_samples": EnvVariable(("INSPECT_EVAL_NO_LOG_SAMPLES",), _only_false),
    "log_realtime": EnvVariable(("INSPECT_EVAL_NO_LOG_REALTIME",), _only_false),
    "log_model_api": EnvVariable(("INSPECT_EVAL_LOG_MODEL_API",), _flag),
    "log_refusals": EnvVariable(("INSPECT_EVAL_LOG_REFUSALS",), _flag),
    "log_buffer": EnvVariable(("INSPECT_EVAL_LOG_BUFFER",), _integer),
    "log_shared": EnvVariable(
        ("INSPECT_LOG_SHARED", "INSPECT_EVAL_LOG_SHARED"),
        _int_or_bool(DEFAULT_LOG_SHARED),
    ),
    "log_level": EnvVariable(("INSPECT_LOG_LEVEL",), _text),
    "log_level_transcript": EnvVariable(("INSPECT_LOG_LEVEL_TRANSCRIPT",), _text),
    # --- how much of the dataset runs ----------------------------------------
    "limit": EnvVariable(("INSPECT_EVAL_LIMIT",), _limit),
    "sample_id": EnvVariable(("INSPECT_EVAL_SAMPLE_ID",), _sample_id),
    "sample_shuffle": EnvVariable(("INSPECT_EVAL_SAMPLE_SHUFFLE",), _sample_shuffle),
    "epochs": EnvVariable(("INSPECT_EVAL_EPOCHS",), _integer),
    # --- how fast it runs ----------------------------------------------------
    "max_samples": EnvVariable(("INSPECT_EVAL_MAX_SAMPLES",), _integer),
    "max_tasks": EnvVariable(("INSPECT_EVAL_MAX_TASKS",), _integer),
    "max_subprocesses": EnvVariable(("INSPECT_EVAL_MAX_SUBPROCESSES",), _integer),
    "max_sandboxes": EnvVariable(("INSPECT_EVAL_MAX_SANDBOXES",), _integer),
    "max_dataset_memory": EnvVariable(("INSPECT_EVAL_MAX_DATASET_MEMORY",), _integer),
    # --- what it talks to ----------------------------------------------------
    "model_cost_config": EnvVariable(("INSPECT_EVAL_MODEL_COST_CONFIG",), _text),
    "sandbox": EnvVariable(("INSPECT_EVAL_SANDBOX",), _sandbox),
    "sandbox_cleanup": EnvVariable(("INSPECT_EVAL_NO_SANDBOX_CLEANUP",), _only_false),
    "sandbox_prebuilt": EnvVariable(("INSPECT_EVAL_SANDBOX_PREBUILT",), _only_true),
    "checkpoint": EnvVariable(("INSPECT_EVAL_CHECKPOINT",), _checkpoint),
    "approval": EnvVariable(("INSPECT_EVAL_APPROVAL",), _text),
    # --- what happens when something breaks ----------------------------------
    "retry_on_error": EnvVariable(("INSPECT_EVAL_RETRY_ON_ERROR",), _retry_on_error),
    "score_on_error": EnvVariable(("INSPECT_EVAL_SCORE_ON_ERROR",), _flag),
    "debug_errors": EnvVariable(("INSPECT_DEBUG_ERRORS",), _flag),
    # --- what the run reports ------------------------------------------------
    "score": EnvVariable(("INSPECT_EVAL_NO_SCORE",), _negated),
    "score_display": EnvVariable(("INSPECT_EVAL_SCORE_DISPLAY",), _only_false),
    "tags": EnvVariable(("INSPECT_EVAL_TAGS",), _comma_separated),
    "metadata": EnvVariable(("INSPECT_EVAL_METADATA",), _metadata),
    "display": EnvVariable(("INSPECT_DISPLAY",), _text),
    "trace": EnvVariable(("INSPECT_EVAL_TRACE",), _only_true),
}
"""Every override field inspect's CLI reads from the environment.

Keys plus `NOT_FROM_ENV` are exactly `EvalSetOverrides.model_fields`, and each
entry's names and conversion are checked against `_cli/eval.py` by test rather
than by eye.
"""


NOT_FROM_ENV: dict[str, str] = {
    "log_dir": (
        "a driven run's log directory is the runner's to choose -- it is where "
        "the runner watches for results. INSPECT_LOG_DIR is a default for a "
        "direct `inspect eval`, and honouring it here would let an exported "
        "variable move a running fleet's output out from under it."
    ),
    "model_base_url": (
        "no CLI option binds a variable to it. Providers read "
        "INSPECT_EVAL_MODEL_BASE_URL themselves as a default "
        "(`model/_providers/util`), so it already reaches the process; "
        "promoting it to an explicit `eval_set()` argument here would change "
        "which of the two wins."
    ),
    "log_images": (
        "the eval-set option stack declares `--log-images` with no `envvar`, so "
        "`inspect eval-set` does not read one; only `inspect eval-retry` binds "
        "INSPECT_EVAL_LOG_IMAGES. Reading it would honour a variable the "
        "command being driven ignores -- probably an upstream oversight, but "
        "not one to paper over from here."
    ),
    "notification": (
        "`--notification` sets `allow_from_autoenv=False` precisely so this "
        "variable is not read as the option's value: INSPECT_EVAL_NOTIFICATION "
        "carries the Apprise URL that `notification=True` reads, and reading "
        "it here would both mean the wrong thing and copy a secret into "
        "whatever the runner persists."
    ),
}
"""Override fields inspect's CLI does *not* resolve from the environment, and why.

Recorded rather than omitted: a field missing from every table is a field
nobody decided about, and the exhaustiveness test cannot tell the difference
unless the decision is written down.
"""


ASSEMBLED = {"generate_config"}
"""Fields read from the environment, but from more than one variable each.

`ENV_VARIABLES` maps a field to variables that carry *its* value; a field built
out of several — `generate_config` from a file plus one variable per
identity-neutral setting — is assembled in `resolve_eval_env` instead. Named
here so that the exhaustiveness test still accounts for it, rather than the
table quietly having a hole the shape of whatever is complicated.

(`epochs` stays in the table: two further variables adjust its reducers, but
`INSPECT_EVAL_EPOCHS` is the one that carries the value.)
"""


# variables that carry one identity-neutral generate-config field each. The
# field set is `GENERATE_CONFIG_FIELDS_TO_EXCLUDE` -- the same partition that
# decides what `generate_config` may carry at all -- so this cannot drift from
# it without the exhaustiveness test noticing.
GENERATE_CONFIG_VARIABLES: dict[str, Callable[[str, str], Any]] = {
    "max_retries": _integer,
    "timeout": _integer,
    "attempt_timeout": _integer,
    "max_connections": _integer,
    "adaptive_connections": _text,
    "batch": _int_or_bool(1),
    "cache": _text,
    "cache_prompt": _text,
}

GENERATE_CONFIG = "INSPECT_EVAL_GENERATE_CONFIG"
"""A YAML or JSON file of generate-config values, as `--generate-config` takes."""


# --- resolution --------------------------------------------------------------


def resolve_eval_env(environ: Mapping[str, str]) -> EvalSetOverrides | None:
    """Inspect's own environment variables, as an overrides document.

    Reads what `inspect eval` would read, with the conversions `inspect eval`
    applies — so a runner honouring the result behaves the way an operator's
    exported variables led them to expect.

    An exported-but-empty variable is a shell profile rather than an
    instruction and is skipped, except where empty is a value click itself
    accepts (a flag, for which it means false).

    Args:
        environ: The environment to read, usually `os.environ`.

    Returns:
        The overrides the environment asks for, or `None` where it asks for
        nothing — an empty document and no document are the same instruction.

    Raises:
        PrerequisiteError: A variable carries a value inspect cannot read.
    """
    values: dict[str, Any] = {}
    for field, variable in ENV_VARIABLES.items():
        found = _first(environ, variable.names)
        if found is None:
            continue
        name, text = found
        converted = variable.convert(text, name)
        if converted is not None:
            values[field] = converted

    if (epochs := _epochs(environ, values.pop("epochs", None))) is not None:
        values["epochs"] = epochs
    if (config := _generate_config(environ)) is not None:
        values["generate_config"] = config

    return EvalSetOverrides.model_validate(values) if values else None


def _first(
    environ: Mapping[str, str], names: tuple[str, ...]
) -> tuple[str, str] | None:
    """The first of these variables the environment sets, as click consults them."""
    for name in names:
        value = environ.get(name)
        # a variable exported empty is how a shell profile says nothing, and
        # click reads it as unset for every option that takes a value
        if value is not None and value.strip():
            return name, value
    return None


def _epochs(
    environ: Mapping[str, str], count: int | None
) -> int | EvalSetOverridesEpochs | None:
    """An epoch count with its reducers, which the CLI assembles from three variables."""
    if count is None:
        return None
    if _first(environ, ("INSPECT_EVAL_NO_EPOCHS_REDUCER",)) is not None:
        return EvalSetOverridesEpochs(epochs=count, reducer=[])
    if (found := _first(environ, ("INSPECT_EVAL_EPOCHS_REDUCER",))) is not None:
        return EvalSetOverridesEpochs(epochs=count, reducer=found[1].split(","))
    return count


def _generate_config(environ: Mapping[str, str]) -> dict[str, Any] | None:
    """The identity-neutral generate-config fields, from a file and the per-field variables.

    A variable beats the file for the same reason a flag beats a file
    everywhere else: it is the more specific instruction.
    """
    # deferred for the reason `eval_set_overrides` defers the same import:
    # evalset.py imports this package's manifest module, so a module-level
    # import here would close the cycle
    from .evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE

    config: dict[str, Any] = {}
    if (found := _first(environ, (GENERATE_CONFIG,))) is not None:
        name, path = found
        try:
            supplied = resolve_args(path)
        except Exception as ex:
            raise PrerequisiteError(
                f"ERROR: {name}={path!r} is not usable: {ex}"
            ) from ex
        unknown = set(supplied) - set(GENERATE_CONFIG_FIELDS_TO_EXCLUDE)
        if unknown:
            raise PrerequisiteError(
                f"ERROR: {name} sets {', '.join(sorted(unknown))}, which "
                "task identity covers — a driven run cannot override those "
                "without orphaning the logs it has already written."
            )
        config.update(supplied)

    for field, convert in GENERATE_CONFIG_VARIABLES.items():
        found = _first(environ, (f"INSPECT_EVAL_{field.upper()}",))
        if found is not None:
            name, text = found
            config[field] = convert(text, name)

    return config or None
