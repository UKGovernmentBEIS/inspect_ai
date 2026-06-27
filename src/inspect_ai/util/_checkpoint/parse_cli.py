"""Parse a `--checkpoint` value into a :class:`CheckpointConfig`.

Accepted forms (in order of detection):

- ``None`` / empty → ``None`` (checkpointing disabled).
- The literal ``"default"`` → ``CheckpointConfig(trigger=None)`` —
  enable checkpointing without pinning a trigger, deferring the
  trigger to a sample-level config or the merge-time default.
- ``"<kind>:<value>"`` shorthand where ``kind`` ∈ ``{turn, time,
  token}`` → parsed shorthand trigger.
- The literal ``"manual"`` → ``trigger=Manual()``.
- Otherwise → treat as a file path; load YAML/JSON via
  :func:`inspect_ai._util.config.resolve_args` and validate against
  :class:`_CheckpointConfigModel`.

The CLI's bare ``--checkpoint`` flag is mapped to ``"default"`` by
Click's ``flag_value``; the merge resolver supplies the concrete
default trigger (see ``DEFAULT_CHECKPOINT_TRIGGER``) once a sample is
in hand.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inspect_ai._util.config import resolve_args

from ._triggers import (
    CheckpointTrigger,
    Manual,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from .config import CheckpointConfig

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$", re.IGNORECASE)
_DURATION_UNITS_S: dict[str, float] = {
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}

_TOKEN_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmb])\s*$", re.IGNORECASE)
_TOKEN_UNITS: dict[str, int] = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
}


def parse_checkpoint(value: str | None) -> CheckpointConfig | None:
    """Parse a CLI/string `--checkpoint` value into a CheckpointConfig.

    See module doc-string for the accepted forms.
    """
    if not value:
        return None
    if value == "default":
        return CheckpointConfig(trigger=None)
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
        case ("token", ":", rest):
            return CheckpointConfig(
                trigger=TokenInterval(
                    every=_parse_tokens(rest, error_prefix="--checkpoint token")
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


def _parse_tokens(value: str, *, error_prefix: str = "tokens") -> int:
    """Parse ``500k`` / ``2m`` / ``1.5m`` / ``1b`` into a token count.

    A ``k``/``m``/``b`` suffix is required (no bare integer). Decimals
    are allowed as long as the result is a whole, positive number of
    tokens.
    """
    m = _TOKEN_RE.match(value)
    if m is None:
        raise ValueError(f"{error_prefix}: expected <number><k|m|b>, got {value!r}")
    tokens = float(m.group(1)) * _TOKEN_UNITS[m.group(2).lower()]
    if tokens <= 0:
        raise ValueError(f"{error_prefix}: value must be > 0, got {value!r}")
    if not tokens.is_integer():
        raise ValueError(
            f"{error_prefix}: must resolve to a whole number of tokens, got {value!r}"
        )
    return int(tokens)


# --- YAML/JSON config loader ----------------------------------------


class _TurnTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["turn"]
    every: int = Field(gt=0)


class _TimeTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["time"]
    every: str
    """Suffixed duration string (``"30s"`` / ``"15m"`` / ``"2h"`` /
    ``"1d"``). A bare numeric value is rejected — the unit is required."""


class _TokenTriggerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["token"]
    every: int | str
    """Raw token count (``500000``) or a suffixed string (``"500k"`` /
    ``"1.5m"`` / ``"1b"``)."""


_TriggerModel = Annotated[
    _TurnTriggerModel | _TimeTriggerModel | _TokenTriggerModel,
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
    retention: Literal["delete", "retain"] = "delete"

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
            return TimeInterval(
                every=_parse_duration(v, error_prefix="checkpoint time")
            )
        case _TokenTriggerModel(every=v):
            return TokenInterval(
                every=v
                if isinstance(v, int)
                else _parse_tokens(v, error_prefix="checkpoint token")
            )


def _parse_config_file(path: str) -> CheckpointConfig:
    data: dict[str, Any] = resolve_args(path)
    try:
        return _CheckpointConfigModel.model_validate(data).to_dataclass()
    except ValidationError as e:
        raise ValueError(f"Invalid checkpoint config at {path}: {e}") from e


def _parse_duration(value: str, *, error_prefix: str = "duration") -> timedelta:
    """Parse ``15m`` / ``30s`` / ``2h`` / ``1d`` into a ``timedelta``.

    A ``s``/``m``/``h``/``d`` suffix is required — a bare number is
    rejected. Raises ``ValueError`` on a malformed string or a
    non-positive result.
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
