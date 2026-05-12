"""Unit tests for `parse_checkpoint`."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from inspect_ai.util._checkpoint import (
    CheckpointConfig,
    TimeInterval,
    TurnInterval,
)
from inspect_ai.util._checkpoint.parse_cli import parse_checkpoint


def test_none_and_empty_return_none() -> None:
    assert parse_checkpoint(None) is None
    assert parse_checkpoint("") is None


def _parse(value: str) -> CheckpointConfig:
    cfg = parse_checkpoint(value)
    assert cfg is not None
    return cfg


def test_turn_shorthand() -> None:
    cfg = _parse("turn:12")
    assert isinstance(cfg.trigger, TurnInterval) and cfg.trigger.every == 12


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("time:30", timedelta(seconds=30)),
        ("time:30s", timedelta(seconds=30)),
        ("time:15m", timedelta(minutes=15)),
        ("time:2h", timedelta(hours=2)),
        ("time:1d", timedelta(days=1)),
    ],
)
def test_time_shorthand(spec: str, expected: timedelta) -> None:
    cfg = _parse(spec)
    assert isinstance(cfg.trigger, TimeInterval)
    assert cfg.trigger.every == expected


def test_manual_literal() -> None:
    cfg = _parse("manual")
    assert cfg.trigger == "manual"


def test_bad_turn_value() -> None:
    with pytest.raises(ValueError, match="turn"):
        parse_checkpoint("turn:abc")


def test_bad_time_value() -> None:
    with pytest.raises(ValueError, match="time"):
        parse_checkpoint("time:5x")


def test_negative_turn() -> None:
    with pytest.raises(ValueError, match="turn"):
        parse_checkpoint("turn:0")


def test_yaml_file(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text(
        "trigger:\n  type: turn\n  every: 8\n"
        "sandbox_paths:\n  default: ['/workspace']\n"
        "max_consecutive_failures: 2\n"
        "retention:\n  after_eval: retain\n"
    )
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TurnInterval) and cfg.trigger.every == 8
    assert cfg.sandbox_paths == {"default": ["/workspace"]}
    assert cfg.max_consecutive_failures == 2
    assert cfg.retention is not None and cfg.retention.after_eval == "retain"


def test_yaml_file_manual_trigger(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger: manual\n")
    cfg = _parse(str(path))
    assert cfg.trigger == "manual"


def test_yaml_file_time_trigger_with_suffix(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger:\n  type: time\n  every: 45m\n")
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TimeInterval)
    assert cfg.trigger.every == timedelta(minutes=45)


def test_json_file(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.json"
    path.write_text(json.dumps({"trigger": {"type": "turn", "every": 3}}))
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TurnInterval) and cfg.trigger.every == 3
