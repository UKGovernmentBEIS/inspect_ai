import math
from typing import Any

from pydantic import BaseModel, Field, model_validator

_DEFAULT_MIN = 10
_DEFAULT_START = 20
_DEFAULT_MAX = 100


class AdaptiveConcurrency(BaseModel):
    """Bounds and tuning for an adaptive concurrency controller.

    Basic fields (`min`, `start`, `max`) bound the range the controller will
    scale within. Advanced fields (`cooldown_seconds`, `decrease_factor`,
    `scale_up_percent`) tune the response curve and have sensible defaults
    for typical evaluation workloads — see the parallelism docs for guidance.
    Accepts a string shorthand ("min-max" or "min-start-max") for use in CLI
    flags and config files; advanced fields are Python-only.
    """

    min: int = Field(default=_DEFAULT_MIN)
    """Minimum concurrency (must be >= 1)."""

    max: int = Field(default=_DEFAULT_MAX)
    """Maximum concurrency."""

    start: int = Field(default=_DEFAULT_START)
    """Starting concurrency (must be within [min, max])."""

    cooldown_seconds: float = Field(default=15.0)
    """Minimum seconds between scale-down cuts."""

    decrease_factor: float = Field(default=0.8)
    """Multiplicative factor applied to the limit on each cut (must be in (0, 1))."""

    scale_up_percent: float = Field(default=0.05)
    """Steady-state additive growth per clean round, as a fraction of current limit (must be in (0, 1])."""

    @model_validator(mode="before")
    @classmethod
    def parse_shorthand(cls, data: Any) -> Any:
        # Accept "min-max" or "min-start-max" string shorthand, and clamp the
        # implicit start (= field default) into [min, max] when start is not
        # explicitly provided. Without clamping, AdaptiveConcurrency(min=1, max=15)
        # would fail bounds validation because the default start exceeds max.
        if isinstance(data, str):
            parts = data.split("-")
            try:
                ints = [int(p) for p in parts]
            except ValueError:
                raise ValueError(
                    f"Invalid AdaptiveConcurrency shorthand {data!r}: "
                    "expected 'min-max' or 'min-start-max'"
                )
            if len(ints) == 2:
                min_val, max_val = ints
                return {
                    "min": min_val,
                    "max": max_val,
                    "start": max(min_val, min(_DEFAULT_START, max_val)),
                }
            elif len(ints) == 3:
                return {"min": ints[0], "start": ints[1], "max": ints[2]}
            else:
                raise ValueError(
                    f"Invalid AdaptiveConcurrency shorthand {data!r}: "
                    "expected 'min-max' or 'min-start-max'"
                )

        # struct form: clamp implicit min/start when max is provided but they
        # are not, so AdaptiveConcurrency(max=8) and AdaptiveConcurrency(min=1,
        # max=15) just work without bounds-validation errors from the defaults
        if isinstance(data, dict):
            max_val = data.get("max", _DEFAULT_MAX)
            if (
                "min" not in data
                and isinstance(max_val, int)
                and max_val < _DEFAULT_MIN
            ):
                data = dict(data)
                data["min"] = max_val
            if "start" not in data:
                min_val = data.get("min", _DEFAULT_MIN)
                if isinstance(min_val, int) and isinstance(max_val, int):
                    data = dict(data)
                    data["start"] = max(min_val, min(_DEFAULT_START, max_val))

        return data

    @model_validator(mode="after")
    def validate_bounds(self) -> "AdaptiveConcurrency":
        if self.min < 1:
            raise ValueError(f"AdaptiveConcurrency min must be >= 1 (got {self.min})")
        if self.max < self.min:
            raise ValueError(
                f"AdaptiveConcurrency max ({self.max}) must be >= min ({self.min})"
            )
        if self.start < self.min or self.start > self.max:
            raise ValueError(
                f"AdaptiveConcurrency start ({self.start}) must be within "
                f"[min={self.min}, max={self.max}]"
            )
        if not (math.isfinite(self.cooldown_seconds) and self.cooldown_seconds >= 0):
            raise ValueError(
                f"AdaptiveConcurrency cooldown_seconds must be a finite value >= 0 "
                f"(got {self.cooldown_seconds})"
            )
        if not (0 < self.decrease_factor < 1):
            raise ValueError(
                f"AdaptiveConcurrency decrease_factor must be in (0, 1) "
                f"(got {self.decrease_factor})"
            )
        if not (0 < self.scale_up_percent <= 1):
            raise ValueError(
                f"AdaptiveConcurrency scale_up_percent must be in (0, 1] "
                f"(got {self.scale_up_percent})"
            )
        return self
