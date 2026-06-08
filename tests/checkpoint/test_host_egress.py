"""Tests for the host egress (sample staging dir → remote sample checkpoints dir).

Local filesystems are the cleanest harness — ``AsyncFilesystem``'s
local path simply opens via fsspec's ``LocalFileSystem``, so a
``tmp_path``-based destination exercises the same code path as a
remote sample checkpoints dir minus the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from inspect_ai.util._checkpoint._host_egress import (
    MANIFEST_FILENAME,
    _safe_order,
    host_egress,
)


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    """Per-test staging dir.

    Pre-creates the context subdir so its contents are reliably
    excluded from the egress.
    """
    s = tmp_path / "staging"
    s.mkdir()
    (s / "context").mkdir()
    return s


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    d = tmp_path / "dest"
    d.mkdir()
    return d


def _write(p: Path, content: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


async def test_noop_when_no_files(staging: Path, dest: Path) -> None:
    await host_egress(staging_dir=str(staging), destination_dir=str(dest))
    assert list(dest.iterdir()) == []
    assert not (staging / MANIFEST_FILENAME).exists()


async def test_ships_new_files_and_writes_manifest(staging: Path, dest: Path) -> None:
    _write(staging / "restic" / "host" / "config", "host-config")
    _write(staging / "restic" / "host" / "keys" / "abc", "host-key")
    _write(staging / "restic" / "host" / "data" / "ab" / "cdef", "pack-data")
    _write(staging / "restic" / "restic-config.json", '{"restic_password":"pwd"}')
    _write(staging / "ckpt-00001.json", '{"checkpoint_id":1}')

    await host_egress(staging_dir=str(staging), destination_dir=str(dest))

    # Files at the destination
    assert (dest / "restic" / "host" / "config").read_text() == "host-config"
    assert (dest / "restic" / "host" / "keys" / "abc").read_text() == "host-key"
    assert (
        dest / "restic" / "host" / "data" / "ab" / "cdef"
    ).read_text() == "pack-data"
    assert (
        dest / "restic" / "restic-config.json"
    ).read_text() == '{"restic_password":"pwd"}'
    assert (dest / "ckpt-00001.json").read_text() == '{"checkpoint_id":1}'

    # Manifest reflects shipment
    manifest = (staging / MANIFEST_FILENAME).read_text().splitlines()
    assert set(manifest) == {
        "restic/host/config",
        "restic/host/keys/abc",
        "restic/host/data/ab/cdef",
        "restic/restic-config.json",
        "ckpt-00001.json",
    }


async def test_excludes_context_subdir(staging: Path, dest: Path) -> None:
    _write(staging / "context" / "events.json", "events")
    _write(staging / "context" / "store.json", "store")
    _write(staging / "restic" / "host" / "config", "host-config")

    await host_egress(staging_dir=str(staging), destination_dir=str(dest))

    assert not (dest / "context").exists()
    assert (dest / "restic" / "host" / "config").is_file()
    manifest = (staging / MANIFEST_FILENAME).read_text().splitlines()
    assert "context/events.json" not in manifest


async def test_second_cycle_only_ships_new_files(staging: Path, dest: Path) -> None:
    _write(staging / "restic" / "host" / "config", "host-config")
    _write(staging / "ckpt-00001.json", "first")
    await host_egress(staging_dir=str(staging), destination_dir=str(dest))

    # Tamper with what's already at the destination to prove the
    # second egress doesn't re-ship it.
    (dest / "restic" / "host" / "config").write_text("untouched-after-egress")

    _write(staging / "restic" / "host" / "data" / "ab" / "cd", "pack")
    _write(staging / "ckpt-00002.json", "second")
    await host_egress(staging_dir=str(staging), destination_dir=str(dest))

    assert (dest / "restic" / "host" / "config").read_text() == "untouched-after-egress"
    assert (dest / "restic" / "host" / "data" / "ab" / "cd").read_text() == "pack"
    assert (dest / "ckpt-00002.json").read_text() == "second"


async def test_sandbox_repos_shipped(staging: Path, dest: Path) -> None:
    _write(staging / "restic" / "sandboxes" / "default" / "config", "sb-config")
    _write(
        staging / "restic" / "sandboxes" / "default" / "data" / "ab" / "cd", "sb-pack"
    )
    _write(staging / "ckpt-00001.json", "side")

    await host_egress(staging_dir=str(staging), destination_dir=str(dest))

    assert (dest / "restic" / "sandboxes" / "default" / "config").is_file()
    assert (dest / "restic" / "sandboxes" / "default" / "data" / "ab" / "cd").is_file()


def test_safe_order_ships_checkpoint_file_last() -> None:
    files = [
        "ckpt-00001.json",
        "restic/host/snapshots/abc",
        "restic/host/data/ab/cd",
        "restic/host/index/ef",
        "restic/host/config",
        "restic/host/keys/key1",
        "restic/restic-config.json",
    ]
    ordered = _safe_order(files)
    # config + keys → data → index → snapshots → restic-config.json → checkpoint file
    assert ordered.index("restic/host/config") < ordered.index("restic/host/data/ab/cd")
    assert ordered.index("restic/host/keys/key1") < ordered.index(
        "restic/host/data/ab/cd"
    )
    assert ordered.index("restic/host/data/ab/cd") < ordered.index(
        "restic/host/index/ef"
    )
    assert ordered.index("restic/host/index/ef") < ordered.index(
        "restic/host/snapshots/abc"
    )
    assert ordered.index("restic/host/snapshots/abc") < ordered.index(
        "restic/restic-config.json"
    )
    assert ordered.index("restic/restic-config.json") < ordered.index("ckpt-00001.json")


def test_safe_order_checkpoint_file_last_across_multiple() -> None:
    files = ["ckpt-00002.json", "restic/host/data/ab", "ckpt-00001.json"]
    ordered = _safe_order(files)
    # Both checkpoint files come after the data file; within checkpoint files, sorted.
    assert ordered == [
        "restic/host/data/ab",
        "ckpt-00001.json",
        "ckpt-00002.json",
    ]
