"""Records of mid-run config changes applied via the control channel.

`inspect ctl config` retunes a running eval's launch configuration in memory
(concurrency caps, log-buffer params, retry-loop overrides). Each applied
change is persisted into the affected eval logs as a
:class:`ConfigUpdate` — an append-only, provenance-carrying record shaped
like `log_updates` (see ``design/ctl/config-log-persistence.md``). The
launch config (`EvalSpec.config` / `EvalSpec.model_generate_config`) is
never mutated: it stays the record of what the eval was *launched* with,
and :func:`effective_eval_config` / :func:`effective_generate_config` fold
the updates over it for readers that want the final effective values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeVar, cast

from pydantic import BaseModel, Field, JsonValue

from inspect_ai.log._edit import ProvenanceData

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalConfig, EvalLog, EvalSpec
    from inspect_ai.model import GenerateConfig


class ConfigValueChange(BaseModel):
    """One knob's value change within a config update."""

    config: Literal["eval", "generate"]
    """Which recorded config object the knob shadows (`EvalConfig` or `GenerateConfig`)."""

    name: str
    """Field name in that object (same spelling as the ctl knob, e.g. "max_samples")."""

    value: JsonValue = Field(default=None)
    """New value.

    May itself be None where None is a meaningful setting for the knob
    (e.g. a time_limit of None lifts the limit entirely)."""

    cleared: bool = Field(default=False)
    """True when an override was removed (the retry knobs' `clear`).

    The knob reverts to its launch value and `value` carries no meaning
    (set to None)."""

    previous: JsonValue = Field(default=None)
    """Effective value before this change (informational, best-effort).

    Never used to compute effective config — the fold in
    `effective_eval_config()` uses launch values + ordered updates only."""


class ConfigUpdate(BaseModel):
    """A group of config changes applied together, sharing provenance."""

    changes: list[ConfigValueChange]
    """The knob changes applied by this update."""

    scope: Literal["task", "process"]
    """Blast radius of the change.

    "task" affects only this log's task; "process" every task in the host
    process (each affected task's log carries the record)."""

    provenance: ProvenanceData
    """Who applied the change, when, and why."""


TConfig = TypeVar("TConfig", bound=BaseModel)


def _fold_config_updates(
    launch: TConfig,
    updates: list[ConfigUpdate] | None,
    config: Literal["eval", "generate"],
) -> TConfig:
    """Apply `updates` (in order) over a copy of the `launch` config.

    A `cleared` change restores the launch value; a `value: None` change
    sets a nullable knob to null (e.g. lifting a time limit). Changes
    naming a field the config object doesn't have (e.g. records written by
    a newer inspect) are skipped rather than erroring.
    """
    effective = launch.model_copy(deep=True)
    for update in updates or []:
        for change in update.changes:
            if change.config != config or change.name not in type(launch).model_fields:
                continue
            new_value = getattr(launch, change.name) if change.cleared else change.value
            setattr(effective, change.name, new_value)
    return effective


def effective_eval_config(log: EvalLog) -> "EvalConfig":
    """The eval config the run ended up under, after any mid-run retunes.

    Returns a copy of the launch `log.eval.config` with `log.config_updates`
    applied in order (a `cleared` change restores the launch value; a
    `value: None` change sets a nullable knob to null). With no updates this
    is just a copy of the launch config.

    Args:
        log: Eval log.

    Returns:
        Effective `EvalConfig` (launch config + ordered config updates).
    """
    return _fold_config_updates(log.eval.config, log.config_updates, "eval")


def effective_generate_config(log: EvalLog) -> "GenerateConfig":
    """The generate config the run ended up under, after any mid-run retunes.

    Returns a copy of the launch `log.eval.model_generate_config` with
    `log.config_updates` applied in order. Note that `max_connections` is a
    knob over live per-model controllers: the folded value is the retuned
    ceiling — the honest answer to "what was it running at" — even though
    the launch field is per-model. A retune restricted to particular models
    carries the filter in `provenance.metadata["max_connections_model"]`
    but folds in regardless; consult that metadata when the process hosted
    several models.

    Args:
        log: Eval log.

    Returns:
        Effective `GenerateConfig` (launch config + ordered config updates).
    """
    return _fold_config_updates(
        log.eval.model_generate_config, log.config_updates, "generate"
    )


def fill_previous_from_launch(update: ConfigUpdate, eval: "EvalSpec") -> ConfigUpdate:
    """Copy of `update` with missing `previous` values filled from launch config.

    The control-channel appliers report `previous` where they can read it
    live (a limiter's old value, a prior override); for a first-time change
    to a knob they have no per-log view of the launch value, so each log
    fills it from its own launch config at recording time. `previous` is
    informational — a reader sees `5 → 20` without replaying history — and
    is never used to compute effective config.
    """
    from pydantic_core import to_jsonable_python

    filled = update.model_copy(deep=True)
    for change in filled.changes:
        if change.previous is not None:
            continue
        launch: BaseModel = (
            eval.config if change.config == "eval" else eval.model_generate_config
        )
        if change.name in type(launch).model_fields:
            change.previous = cast(
                JsonValue,
                to_jsonable_python(
                    getattr(launch, change.name), fallback=lambda _: None
                ),
            )
    return filled
