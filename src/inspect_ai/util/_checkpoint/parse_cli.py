"""Parse a `--checkpoint` value into a :class:`CheckpointConfig`.

Accepted forms (in order of detection):

- ``None`` / empty → ``None`` (checkpointing disabled).
- ``"<kind>:<value>"`` shorthand where ``kind`` ∈ ``{turn, time}`` →
  parsed shorthand trigger.
- The literal ``"manual"`` → ``trigger=Manual()``.
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

from ._triggers import CheckpointTrigger, Manual, TimeInterval, TurnInterval
from .config import CheckpointConfig, Retention

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_DURATION_UNITS_S: dict[str, float] = {
    "": 1.0,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}


def parse_checkpoint(value: str | None) -> CheckpointConfig | None:
    """Parse a CLI/string `--checkpoint` value into a CheckpointConfig.

    See module doc-string for the accepted forms.
    """
    if not value:
        return None
    if value == "manual":
        return CheckpointConfig(trigger=Manual())
    match value.partition(":"):
        case ("turn", ":", rest):
            return CheckpointConfig(
                trigger=TurnInterval(every=_parse_positive_int(rest, "turn"))
            )
        case ("time", ":", rest):
            return CheckpointConfig(
                trigger=TimeInterval(
                    every=_parse_duration(rest, error_prefix="--checkpoint time")
                )
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


# --- YAML/JSON config loader ----------------------------------------


class _TurnTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["turn"]
    every: int = Field(gt=0)


class _TimeTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["time"]
    every: int | float | str


_TriggerModel = Annotated[
    _TurnTriggerModel | _TimeTriggerModel,
    Field(discriminator="type"),
]


class _CheckpointConfigModel(BaseModel):
    """Pydantic mirror of :class:`CheckpointConfig` for YAML/JSON loading.

    Two fields differ from the real dataclass:
    - ``trigger`` accepts a discriminated dict (``{"type": "turn", "every": 5}``)
      or the literal ``"manual"``, and translates to a strategy instance.
    - All other fields validate directly against their dataclass counterparts.
    """

    model_config = ConfigDict(extra="forbid")

    trigger: _TriggerModel | Literal["manual"]
    checkpoints_location: str | None = None
    sandbox_paths: dict[str, list[str]] = Field(default_factory=dict)
    max_consecutive_failures: int | None = None
    retention: Retention = Field(default_factory=Retention)

    def to_dataclass(self) -> CheckpointConfig:
        return CheckpointConfig(
            trigger=_trigger_model_to_strategy(self.trigger),
            checkpoints_location=self.checkpoints_location,
            sandbox_paths=self.sandbox_paths,
            max_consecutive_failures=self.max_consecutive_failures,
            retention=self.retention,
        )


def _trigger_model_to_strategy(
    model: _TriggerModel | Literal["manual"],
) -> CheckpointTrigger:
    match model:
        case "manual":
            return Manual()
        case _TurnTriggerModel(every=n):
            return TurnInterval(every=n)
        case _TimeTriggerModel(every=v):
            return TimeInterval(every=_coerce_duration(v))


def _coerce_duration(value: int | float | str) -> timedelta:
    return (
        _parse_duration(value, error_prefix="checkpoint time")
        if isinstance(value, str)
        else timedelta(seconds=float(value))
    )


def _parse_config_file(path: str) -> CheckpointConfig:
    data: dict[str, Any] = resolve_args(path)
    try:
        return _CheckpointConfigModel.model_validate(data).to_dataclass()
    except ValidationError as e:
        raise ValueError(f"Invalid checkpoint config at {path}: {e}") from e


def _parse_duration(value: str, *, error_prefix: str = "duration") -> timedelta:
    """Parse ``15m`` / ``30s`` / ``2h`` / ``1d``, or a bare integer (seconds).

    Raises ``ValueError`` on a malformed string or a non-positive result.
    ``error_prefix`` is used to tag the raised message (e.g. the CLI flag
    name) so the diagnostic is meaningful to the caller's audience.
    """
    m = _DURATION_RE.match(value)
    if m is None:
        raise ValueError(f"{error_prefix}: expected <number><s|m|h|d>, got {value!r}")
    seconds = float(m.group(1)) * _DURATION_UNITS_S[m.group(2).lower()]
    if seconds <= 0:
        raise ValueError(f"{error_prefix}: duration must be > 0, got {value!r}")
    return timedelta(seconds=seconds)
