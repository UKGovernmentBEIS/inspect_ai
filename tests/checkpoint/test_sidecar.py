"""Tests for the on-disk layout types.

Pure data types: `CheckpointDetails` (per-checkpoint `ckpt-NNNNN.json`)
and `CheckpointSample` (per-sample `sample.json`).
Verifies the contract: required fields, validation strictness on
triggers, JSON round-trip, and ``extra="allow"`` forward-compat.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from inspect_ai.util._checkpoint._layout import CheckpointDetails, CheckpointSample


def _info(
    snapshot_id: str, size_bytes: int = 0, duration_ms: int = 0
) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "size_bytes": size_bytes,
        "duration_ms": duration_ms,
    }


_BASE_SIDECAR = {
    "checkpoint_id": 1,
    "trigger": "time",
    "turn": 42,
    "created_at": "2026-04-26T14:23:11Z",
    "duration_ms": 842,
    "size_bytes": 1834291,
    "host": _info("abc123"),
    "sandboxes": {
        "default": _info("def456"),
        "tools": _info("ghi789"),
    },
}

_BASE_SAMPLE = {
    "restic_password": "s3cr3t",
}


# --- CheckpointDetails ----------------------------------------------------


def test_sidecar_basic_round_trip() -> None:
    sidecar = CheckpointDetails.model_validate(_BASE_SIDECAR)
    assert sidecar.checkpoint_id == 1
    assert sidecar.trigger == "time"
    assert sidecar.created_at == datetime(2026, 4, 26, 14, 23, 11, tzinfo=timezone.utc)
    assert sidecar.host.snapshot_id == "abc123"
    assert {name: info.snapshot_id for name, info in sidecar.sandboxes.items()} == {
        "default": "def456",
        "tools": "ghi789",
    }

    # JSON round-trip preserves all fields.
    rehydrated = CheckpointDetails.model_validate_json(sidecar.model_dump_json())
    assert rehydrated == sidecar


@pytest.mark.parametrize("trigger", ["time", "turn", "manual"])
def test_sidecar_accepts_all_documented_triggers(trigger: str) -> None:
    payload = {**_BASE_SIDECAR, "trigger": trigger}
    sidecar = CheckpointDetails.model_validate(payload)
    assert sidecar.trigger == trigger


def test_sidecar_rejects_unknown_trigger() -> None:
    payload = {**_BASE_SIDECAR, "trigger": "bogus"}
    with pytest.raises(ValidationError):
        CheckpointDetails.model_validate(payload)


def test_sidecar_extra_fields_preserved_round_trip() -> None:
    """Forward-compat for unknown fields.

    A future inspect adds a field; older inspect must keep that field
    intact when round-tripping the JSON.
    """
    payload = {**_BASE_SIDECAR, "future_field": {"nested": [1, 2, 3]}}
    sidecar = CheckpointDetails.model_validate(payload)
    dumped = json.loads(sidecar.model_dump_json())
    assert dumped["future_field"] == {"nested": [1, 2, 3]}


def test_sidecar_empty_sandboxes_is_valid() -> None:
    """Host-only checkpointing case: no sandbox snapshots."""
    payload = {**_BASE_SIDECAR, "sandboxes": {}}
    sidecar = CheckpointDetails.model_validate(payload)
    assert sidecar.sandboxes == {}


# --- CheckpointSample -----------------------------------------------------


def test_sample_basic_round_trip() -> None:
    sample = CheckpointSample.model_validate(_BASE_SAMPLE)
    assert sample.restic_password == "s3cr3t"

    rehydrated = CheckpointSample.model_validate_json(sample.model_dump_json())
    assert rehydrated == sample


def test_sample_requires_password() -> None:
    with pytest.raises(ValidationError):
        CheckpointSample.model_validate({})


def test_sample_extra_fields_preserved_round_trip() -> None:
    payload = {**_BASE_SAMPLE, "future_field": "later"}
    sample = CheckpointSample.model_validate(payload)
    dumped = json.loads(sample.model_dump_json())
    assert dumped["future_field"] == "later"
