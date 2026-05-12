"""Parse a `--checkpoint` value into a :class:`CheckpointConfig`.

Accepted forms (in order of detection):

- ``None`` / empty → ``None`` (checkpointing disabled).
- ``"<kind>:<value>"`` shorthand where ``kind`` ∈
  ``{turn, time, token, cost}`` → parsed shorthand trigger.
- The literal ``"manual"`` → ``trigger="manual"``.
- Otherwise → treat as a file path; load YAML/JSON via
  :func:`inspect_ai._util.config.resolve_args` and validate against
  :class:`_CheckpointConfigModel`.

The CLI's bare ``--checkpoint`` flag is mapped to a concrete shorthand
(``"turn:5"``) by Click's ``flag_value``; this parser has no
default-policy knowledge.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inspect_ai._util.config import resolve_args

from .config import (
    BudgetPercent,
    CheckpointConfig,
    CheckpointTrigger,
    CostInterval,
    Retention,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)


def parse_checkpoint(value: str | None) -> CheckpointConfig | None:
    """Parse a CLI/string `--checkpoint` value into a CheckpointConfig.

    See module doc-string for the accepted forms.
    """
    if not value:
        return None
    if value == "manual":
        return CheckpointConfig(trigger="manual")
    match value.partition(":"):
        case ("turn", ":", rest):
            return CheckpointConfig(
                trigger=TurnInterval(every=_parse_positive_int(rest, "turn"))
            )
        case ("time", ":", rest):
            return CheckpointConfig(trigger=TimeInterval(every=_parse_duration(rest)))
        case ("token", ":", rest):
            return CheckpointConfig(
                trigger=TokenInterval(every=_parse_positive_int(rest, "token"))
            )
        case ("cost", ":", rest):
            return CheckpointConfig(
                trigger=CostInterval(every=_parse_positive_float(rest, "cost"))
            )
        case _:
            return _parse_config_file(value)


def _parse_positive_int(value: str, kind: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise ValueError(
            f"--checkpoint {kind}: expected an integer, got {value!r}"
        ) from exc
    if n <= 0:
        raise ValueError(f"--checkpoint {kind}: value must be > 0, got {n}")
    return n


def _parse_positive_float(value: str, kind: str) -> float:
    try:
        x = float(value)
    except ValueError as exc:
        raise ValueError(
            f"--checkpoint {kind}: expected a number, got {value!r}"
        ) from exc
    if x <= 0:
        raise ValueError(f"--checkpoint {kind}: value must be > 0, got {x}")
    return x


_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_DURATION_UNITS_S = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def _parse_duration(value: str) -> timedelta:
    """Parse ``15m``, ``30s``, ``2h``, ``1d``, or a bare integer (seconds)."""
    m = _DURATION_RE.match(value)
    if m is None:
        raise ValueError(
            f"--checkpoint time: expected <number><s|m|h|d>, got {value!r}"
        )
    n = float(m.group(1))
    unit = m.group(2).lower()
    seconds = n * _DURATION_UNITS_S[unit]
    if seconds <= 0:
        raise ValueError(f"--checkpoint time: duration must be > 0, got {value!r}")
    return timedelta(seconds=seconds)


# --- YAML/JSON config loader ----------------------------------------


class _TurnTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["turn"]
    every: int = Field(gt=0)


class _TimeTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["time"]
    every: int | float | str


class _TokenTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["token"]
    every: int = Field(gt=0)


class _CostTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cost"]
    every: float = Field(gt=0)


class _BudgetTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["budget"]
    budget: Literal["token", "cost", "time", "working"]
    percent: float = Field(gt=0)


_TriggerModel = Annotated[
    _TurnTriggerModel
    | _TimeTriggerModel
    | _TokenTriggerModel
    | _CostTriggerModel
    | _BudgetTriggerModel,
    Field(discriminator="type"),
]


class _RetentionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_eval: Literal["delete", "retain"] = "delete"


class _CheckpointConfigModel(BaseModel):
    """Pydantic mirror of :class:`CheckpointConfig` for YAML/JSON loading."""

    model_config = ConfigDict(extra="forbid")

    trigger: _TriggerModel | Literal["manual"]
    checkpoints_dir: str | None = None
    sandbox_paths: dict[str, list[str]] = Field(default_factory=dict)
    max_consecutive_failures: int | None = None
    retention: _RetentionModel = Field(default_factory=_RetentionModel)

    def to_dataclass(self) -> CheckpointConfig:
        return CheckpointConfig(
            trigger=_trigger_model_to_dataclass(self.trigger),
            checkpoints_dir=self.checkpoints_dir,
            sandbox_paths=self.sandbox_paths,
            max_consecutive_failures=self.max_consecutive_failures,
            retention=Retention(after_eval=self.retention.after_eval),
        )


def _trigger_model_to_dataclass(
    model: _TriggerModel | Literal["manual"],
) -> CheckpointTrigger:
    match model:
        case "manual":
            return "manual"
        case _TurnTriggerModel(every=n):
            return TurnInterval(every=n)
        case _TimeTriggerModel(every=v):
            return TimeInterval(every=_coerce_duration(v))
        case _TokenTriggerModel(every=n):
            return TokenInterval(every=n)
        case _CostTriggerModel(every=n):
            return CostInterval(every=n)
        case _BudgetTriggerModel(budget=b, percent=p):
            return BudgetPercent(budget=b, percent=p)


def _coerce_duration(value: int | float | str) -> timedelta:
    return (
        _parse_duration(value)
        if isinstance(value, str)
        else timedelta(seconds=float(value))
    )


def _parse_config_file(path: str) -> CheckpointConfig:
    data: dict[str, Any] = resolve_args(path)
    try:
        return _CheckpointConfigModel.model_validate(data).to_dataclass()
    except ValidationError as e:
        raise ValueError(f"Invalid checkpoint config at {path}: {e}") from e
