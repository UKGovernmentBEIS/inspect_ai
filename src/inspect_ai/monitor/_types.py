import math
import re
from typing import Any, Literal, Mapping, cast

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from typing_extensions import Self


class _FrozenDict(dict[str, Any]):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("monitor schema containers are immutable")

    __setitem__ = _immutable  # type: ignore[assignment]
    __delitem__ = _immutable  # type: ignore[assignment]
    __ior__ = _immutable  # type: ignore[assignment]
    clear = _immutable  # type: ignore[assignment]
    pop = _immutable  # type: ignore[assignment]
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable  # type: ignore[assignment]
    update = _immutable  # type: ignore[assignment]

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        memo[id(self)] = self
        return self

    def __reduce__(self) -> tuple[type[Self], tuple[dict[str, Any]]]:
        return (type(self), (dict(self),))


class _FrozenList(list[JsonValue]):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("monitor schema containers are immutable")

    __setitem__ = _immutable  # type: ignore[assignment]
    __delitem__ = _immutable  # type: ignore[assignment]
    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]
    append = _immutable  # type: ignore[assignment]
    clear = _immutable  # type: ignore[assignment]
    extend = _immutable  # type: ignore[assignment]
    insert = _immutable  # type: ignore[assignment]
    pop = _immutable  # type: ignore[assignment]
    remove = _immutable  # type: ignore[assignment]
    reverse = _immutable  # type: ignore[assignment]
    sort = _immutable  # type: ignore[assignment]

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        memo[id(self)] = self
        return self

    def __reduce__(self) -> tuple[type[Self], tuple[list[JsonValue]]]:
        return (type(self), (list(self),))


class _MonitorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Return a validated copy, including any field updates."""
        values = self.model_dump(round_trip=True)
        if deep:
            values = self.model_validate(values).model_dump(round_trip=True)
        if update:
            values.update(update)
        return self.__class__.model_validate(values)

    def _validate_serialization_state(self) -> None:
        pass

    @model_serializer(mode="wrap")
    def validate_before_serialization(
        self, handler: SerializerFunctionWrapHandler
    ) -> Any:
        self._validate_serialization_state()
        return handler(self)


def _freeze_json(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList([_freeze_json(item) for item in value])
    return value


def _validate_finite_json(value: JsonValue | None) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if isinstance(value, list):
        for item in value:
            _validate_finite_json(item)
    if isinstance(value, dict):
        for item in value.values():
            _validate_finite_json(item)


_SECRET_KEY = re.compile(
    r"(apikey|accesstoken|authtoken|token|secret|password|credential|credentials|privatekey|authorization)$"
)
_REDACTED_VALUES = {"[REDACTED]", "<redacted>", "***"}


def _normalize_config_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", key.lower())


def _is_redacted(value: JsonValue) -> bool:
    return (
        value is None
        or value is False
        or value == ""
        or (isinstance(value, str) and value in _REDACTED_VALUES)
    )


def _validate_redacted_config(value: JsonValue, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            normalized = _normalize_config_key(key)
            if _SECRET_KEY.search(normalized) and not _is_redacted(item):
                raise ValueError(f"{item_path} must be redacted before serialization")
            _validate_redacted_config(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_redacted_config(item, f"{path}[{index}]")


class ComponentRef(_MonitorModel):
    """Stable identity for a component referenced by monitor output."""

    name: str = Field(min_length=1)
    """Registry or provider-qualified component name."""

    version: str | None = Field(default=None)
    """Optional component version."""


class ProducerRef(ComponentRef):
    """Identity and configuration of a monitor producer."""

    config: dict[str, JsonValue] = Field(default_factory=dict)
    """Pre-redacted, non-secret, JSON-serializable producer configuration."""

    def _validate_serialization_state(self) -> None:
        _validate_finite_json(self.config)
        _validate_redacted_config(self.config)

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        self._validate_serialization_state()
        object.__setattr__(
            self, "config", cast(dict[str, JsonValue], _freeze_json(self.config))
        )
        return self


class SignalDerivation(_MonitorModel):
    """How a signal value was derived from observations."""

    method: Literal["instant", "ema", "rolling", "custom"]
    """Signal derivation method."""

    name: str | None = Field(default=None, min_length=1)
    """Stable algorithm name required for custom derivations."""

    version: str | None = Field(default=None, min_length=1)
    """Optional custom derivation version."""

    alpha: float | None = Field(default=None, gt=0, le=1)
    """Smoothing factor for an exponential moving average."""

    window_size: int | None = Field(default=None, gt=0)
    """Observation count for a rolling window."""

    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    """Method-specific JSON metadata such as a distance metric."""

    def _validate_serialization_state(self) -> None:
        _validate_finite_json(self.parameters)
        reserved = {"method", "name", "version", "alpha", "window_size"}
        shadowed = reserved.intersection(self.parameters)
        if shadowed:
            field = sorted(shadowed)[0]
            raise ValueError(f"parameters cannot shadow '{field}'")

    @model_validator(mode="after")
    def validate_parameters(self) -> Self:
        self._validate_serialization_state()

        if self.method == "custom":
            if self.name is None:
                raise ValueError("name is required when method is 'custom'")
        elif self.name is not None or self.version is not None:
            field = "name" if self.name is not None else "version"
            raise ValueError(f"{field} is only valid when method is 'custom'")

        if self.method == "ema":
            if self.alpha is None:
                raise ValueError("alpha is required when method is 'ema'")
            if self.window_size is not None:
                raise ValueError("window_size is not valid when method is 'ema'")
        elif self.method == "rolling":
            if self.window_size is None:
                raise ValueError("window_size is required when method is 'rolling'")
            if self.alpha is not None:
                raise ValueError("alpha is not valid when method is 'rolling'")
        elif self.alpha is not None or self.window_size is not None:
            field = "alpha" if self.alpha is not None else "window_size"
            raise ValueError(f"{field} is not valid when method is '{self.method}'")
        object.__setattr__(
            self,
            "parameters",
            cast(dict[str, JsonValue], _freeze_json(self.parameters)),
        )
        return self


class SignalValue(_MonitorModel):
    """A monitor signal together with its availability and derivation."""

    value: JsonValue | None = Field(default=None)
    """Observed JSON value, or `None` when no value is available."""

    state: Literal["observed", "unavailable", "not_applicable", "error"]
    """Availability state of the signal."""

    reason: str | None = Field(default=None)
    """Optional explanation for a non-observed state."""

    derivation: SignalDerivation = Field(
        default_factory=lambda: SignalDerivation(method="instant")
    )
    """Description of how the value was derived."""

    def _validate_serialization_state(self) -> None:
        _validate_finite_json(self.value)
        if self.state == "observed" and self.value is None:
            raise ValueError("observed signals require a non-null value")
        if self.state != "observed" and self.value is not None:
            raise ValueError(f"value must be None when state is '{self.state}'")

    @model_validator(mode="after")
    def validate_value_state(self) -> Self:
        self._validate_serialization_state()
        if self.value is not None:
            object.__setattr__(self, "value", _freeze_json(self.value))
        return self


class MonitorContext(_MonitorModel):
    """Oracle-free context exposed to a monitor producer."""

    eval_set_id: str | None = Field(default=None)
    """Evaluation set identifier, when the sample belongs to an eval set."""

    run_id: str = Field(min_length=1)
    """Evaluation run identifier."""

    eval_id: str = Field(min_length=1)
    """Task evaluation identifier."""

    sample_uuid: str = Field(min_length=1)
    """Stable sample UUID across attempts."""

    epoch: int = Field(gt=0)
    """One-based sample epoch."""

    attempt: int = Field(gt=0)
    """One-based sample attempt."""

    model: ComponentRef
    """Model used for the sample."""


class MonitorRecord(_MonitorModel):
    """Attempt or sample record for an append-only persistence stream.

    Append-only is a recorder invariant: persisted records are never updated.
    Field reassignment and nested schema-container mutation are both rejected.
    """

    schema_version: Literal["1"] = "1"
    """Monitor record schema version."""

    record_id: str = Field(min_length=1)
    """Unique record identifier."""

    record_kind: Literal["attempt", "sample"]
    """Lifecycle level represented by this record."""

    emitted_at: AwareDatetime
    """Timezone-aware record emission time."""

    eval_set_id: str | None = Field(default=None)
    run_id: str = Field(min_length=1)
    eval_id: str = Field(min_length=1)
    sample_uuid: str = Field(min_length=1)
    dataset_sample_id: str | int
    epoch: int = Field(gt=0)
    attempt: int | None = Field(default=None, gt=0)
    attempt_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    will_retry: bool | None = Field(default=None)

    producer: ProducerRef
    model: ComponentRef
    scorer: ComponentRef | None = Field(default=None)

    execution_status: Literal["completed", "errored", "cancelled"]
    scoring_status: Literal[
        "scored",
        "abstained",
        "unscored",
        "not_run",
        "errored",
    ]
    status_reason: str | None = Field(default=None)

    signals: dict[str, SignalValue] = Field(default_factory=dict)
    trace_ref: str | None = Field(default=None)

    def _validate_serialization_state(self) -> None:
        for name, signal in self.signals.items():
            if not name:
                raise ValueError("signal names must be non-empty")
            if not isinstance(signal, SignalValue):
                raise ValueError(f"signal '{name}' must be a SignalValue")

    @model_validator(mode="after")
    def validate_record_shape(self) -> Self:
        self._validate_serialization_state()
        if self.record_kind == "attempt":
            if self.attempt is None:
                raise ValueError("attempt is required for attempt records")
            if self.attempt_record_ids:
                raise ValueError("attempt_record_ids must be empty for attempt records")
            if self.will_retry is None:
                raise ValueError("will_retry is required for attempt records")
            if self.will_retry and self.execution_status != "errored":
                raise ValueError(
                    "will_retry can be true only when execution_status is 'errored'"
                )
        else:
            if self.attempt is not None:
                raise ValueError("attempt must be None for sample records")
            if self.will_retry is not None:
                raise ValueError("will_retry must be None for sample records")
            if any(not record_id for record_id in self.attempt_record_ids):
                raise ValueError("attempt_record_ids cannot contain empty IDs")
            if len(set(self.attempt_record_ids)) != len(self.attempt_record_ids):
                raise ValueError("attempt_record_ids cannot contain duplicates")
            if self.record_id in self.attempt_record_ids:
                raise ValueError(
                    "attempt_record_ids cannot contain the sample record_id"
                )
            if not self.attempt_record_ids and not (
                self.execution_status in {"errored", "cancelled"}
                and self.scoring_status == "not_run"
            ):
                raise ValueError(
                    "attempt_record_ids can be empty only for a terminal "
                    "initialization failure"
                )

        if self.scoring_status == "scored" and self.scorer is None:
            raise ValueError("scorer is required when scoring_status is 'scored'")
        object.__setattr__(
            self,
            "signals",
            cast(dict[str, SignalValue], _FrozenDict(self.signals)),
        )
        return self


__all__ = [
    "ComponentRef",
    "MonitorContext",
    "MonitorRecord",
    "ProducerRef",
    "SignalDerivation",
    "SignalValue",
]
