"""Tests for the host-local checkpoint working tree."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from inspect_ai.checkpoint._working_tree import (
    attempt_working_tree,
    working_tree_root,
    write_working_tree,
)


@contextmanager
def _patch_cache_dir(tmp_path: Path) -> Iterator[None]:
    """Redirect ``inspect_cache_dir`` to a tmp directory."""

    def fake_cache_dir(subdir: str | None) -> Path:
        d = tmp_path / (subdir or "")
        d.mkdir(parents=True, exist_ok=True)
        return d

    with patch(
        "inspect_ai.checkpoint._working_tree.inspect_cache_dir",
        side_effect=fake_cache_dir,
    ):
        yield


@pytest.fixture
def cache_dir(tmp_path: Path) -> Iterator[Path]:
    with _patch_cache_dir(tmp_path):
        yield tmp_path


def test_working_tree_root_strips_eval_suffix(cache_dir: Path) -> None:
    assert working_tree_root("/logs/foo.eval") == cache_dir / "checkpoints/foo"


def test_working_tree_root_handles_s3_uri(cache_dir: Path) -> None:
    assert (
        working_tree_root("s3://bucket/path/foo.eval") == cache_dir / "checkpoints/foo"
    )


def test_working_tree_root_passthrough_when_no_suffix(cache_dir: Path) -> None:
    """Basename without the `.eval` suffix is used as-is."""
    assert working_tree_root("/logs/raw_name") == cache_dir / "checkpoints/raw_name"


def test_attempt_working_tree_uses_sample_id_and_epoch(cache_dir: Path) -> None:
    assert (
        attempt_working_tree("/logs/foo.eval", "s7", 2)
        == cache_dir / "checkpoints/foo/s7__2"
    )


async def test_write_working_tree_creates_dir_and_files(cache_dir: Path) -> None:
    attempt = await write_working_tree("/logs/foo.eval", "s1", 0)

    assert attempt.is_dir()
    assert attempt == cache_dir / "checkpoints/foo/s1__0"

    context = attempt / "context.json"
    store = attempt / "store.json"
    assert context.is_file()
    assert store.is_file()

    # Both files parse as JSON (placeholder content).
    json.loads(context.read_text())
    json.loads(store.read_text())


async def test_write_working_tree_overwrites_in_place(cache_dir: Path) -> None:
    attempt = await write_working_tree("/logs/foo.eval", "s1", 0)
    (attempt / "context.json").write_text('"polluted"')

    # Second call rewrites the placeholders.
    await write_working_tree("/logs/foo.eval", "s1", 0)
    assert json.loads((attempt / "context.json").read_text()) == {
        "messages": [],
        "events": [],
    }
