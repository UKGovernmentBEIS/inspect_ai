"""Tests for the on-disk layout types.

Phase 2 ships `CheckpointSidecar` and `CheckpointManifest` as pure data types.
Verifies the contract: required fields, validation strictness on triggers and
engines, JSON round-trip, and ``extra="allow"`` forward-compat.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from inspect_ai.checkpoint import CheckpointManifest, CheckpointSidecar

_BASE_SIDECAR = {
    "checkpoint_id": 1,
    "trigger": "time",
    "turn": 42,
    "created_at": "2026-04-26T14:23:11Z",
    "duration_ms": 842,
    "size_bytes": 1834291,
    "host_snapshot_id": "abc123",
    "sandboxes": {"default": "def456", "tools": "ghi789"},
}

_BASE_MANIFEST = {
    "eval_id": "test-eval-0001",
    "layout_version": 1,
    "engine": "restic",
    "restic_password": "s3cr3t",
}


# --- CheckpointSidecar ----------------------------------------------------


def test_sidecar_basic_round_trip() -> None:
    sidecar = CheckpointSidecar.model_validate(_BASE_SIDECAR)
    assert sidecar.checkpoint_id == 1
    assert sidecar.trigger == "time"
    assert sidecar.created_at == datetime(2026, 4, 26, 14, 23, 11, tzinfo=timezone.utc)
    assert sidecar.sandboxes == {"default": "def456", "tools": "ghi789"}

    # JSON round-trip preserves all fields.
    rehydrated = CheckpointSidecar.model_validate_json(sidecar.model_dump_json())
    assert rehydrated == sidecar


@pytest.mark.parametrize(
    "trigger", ["time", "turn", "manual", "token", "cost", "budget"]
)
def test_sidecar_accepts_all_documented_triggers(trigger: str) -> None:
    payload = {**_BASE_SIDECAR, "trigger": trigger}
    sidecar = CheckpointSidecar.model_validate(payload)
    assert sidecar.trigger == trigger


def test_sidecar_rejects_unknown_trigger() -> None:
    payload = {**_BASE_SIDECAR, "trigger": "bogus"}
    with pytest.raises(ValidationError):
        CheckpointSidecar.model_validate(payload)


def test_sidecar_extra_fields_preserved_round_trip() -> None:
    """Forward-compat for unknown fields.

    A future inspect adds a field; older inspect must keep that field
    intact when round-tripping the JSON.
    """
    payload = {**_BASE_SIDECAR, "future_field": {"nested": [1, 2, 3]}}
    sidecar = CheckpointSidecar.model_validate(payload)
    dumped = json.loads(sidecar.model_dump_json())
    assert dumped["future_field"] == {"nested": [1, 2, 3]}


def test_sidecar_empty_sandboxes_is_valid() -> None:
    """Host-only checkpointing case: no sandbox snapshots."""
    payload = {**_BASE_SIDECAR, "sandboxes": {}}
    sidecar = CheckpointSidecar.model_validate(payload)
    assert sidecar.sandboxes == {}


# --- CheckpointManifest ---------------------------------------------------


def test_manifest_basic_round_trip() -> None:
    manifest = CheckpointManifest.model_validate(_BASE_MANIFEST)
    assert manifest.eval_id == "test-eval-0001"
    assert manifest.layout_version == 1
    assert manifest.engine == "restic"
    assert manifest.restic_password == "s3cr3t"

    rehydrated = CheckpointManifest.model_validate_json(manifest.model_dump_json())
    assert rehydrated == manifest


def test_manifest_rejects_unknown_engine() -> None:
    payload = {**_BASE_MANIFEST, "engine": "borg"}
    with pytest.raises(ValidationError):
        CheckpointManifest.model_validate(payload)


def test_manifest_extra_fields_preserved_round_trip() -> None:
    payload = {**_BASE_MANIFEST, "future_field": "later"}
    manifest = CheckpointManifest.model_validate(payload)
    dumped = json.loads(manifest.model_dump_json())
    assert dumped["future_field"] == "later"
