"""Unit tests for `parse_checkpoint`."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from inspect_ai.util._checkpoint import (
    CheckpointConfig,
    Manual,
    TimeInterval,
    TokenInterval,
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


def test_bare_time_rejected() -> None:
    """A bare numeric duration (no unit) is no longer accepted."""
    with pytest.raises(ValueError, match="time"):
        parse_checkpoint("time:30")


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("token:500k", 500_000),
        ("token:2m", 2_000_000),
        ("token:1b", 1_000_000_000),
        ("token:1.5m", 1_500_000),
    ],
)
def test_token_shorthand(spec: str, expected: int) -> None:
    cfg = _parse(spec)
    assert isinstance(cfg.trigger, TokenInterval)
    assert cfg.trigger.every == expected


@pytest.mark.parametrize("spec", ["token:500000", "token:0k", "token:0.0001k"])
def test_bad_token_value(spec: str) -> None:
    with pytest.raises(ValueError, match="token"):
        parse_checkpoint(spec)


def test_default_sentinel_enables_without_trigger() -> None:
    cfg = _parse("default")
    assert cfg.trigger is None


def test_manual_literal() -> None:
    cfg = _parse("manual")
    assert isinstance(cfg.trigger, Manual)


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
        "retention: retain\n"
    )
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TurnInterval) and cfg.trigger.every == 8
    assert cfg.sandbox_paths == {"default": ["/workspace"]}
    assert cfg.max_consecutive_failures == 2
    assert cfg.retention == "retain"


def test_yaml_file_manual_trigger(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger: manual\n")
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, Manual)


def test_yaml_file_time_trigger_with_suffix(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger:\n  type: time\n  every: 45m\n")
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TimeInterval)
    assert cfg.trigger.every == timedelta(minutes=45)


def test_yaml_file_token_trigger(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger:\n  type: token\n  every: 500000\n")
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TokenInterval) and cfg.trigger.every == 500_000


def test_yaml_file_token_trigger_suffixed(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text('trigger:\n  type: token\n  every: "1.5m"\n')
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TokenInterval) and cfg.trigger.every == 1_500_000


def test_yaml_file_time_numeric_rejected(tmp_path: Path) -> None:
    """Bare numeric seconds are rejected; a suffixed string is required."""
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger:\n  type: time\n  every: 30\n")
    with pytest.raises(ValueError):
        parse_checkpoint(str(path))


def test_json_file(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.json"
    path.write_text(json.dumps({"trigger": {"type": "turn", "every": 3}}))
    cfg = _parse(str(path))
    assert isinstance(cfg.trigger, TurnInterval) and cfg.trigger.every == 3
