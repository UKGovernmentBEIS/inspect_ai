"""Tests for the resume-side FS-copy helpers.

Mostly against a moto-backed S3: ``_fs_copy_cross_cutting`` and
``_fs_copy_repo`` downloading a remote sample dir's contents into a
local staging dir, plus the hydrate-time ``host_egress`` that ships the
resume payload to the new attempt's destination (and records it so the
next fire's egress doesn't re-upload it). Also covers ``_fs_copy_repo``
against a local relative source (the path form eval-retry actually
supplies).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.util._checkpoint._host_egress import (
    MANIFEST_FILENAME,
    host_egress,
)
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
from inspect_ai.util._checkpoint.hydrate import (
    _fs_copy_cross_cutting,
    _fs_copy_repo,
)

S3_BUCKET = "s3://test-bucket"


async def _put(fs: AsyncFilesystem, uri: str, content: bytes) -> None:
    await fs.write_file(uri, content)


def _checkpoint_bytes(checkpoint_id: int) -> bytes:
    return (
        Checkpoint(
            checkpoint_id=checkpoint_id,
            trigger="turn",
            turn=checkpoint_id,
            created_at=datetime(2026, 5, 17, 18, 0, tzinfo=timezone.utc),
            duration_ms=10,
            size_bytes=100 + checkpoint_id,
            host=SnapshotDetails(
                snapshot_id=f"snap-{checkpoint_id}",
                size_bytes=100 + checkpoint_id,
                duration_ms=10,
            ),
            sandboxes={},
        )
        .model_dump_json()
        .encode()
    )


async def test_fs_copy_cross_cutting_downloads_from_s3(
    tmp_path: Path, mock_s3: None
) -> None:
    src = f"{S3_BUCKET}/old-eval.checkpoints/s__0"
    new = tmp_path / "staging"
    new.mkdir()

    async with AsyncFilesystem() as fs:
        await _put(
            fs,
            f"{src}/restic/restic-config.json",
            b'{"restic_password":"the-pw"}',
        )
        await _put(fs, f"{src}/ckpt-00001.json", b'{"checkpoint_id":1}')
        await _put(fs, f"{src}/ckpt-00002.json", b'{"checkpoint_id":2}')

        written = await _fs_copy_cross_cutting(src, str(new))

    assert set(written) == {
        "restic/restic-config.json",
        "ckpt-00001.json",
        "ckpt-00002.json",
    }
    assert (
        new / "restic" / "restic-config.json"
    ).read_bytes() == b'{"restic_password":"the-pw"}'
    assert (new / "ckpt-00001.json").read_bytes() == b'{"checkpoint_id":1}'
    assert (new / "ckpt-00002.json").read_bytes() == b'{"checkpoint_id":2}'


async def test_fs_copy_cross_cutting_noop_when_source_missing(
    tmp_path: Path, mock_s3: None
) -> None:
    """A source dir with no relevant files (fresh resume edge) returns []."""
    src = f"{S3_BUCKET}/empty-eval.checkpoints/s__0"
    new = tmp_path / "staging"
    new.mkdir()

    async with AsyncFilesystem():
        written = await _fs_copy_cross_cutting(src, str(new))

    assert written == []
    assert not (new / "restic").exists()


async def test_fs_copy_repo_downloads_tree_from_s3(
    tmp_path: Path, mock_s3: None
) -> None:
    src_root = f"{S3_BUCKET}/repo-tree.checkpoints/s__0"
    new_repo = tmp_path / "staging" / "restic" / "host"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src_root}/restic/host/config", b"cfg")
        await _put(fs, f"{src_root}/restic/host/keys/key01", b"k")
        await _put(fs, f"{src_root}/restic/host/data/ab/cdef", b"pack-data")
        await _put(fs, f"{src_root}/restic/host/index/11", b"idx")
        await _put(fs, f"{src_root}/restic/host/snapshots/22", b"snap")

        written = await _fs_copy_repo(
            src_root, "restic/host", str(new_repo), label="host"
        )

    assert set(written) == {
        "restic/host/config",
        "restic/host/keys/key01",
        "restic/host/data/ab/cdef",
        "restic/host/index/11",
        "restic/host/snapshots/22",
    }
    assert (new_repo / "config").read_bytes() == b"cfg"
    assert (new_repo / "keys" / "key01").read_bytes() == b"k"
    assert (new_repo / "data" / "ab" / "cdef").read_bytes() == b"pack-data"


async def test_fs_copy_repo_local_relative_source_lands_at_correct_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local source given as a *relative* path must relativize correctly.

    Regression: ``iter_files`` returns fsspec-normalized absolute paths for
    local sources, so slicing each URI by ``len(src_base)`` (which held only
    for S3, where the URI echoes ``src_base`` verbatim) cut at the wrong
    offset and produced mangled dest paths like
    ``<repo>/<eval-id-fragment>.checkpoints/.../config``. Resume (eval-retry)
    passes a relative ``logs/...`` source, so this is the real-world path.
    """
    monkeypatch.chdir(tmp_path)
    src_root = "old.checkpoints/s__0"  # relative, as eval-retry supplies
    src_host = Path(src_root) / "restic" / "host"
    (src_host / "keys").mkdir(parents=True)
    (src_host / "data" / "ab").mkdir(parents=True)
    (src_host / "config").write_bytes(b"cfg")
    (src_host / "keys" / "k1").write_bytes(b"k")
    (src_host / "data" / "ab" / "cd").write_bytes(b"pack")

    new_repo = Path("new.checkpoints/s__0/restic/host")  # relative dest

    async with AsyncFilesystem():
        written = await _fs_copy_repo(
            src_root, "restic/host", str(new_repo), label="host"
        )

    assert set(written) == {
        "restic/host/config",
        "restic/host/keys/k1",
        "restic/host/data/ab/cd",
    }
    assert (new_repo / "config").read_bytes() == b"cfg"
    assert (new_repo / "keys" / "k1").read_bytes() == b"k"
    assert (new_repo / "data" / "ab" / "cd").read_bytes() == b"pack"


async def test_fs_copy_repo_raises_when_source_missing(
    tmp_path: Path, mock_s3: None
) -> None:
    src_root = f"{S3_BUCKET}/repo-missing.checkpoints/s__0"
    new_repo = tmp_path / "staging" / "restic" / "host"

    async with AsyncFilesystem():
        try:
            await _fs_copy_repo(src_root, "restic/host", str(new_repo), label="host")
        except RuntimeError as e:
            assert "no files were found" in str(e)
        else:
            raise AssertionError("expected RuntimeError when source missing")


async def test_remote_resume_ships_payload_to_new_destination(
    tmp_path: Path, mock_s3: None
) -> None:
    """Hydrate-time host_egress makes the new attempt's dir resumable.

    Each retry attempt writes to its own remote sample dir (derived from
    its log location), so the payload downloaded from the *prior*
    attempt's dir must ship to the *new* destination at hydrate time —
    before any agent work runs. Otherwise a crash before the first
    post-resume fire leaves the new dir empty and the next retry (which
    looks only there) restarts the sample from scratch.
    """
    old_root = f"{S3_BUCKET}/old.checkpoints/s__0"
    new_root = f"{S3_BUCKET}/new.checkpoints/s__0"
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "context").mkdir()

    async with AsyncFilesystem() as fs:
        # The prior attempt's sample dir holds a complete subtree.
        await _put(
            fs, f"{old_root}/restic/restic-config.json", b'{"restic_password":"p"}'
        )
        await _put(fs, f"{old_root}/restic/host/config", b"cfg")
        await _put(fs, f"{old_root}/restic/host/data/ab/cd", b"pack")
        await _put(fs, f"{old_root}/ckpt-00001.json", _checkpoint_bytes(1))

        # Resume: download into a fresh local staging dir, then ship the
        # payload to the new attempt's destination (as hydrate does).
        await _fs_copy_cross_cutting(old_root, str(staging))
        await _fs_copy_repo(
            old_root, "restic/host", str(staging / "restic" / "host"), label="host"
        )
        await host_egress(staging_dir=str(staging), destination_dir=new_root)

        # The new destination holds the full payload — resumable even if
        # this attempt never fires another checkpoint.
        assert await fs.read_file(f"{new_root}/ckpt-00001.json") == _checkpoint_bytes(1)
        assert await fs.read_file(f"{new_root}/restic/host/config") == b"cfg"
        assert await fs.read_file(f"{new_root}/restic/host/data/ab/cd") == b"pack"
        assert (
            await fs.read_file(f"{new_root}/restic/restic-config.json")
            == b'{"restic_password":"p"}'
        )

        # Manifest records the shipment.
        manifest_lines = (staging / MANIFEST_FILENAME).read_text().splitlines()
        assert set(manifest_lines) == {
            "restic/restic-config.json",
            "restic/host/config",
            "restic/host/data/ab/cd",
            "ckpt-00001.json",
        }

        # Tamper with the destination to prove the next host_egress doesn't
        # re-ship already-manifested files.
        await fs.write_file(f"{new_root}/restic/host/config", b"untouched")

        await host_egress(staging_dir=str(staging), destination_dir=new_root)

        assert await fs.read_file(f"{new_root}/restic/host/config") == b"untouched"
