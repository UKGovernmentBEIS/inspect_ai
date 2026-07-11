import copy
import pickle
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from inspect_ai.monitor import (
    ComponentRef,
    MonitorContext,
    MonitorRecord,
    ProducerRef,
    SignalDerivation,
    SignalValue,
)


def component(name: str = "openai/gpt-4o") -> ComponentRef:
    return ComponentRef(name=name)


def producer() -> ProducerRef:
    return ProducerRef(name="flight-recorder", version="0.1.0")


def signal() -> SignalValue:
    return SignalValue(
        value=0.42,
        state="observed",
        derivation=SignalDerivation(method="ema", alpha=0.3),
    )


def attempt_record() -> MonitorRecord:
    return MonitorRecord(
        record_id="record-1",
        record_kind="attempt",
        emitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
        sample_uuid="sample-1",
        dataset_sample_id=7,
        epoch=1,
        attempt=1,
        will_retry=False,
        producer=producer(),
        model=component(),
        scorer=component("match"),
        execution_status="completed",
        scoring_status="scored",
        signals={"kl_acceleration": signal()},
    )


def test_signal_derivation_represents_ema_and_rolling_windows() -> None:
    ema = SignalDerivation(method="ema", alpha=0.3)
    rolling = SignalDerivation(
        method="rolling",
        window_size=20,
        parameters={"distance": "wasserstein"},
    )

    assert ema.model_dump(exclude_none=True) == {
        "method": "ema",
        "alpha": 0.3,
        "parameters": {},
    }
    assert rolling.model_dump(exclude_none=True) == {
        "method": "rolling",
        "window_size": 20,
        "parameters": {"distance": "wasserstein"},
    }


def test_custom_derivation_requires_a_stable_name() -> None:
    with pytest.raises(ValidationError, match="name"):
        SignalDerivation(method="custom")

    custom = SignalDerivation(
        method="custom",
        name="flightrecorder.advantage_drift",
        version="1",
        parameters={"distance": "wasserstein"},
    )
    assert custom.name == "flightrecorder.advantage_drift"


@pytest.mark.parametrize("reserved_key", ["method", "alpha", "window_size", "name"])
def test_derivation_parameters_cannot_shadow_schema_fields(
    reserved_key: str,
) -> None:
    with pytest.raises(ValidationError, match=reserved_key):
        SignalDerivation(method="instant", parameters={reserved_key: 0.3})


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"method": "ema"}, "alpha"),
        ({"method": "ema", "alpha": 0.0}, "alpha"),
        ({"method": "ema", "alpha": 0.3, "window_size": 20}, "window_size"),
        ({"method": "rolling"}, "window_size"),
        ({"method": "rolling", "window_size": 0}, "window_size"),
        ({"method": "instant", "alpha": 0.3}, "alpha"),
    ],
)
def test_signal_derivation_rejects_ambiguous_parameters(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SignalDerivation(**kwargs)  # type: ignore[arg-type]


def test_signal_value_distinguishes_observed_and_unavailable_values() -> None:
    observed = signal()
    unavailable = SignalValue(
        value=None,
        state="unavailable",
        reason="No token log probabilities",
        derivation=SignalDerivation(method="instant"),
    )

    assert observed.value == 0.42
    assert unavailable.model_dump(exclude_none=True) == {
        "state": "unavailable",
        "reason": "No token log probabilities",
        "derivation": {"method": "instant", "parameters": {}},
    }

    with pytest.raises(ValidationError, match="observed"):
        SignalValue(value=None, state="observed")

    with pytest.raises(ValidationError, match="must be None"):
        SignalValue(value=0.42, state="error", reason="extractor failed")


def test_rolling_signal_marks_insufficient_history_as_unavailable() -> None:
    cold_start = SignalValue(
        value=None,
        state="unavailable",
        reason="insufficient_history",
        derivation=SignalDerivation(method="rolling", window_size=20),
    )

    assert cold_start.model_dump(exclude_none=True) == {
        "state": "unavailable",
        "reason": "insufficient_history",
        "derivation": {
            "method": "rolling",
            "window_size": 20,
            "parameters": {},
        },
    }

    with pytest.raises(ValidationError, match="must be None"):
        SignalValue(
            value=0.0,
            state="unavailable",
            reason="insufficient_history",
            derivation=SignalDerivation(method="rolling", window_size=20),
        )


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), {"nested": [float("nan")]}],
)
def test_non_finite_json_values_are_rejected(value: object) -> None:
    with pytest.raises(ValidationError, match="finite"):
        SignalValue(value=value, state="observed")  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="finite"):
        ProducerRef(name="monitor", config={"value": value})  # type: ignore[dict-item]

    with pytest.raises(ValidationError, match="finite"):
        SignalDerivation(method="instant", parameters={"value": value})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    "secret_key",
    [
        "api_key",
        "apiKey",
        "APIKey",
        "ClientAPIKey",
        "clientSecret",
        "authorization",
        "HTTPAuthorization",
        "JWTToken",
    ],
)
def test_producer_config_rejects_unredacted_credentials(secret_key: str) -> None:
    with pytest.raises(ValidationError, match=secret_key):
        ProducerRef(name="monitor", config={"nested": {secret_key: "secret"}})

    producer_ref = ProducerRef(
        name="monitor", config={"nested": {secret_key: "[REDACTED]"}}
    )
    assert producer_ref.config["nested"] == {secret_key: "[REDACTED]"}

    with pytest.raises(ValidationError, match="Authorization"):
        ProducerRef(
            name="monitor",
            config={"headers": [{"Authorization": "Bearer secret"}]},
        )


def test_monitor_context_is_an_oracle_free_allowlist() -> None:
    context = MonitorContext(
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
        sample_uuid="sample-1",
        epoch=1,
        attempt=1,
        model=component(),
    )

    assert context.attempt == 1
    assert set(MonitorContext.model_fields) == {
        "eval_set_id",
        "run_id",
        "eval_id",
        "sample_uuid",
        "epoch",
        "attempt",
        "model",
    }

    with pytest.raises(ValidationError, match="target"):
        MonitorContext(
            eval_set_id=None,
            run_id="run-1",
            eval_id="eval-1",
            sample_uuid="sample-1",
            epoch=1,
            attempt=1,
            model=component(),
            target="secret",
        )  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "field",
    ["dataset_sample_id", "score", "scorer"],
)
def test_monitor_context_rejects_runtime_owned_or_oracle_fields(field: str) -> None:
    payload = {
        "eval_set_id": None,
        "run_id": "run-1",
        "eval_id": "eval-1",
        "sample_uuid": "sample-1",
        "epoch": 1,
        "attempt": 1,
        "model": {"name": "openai/gpt-4o"},
        field: "forbidden",
    }

    with pytest.raises(ValidationError):
        MonitorContext.model_validate(payload)


def test_attempt_record_serializes_derivation_and_runtime_status() -> None:
    record = attempt_record()
    payload = record.model_dump(mode="json", exclude_none=True)

    assert payload["schema_version"] == "1"
    assert payload["record_kind"] == "attempt"
    assert payload["dataset_sample_id"] == 7
    assert payload["signals"]["kl_acceleration"]["derivation"] == {
        "method": "ema",
        "alpha": 0.3,
        "parameters": {},
    }
    assert MonitorRecord.model_validate_json(record.model_dump_json()) == record


def test_record_kind_enforces_attempt_and_sample_shapes() -> None:
    attempt_payload = attempt_record().model_dump()
    with pytest.raises(ValidationError, match="attempt"):
        MonitorRecord.model_validate(attempt_payload | {"attempt": None})

    sample_payload = attempt_payload | {
        "record_id": "record-2",
        "record_kind": "sample",
        "attempt": None,
        "attempt_record_ids": ("record-1",),
        "will_retry": None,
    }
    validated = MonitorRecord.model_validate(sample_payload)
    assert validated.attempt_record_ids == ("record-1",)

    with pytest.raises(ValidationError, match="will_retry"):
        MonitorRecord.model_validate(sample_payload | {"will_retry": False})


def test_record_lifecycle_rejects_ambiguous_references_and_statuses() -> None:
    attempt = attempt_record()
    sample_payload = attempt.model_dump()
    sample_payload.update(
        record_id="sample-record",
        record_kind="sample",
        attempt=None,
        attempt_record_ids=("record-1",),
        will_retry=None,
    )

    for attempt_record_ids in [
        ("",),
        ("record-1", "record-1"),
        ("sample-record",),
    ]:
        with pytest.raises(ValidationError, match="attempt_record_ids"):
            MonitorRecord.model_validate(
                sample_payload | {"attempt_record_ids": attempt_record_ids}
            )

    with pytest.raises(ValidationError, match="will_retry"):
        MonitorRecord.model_validate(attempt.model_dump() | {"will_retry": True})

    with pytest.raises(ValidationError, match="scorer"):
        MonitorRecord.model_validate(attempt.model_dump() | {"scorer": None})

    with pytest.raises(ValidationError, match="attempt_record_ids"):
        MonitorRecord.model_validate(sample_payload | {"attempt_record_ids": ()})

    initialization_failure = sample_payload | {
        "attempt_record_ids": (),
        "execution_status": "errored",
        "scoring_status": "not_run",
        "scorer": None,
        "status_reason": "initialization failed",
    }
    assert MonitorRecord.model_validate(initialization_failure).attempt_record_ids == ()


def test_model_copy_revalidates_updates() -> None:
    signal = SignalValue(value=0.42, state="observed")
    with pytest.raises(ValidationError, match="finite"):
        signal.model_copy(update={"value": float("nan")})

    context = MonitorContext(
        eval_set_id=None,
        run_id="run-1",
        eval_id="eval-1",
        sample_uuid="sample-1",
        epoch=1,
        attempt=1,
        model=component(),
    )
    with pytest.raises(ValidationError, match="target"):
        context.model_copy(update={"target": "oracle"})

    with pytest.raises(ValidationError, match="will_retry"):
        attempt_record().model_copy(update={"will_retry": True})


def test_nested_schema_containers_cannot_be_mutated() -> None:
    producer_ref = ProducerRef(
        name="monitor",
        config={"headers": [{"Authorization": "[REDACTED]"}]},
    )
    with pytest.raises(TypeError, match="immutable"):
        producer_ref.config["api_key"] = "secret"

    headers = producer_ref.config["headers"]
    assert isinstance(headers, list)
    with pytest.raises(TypeError, match="immutable"):
        headers.append({"Authorization": "secret"})

    record = attempt_record()
    with pytest.raises(TypeError, match="immutable"):
        record.signals["late_signal"] = SignalValue(value=1.0, state="observed")

    round_trip = ProducerRef.model_validate_json(producer_ref.model_dump_json())
    assert round_trip == producer_ref


def test_serialization_revalidates_base_class_mutation_bypasses() -> None:
    component_ref = ComponentRef(name="model")
    assert component_ref.model_dump(exclude={"name"}) == {"version": None}

    producer_ref = ProducerRef(
        name="monitor",
        config={"headers": [{"Authorization": "[REDACTED]"}]},
    )
    dict.__setitem__(producer_ref.config, "APIKey", "secret")
    with pytest.raises(PydanticSerializationError, match="redacted"):
        producer_ref.model_dump_json()

    signal_value = SignalValue(value=[0.42], state="observed")
    assert isinstance(signal_value.value, list)
    list.append(signal_value.value, float("nan"))
    with pytest.raises(PydanticSerializationError, match="finite"):
        signal_value.model_dump_json()


def test_immutable_models_support_deepcopy_and_pickle() -> None:
    producer_ref = ProducerRef(
        name="monitor",
        config={"nested": [{"value": 1}]},
    )

    assert copy.deepcopy(producer_ref) == producer_ref
    assert pickle.loads(pickle.dumps(producer_ref)) == producer_ref


def test_monitor_model_fields_cannot_be_reassigned() -> None:
    record = attempt_record()

    with pytest.raises(ValidationError, match="frozen"):
        record.execution_status = "errored"
