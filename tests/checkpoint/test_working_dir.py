"""Tests for the eval and sample working dirs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from inspect_ai.checkpoint._working_dir import (
    _eval_working_dir,
    _sample_working_dir,
    ensure_sample_working_dir,
)


@contextmanager
def _patch_cache_dir(tmp_path: Path) -> Iterator[None]:
    """Redirect ``inspect_cache_dir`` to a tmp directory."""

    def fake_cache_dir(subdir: str | None) -> Path:
        d = tmp_path / (subdir or "")
        d.mkdir(parents=True, exist_ok=True)
        return d

    with patch(
        "inspect_ai.checkpoint._working_dir.inspect_cache_dir",
        side_effect=fake_cache_dir,
    ):
        yield


@pytest.fixture
def cache_dir(tmp_path: Path) -> Iterator[Path]:
    with _patch_cache_dir(tmp_path):
        yield tmp_path


def test_eval_working_dir_strips_eval_suffix(cache_dir: Path) -> None:
    assert _eval_working_dir("/logs/foo.eval") == str(cache_dir / "checkpoints/foo")


def test_eval_working_dir_handles_s3_uri(cache_dir: Path) -> None:
    assert _eval_working_dir("s3://bucket/path/foo.eval") == str(
        cache_dir / "checkpoints/foo"
    )


def test_eval_working_dir_passthrough_when_no_suffix(cache_dir: Path) -> None:
    """Basename without the `.eval` suffix is used as-is."""
    assert _eval_working_dir("/logs/raw_name") == str(
        cache_dir / "checkpoints/raw_name"
    )


def test_sample_working_dir_uses_sample_id_and_epoch(cache_dir: Path) -> None:
    assert _sample_working_dir("/logs/foo.eval", "s7", 2) == str(
        cache_dir / "checkpoints/foo/s7__2"
    )


async def test_ensure_creates_dir_and_returns_path(cache_dir: Path) -> None:
    sample_dir = await ensure_sample_working_dir("/logs/foo.eval", "s1", 0)
    assert Path(sample_dir).is_dir()
    assert sample_dir == str(cache_dir / "checkpoints/foo/s1__0")
