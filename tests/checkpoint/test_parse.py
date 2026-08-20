"""Unit tests for `parse_checkpoint`."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from inspect_ai.util._checkpoint import (
    ArchiveSnapshots,
    CheckpointConfig,
    Manual,
    ResticSnapshots,
    SandboxSnapshotConfig,
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


def test_yaml_file_omitted_fields_get_defaults(tmp_path: Path) -> None:
    """Fields omitted from a config file take the parser's defaults.

    These non-None defaults count as "explicitly set" in
    ``merge_checkpoint_configs`` and override lower-priority layers.
    Changing omitted fields to inherit instead is a planned follow-up
    behavior change, deliberately kept out of the strategy-selection PR.
    """
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger: manual\n")
    cfg = _parse(str(path))
    assert cfg.sandbox_paths == {}
    assert cfg.retention == "delete"
    assert cfg.max_consecutive_failures is None
    assert cfg.checkpoints_location is None


def test_yaml_file_requires_trigger(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text("sandbox_paths:\n  default:\n    strategy: archive\n")
    with pytest.raises(ValueError, match="trigger"):
        _parse(str(path))


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


def test_yaml_file_sandbox_paths_with_strategies(tmp_path: Path) -> None:
    """`sandbox_paths` values mix bare path lists and strategy mappings."""
    path = tmp_path / "ckpt.yaml"
    path.write_text(
        "trigger:\n  type: turn\n  every: 2\n"
        "sandbox_paths:\n"
        "  default:\n"
        "    paths: ['/data']\n"
        "    strategy: archive\n"
        "  web:\n"
        "    strategy: restic-incremental\n"
        "  scratch: ['/scratch']\n"
    )
    cfg = _parse(str(path))
    assert cfg.sandbox_paths == {
        "default": SandboxSnapshotConfig(
            paths=["/data"],
            strategy=ArchiveSnapshots(),
        ),
        "web": SandboxSnapshotConfig(paths=None, strategy=ResticSnapshots()),
        "scratch": ["/scratch"],
    }


def test_yaml_file_sandbox_paths_omitted_strategy_inherits(
    tmp_path: Path,
) -> None:
    """A mapping-form entry without ``strategy:`` expresses no strategy opinion.

    Matching a bare path-list value, so it doesn't stomp a
    lower-priority layer's selection for that sandbox.
    """
    path = tmp_path / "ckpt.yaml"
    path.write_text(
        "trigger: manual\nsandbox_paths:\n  default:\n    paths: ['/data']\n"
    )
    cfg = _parse(str(path))
    assert cfg.sandbox_paths == {
        "default": SandboxSnapshotConfig(paths=["/data"], strategy=None)
    }


def test_yaml_file_unknown_strategy_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.yaml"
    path.write_text("trigger: manual\nsandbox_paths:\n  default:\n    strategy: zfs\n")
    with pytest.raises(ValueError):
        parse_checkpoint(str(path))
