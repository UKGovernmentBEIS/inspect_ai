"""Tests for the resume-side FS-copy helpers.

Mostly against a moto-backed S3: ``_fs_copy_restic_config`` /
``_fs_copy_checkpoint_files`` and ``_fs_copy_repo`` downloading a
remote sample dir's contents into a local staging dir, plus the remote
resume flow (``copy_resume_payloads`` replicating the old attempt's
sample dirs into the new attempt's remote eval dir — s3 → s3 — and the
hydrate-time staging pull whose ``seed_manifest`` keeps the next
fire's egress from re-uploading the payload). Also covers
``_fs_copy_repo`` against a local relative source (the path form
eval-retry actually supplies).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.util._checkpoint._host_egress import (
    MANIFEST_FILENAME,
    host_egress,
    seed_manifest,
)
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
from inspect_ai.util._checkpoint._resume_copy import (
    _fs_copy_checkpoint_files,
    _fs_copy_repo,
    _fs_copy_restic_config,
    copy_payload_files,
    copy_resume_payloads,
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


async def test_fs_copy_config_and_checkpoint_files_download_from_s3(
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

        written = await _fs_copy_restic_config(src, str(new))
        written += await _fs_copy_checkpoint_files(src, str(new))

    # checkpoint files copy newest first: this copy is multi-write, and a
    # torn prefix must contain the latest checkpoint, not a stale one
    assert written == [
        "restic/restic-config.json",
        "ckpt-00002.json",
        "ckpt-00001.json",
    ]
    assert (
        new / "restic" / "restic-config.json"
    ).read_bytes() == b'{"restic_password":"the-pw"}'
    assert (new / "ckpt-00001.json").read_bytes() == b'{"checkpoint_id":1}'
    assert (new / "ckpt-00002.json").read_bytes() == b'{"checkpoint_id":2}'


async def test_fs_copy_config_and_checkpoint_files_noop_when_source_missing(
    tmp_path: Path, mock_s3: None
) -> None:
    """A source dir with no relevant files (fresh resume edge) returns []."""
    src = f"{S3_BUCKET}/empty-eval.checkpoints/s__0"
    new = tmp_path / "staging"
    new.mkdir()

    async with AsyncFilesystem():
        written = await _fs_copy_restic_config(src, str(new))
        written += await _fs_copy_checkpoint_files(src, str(new))

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


async def test_remote_resume_copies_payload_to_new_destination(
    tmp_path: Path, mock_s3: None
) -> None:
    """The remote resume flow: s3 → s3 startup copy, then the staging pull.

    Each retry attempt writes to its own remote eval dir (derived from
    its log location), so the startup copy replicates the prior
    attempt's sample dirs at the *new* destination before any sample
    runs. At sample start, hydrate pulls the payload from the
    destination into local staging and seeds the egress manifest so
    the next fire ships only its delta.
    """
    old_eval = f"{S3_BUCKET}/old.checkpoints"
    new_eval = f"{S3_BUCKET}/new.checkpoints"
    old_root = f"{old_eval}/s__0"
    new_root = f"{new_eval}/s__0"
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
        await _put(fs, f"{old_root}/restic/sandboxes/default/config", b"sb-cfg")
        await _put(fs, f"{old_root}/ckpt-00001.json", _checkpoint_bytes(1))

        # Startup copy: whole attempt, source → destination, both remote.
        await copy_resume_payloads(
            source_eval_dir=old_eval, destination_eval_dir=new_eval
        )

        # The new destination holds the full payload — resumable even if
        # this attempt never fires a checkpoint.
        assert await fs.read_file(f"{new_root}/ckpt-00001.json") == _checkpoint_bytes(1)
        assert await fs.read_file(f"{new_root}/restic/host/config") == b"cfg"
        assert await fs.read_file(f"{new_root}/restic/host/data/ab/cd") == b"pack"
        assert (
            await fs.read_file(f"{new_root}/restic/sandboxes/default/config")
            == b"sb-cfg"
        )
        assert (
            await fs.read_file(f"{new_root}/restic/restic-config.json")
            == b'{"restic_password":"p"}'
        )

        # Sample start: pull the destination's payload into staging and
        # seed the manifest (as hydrate does).
        downloaded = await copy_payload_files(new_root, str(staging))
        seed_manifest(str(staging), downloaded)

        assert (staging / "restic" / "host" / "config").read_bytes() == b"cfg"
        manifest_lines = (staging / MANIFEST_FILENAME).read_text().splitlines()
        assert set(manifest_lines) == {
            "restic/restic-config.json",
            "restic/host/config",
            "restic/host/data/ab/cd",
            "restic/sandboxes/default/config",
            "ckpt-00001.json",
        }

        # Tamper with the destination to prove the next host_egress doesn't
        # re-ship the seeded payload.
        await fs.write_file(f"{new_root}/restic/host/config", b"untouched")

        await host_egress(staging_dir=str(staging), destination_dir=new_root)

        assert await fs.read_file(f"{new_root}/restic/host/config") == b"untouched"
