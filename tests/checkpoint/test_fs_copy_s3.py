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
from uuid import uuid4

import pytest

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.util._checkpoint._host_egress import (
    MANIFEST_FILENAME,
    host_egress,
)
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
from inspect_ai.util._checkpoint._repo_ops import (
    fs_copy_repo,
    is_restic_repo_file,
)
from inspect_ai.util._checkpoint.hydrate import (
    _fs_copy_cross_cutting,
)

S3_BUCKET = "s3://test-bucket"

# Restic names every object by its sha256, so repo entries are 64 hex chars.
KEY_ID = "1" * 64
PACK_ID = "2" * 64
INDEX_ID = "3" * 64
SNAP_ID = "4" * 64


async def _fs_copy_repo(
    old_sample_dir: str, subpath: str, new_repo: str, *, label: str
) -> list[str]:
    """``fs_copy_repo`` with the restic layout predicate every restic caller passes."""
    return await fs_copy_repo(
        old_sample_dir, subpath, new_repo, label=label, accept=is_restic_repo_file
    )


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
        await _put(fs, f"{src_root}/restic/host/keys/{KEY_ID}", b"k")
        await _put(fs, f"{src_root}/restic/host/data/ab/{PACK_ID}", b"pack-data")
        await _put(fs, f"{src_root}/restic/host/index/{INDEX_ID}", b"idx")
        await _put(fs, f"{src_root}/restic/host/snapshots/{SNAP_ID}", b"snap")

        written = await _fs_copy_repo(
            src_root, "restic/host", str(new_repo), label="host"
        )

    assert set(written) == {
        "restic/host/config",
        f"restic/host/keys/{KEY_ID}",
        f"restic/host/data/ab/{PACK_ID}",
        f"restic/host/index/{INDEX_ID}",
        f"restic/host/snapshots/{SNAP_ID}",
    }
    assert (new_repo / "config").read_bytes() == b"cfg"
    assert (new_repo / "keys" / KEY_ID).read_bytes() == b"k"
    assert (new_repo / "data" / "ab" / PACK_ID).read_bytes() == b"pack-data"


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
    (src_host / "keys" / KEY_ID).write_bytes(b"k")
    (src_host / "data" / "ab" / PACK_ID).write_bytes(b"pack")

    new_repo = Path("new.checkpoints/s__0/restic/host")  # relative dest

    async with AsyncFilesystem():
        written = await _fs_copy_repo(
            src_root, "restic/host", str(new_repo), label="host"
        )

    assert set(written) == {
        "restic/host/config",
        f"restic/host/keys/{KEY_ID}",
        f"restic/host/data/ab/{PACK_ID}",
    }
    assert (new_repo / "config").read_bytes() == b"cfg"
    assert (new_repo / "keys" / KEY_ID).read_bytes() == b"k"
    assert (new_repo / "data" / "ab" / PACK_ID).read_bytes() == b"pack"


def _files_under(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "hostile_key, match",
    [
        pytest.param("restic/host/../../x", r"'\.\.' is not allowed", id="dotdot"),
        pytest.param("restic/host/./x", r"'\.' is not allowed", id="dot"),
        pytest.param("restic/host//etc/x", "absolute", id="double-slash-absolute"),
        pytest.param("restic/host/data/ab//x", "empty", id="double-slash-interior"),
        pytest.param(
            "restic/host/data/ab/../../keys/" + KEY_ID,
            r"'\.\.' is not allowed",
            id="dotdot-into-layout",
        ),
    ],
)
async def test_fs_copy_repo_refuses_uncontained_remote_keys(
    tmp_path: Path, mock_s3: None, hostile_key: str, match: str
) -> None:
    """Object-store keys are attacker-controlled; a bad one fails hydration.

    Each key is stored verbatim by S3 (moto included) and enumerated back
    verbatim by ``iter_files``. Without containment, ``..`` walks out of
    the new repo and a doubled slash makes the remainder absolute so
    ``Path`` discards the repo root entirely.
    """
    # The moto bucket outlives one parametrized case; keep each case's prefix apart.
    src_root = f"{S3_BUCKET}/hostile-{uuid4().hex}.checkpoints/s__0"
    staging = tmp_path / "staging"
    new_repo = staging / "restic" / "host"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src_root}/restic/host/config", b"cfg")
        await _put(fs, f"{src_root}/{hostile_key}", b"evil")

        with pytest.raises(RuntimeError, match=match) as excinfo:
            await _fs_copy_repo(src_root, "restic/host", str(new_repo), label="host")

    # The message names the offending source entry.
    assert hostile_key.split("/")[-1] in str(excinfo.value)
    # Nothing landed anywhere except (possibly) the legitimate `config`.
    assert _files_under(tmp_path) <= {Path("staging/restic/host/config")}
    assert not (tmp_path / "x").exists()
    assert not (tmp_path / "etc").exists()


async def test_fs_copy_repo_refuses_absolute_remainder_inside_tmp(
    tmp_path: Path, mock_s3: None
) -> None:
    """A doubled slash whose remainder points at a writable dir still can't land.

    Uses a remainder under ``tmp_path`` (writable, unlike ``/etc``) so the
    test would observe the escaped write if containment were missing.
    """
    src_root = f"{S3_BUCKET}/hostile-abs-{uuid4().hex}.checkpoints/s__0"
    new_repo = tmp_path / "staging" / "restic" / "host"
    escaped = tmp_path / "escaped"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src_root}/restic/host/config", b"cfg")
        await _put(fs, f"{src_root}/restic/host/{escaped}/x", b"evil")

        with pytest.raises(RuntimeError, match="absolute"):
            await _fs_copy_repo(src_root, "restic/host", str(new_repo), label="host")

    assert not escaped.exists()
    assert _files_under(tmp_path) <= {Path("staging/restic/host/config")}


async def test_fs_copy_repo_backstop_refuses_join_resolving_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolved-path backstop catches an escape the component checks can't see.

    On POSIX no contained relative path escapes by itself, so plant a
    symlink inside the new repo root pointing outside it: the join is
    contained textually but resolves elsewhere.
    """
    monkeypatch.chdir(tmp_path)
    src_root = "old.checkpoints/s__0"
    src_host = Path(src_root) / "restic" / "host"
    (src_host / "data" / "ab").mkdir(parents=True)
    (src_host / "config").write_bytes(b"cfg")
    (src_host / "data" / "ab" / PACK_ID).write_bytes(b"pack")

    new_repo = tmp_path / "new" / "restic" / "host"
    new_repo.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (new_repo / "data").symlink_to(outside, target_is_directory=True)

    async with AsyncFilesystem():
        with pytest.raises(RuntimeError, match="resolves outside"):
            await _fs_copy_repo(src_root, "restic/host", str(new_repo), label="host")

    assert _files_under(outside) == set()


async def test_fs_copy_repo_skips_entries_outside_layout_with_warning(
    tmp_path: Path, mock_s3: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Contained entries the layout predicate rejects are skipped, not fatal.

    A prior attempt killed mid-write leaves debris (restic's ``-tmp-``
    files) that the next attempt must resume past; a stray file is
    skipped the same way. Containment failures still raise (see above).
    """
    src_root = f"{S3_BUCKET}/debris-{uuid4().hex}.checkpoints/s__0"
    new_repo = tmp_path / "restic" / "host"
    debris = f"data/ab/{PACK_ID}-tmp-123456"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src_root}/restic/host/config", b"cfg")
        await _put(fs, f"{src_root}/restic/host/data/ab/{PACK_ID}", b"pack")
        await _put(fs, f"{src_root}/restic/host/{debris}", b"partial pack")
        await _put(fs, f"{src_root}/restic/host/evil.sh", b"#!/bin/sh")

        with caplog.at_level("WARNING", logger="inspect_ai"):
            written = await _fs_copy_repo(
                src_root, "restic/host", str(new_repo), label="host"
            )

    assert set(written) == {"restic/host/config", f"restic/host/data/ab/{PACK_ID}"}
    assert _files_under(new_repo) == {Path("config"), Path("data/ab") / PACK_ID}
    skipped = [
        r.getMessage() for r in caplog.records if "skipping host repo" in r.getMessage()
    ]
    assert len(skipped) == 2
    assert any(debris in m for m in skipped)
    assert any("evil.sh" in m for m in skipped)


async def test_fs_copy_repo_accept_predicate_scopes_copy_to_layout(
    tmp_path: Path, mock_s3: None
) -> None:
    """Each caller's ``accept`` decides what belongs; the restic one takes only restic files."""
    src_root = f"{S3_BUCKET}/scoped-{uuid4().hex}.checkpoints/s__0"
    new_repo = tmp_path / "restic" / "host"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src_root}/restic/host/config", b"cfg")
        await _put(fs, f"{src_root}/restic/host/locks/{SNAP_ID}", b"lock")
        await _put(fs, f"{src_root}/restic/host/keys/not-hex", b"k")

        written = await _fs_copy_repo(
            src_root, "restic/host", str(new_repo), label="host"
        )
        assert set(written) == {"restic/host/config", f"restic/host/locks/{SNAP_ID}"}
        assert not (new_repo / "keys" / "not-hex").exists()

        # A caller-supplied predicate can accept it instead.
        written = await fs_copy_repo(
            src_root,
            "restic/host",
            str(new_repo),
            label="host",
            accept=lambda rel: rel in {"config", "keys/not-hex", f"locks/{SNAP_ID}"},
        )

    assert set(written) == {
        "restic/host/config",
        f"restic/host/locks/{SNAP_ID}",
        "restic/host/keys/not-hex",
    }


async def test_fs_copy_repo_skips_directory_marker_objects(
    tmp_path: Path, mock_s3: None
) -> None:
    """Zero-byte ``.../`` keys (S3 console "Create folder") aren't files."""
    src_root = f"{S3_BUCKET}/markers-{uuid4().hex}.checkpoints/s__0"
    new_repo = tmp_path / "restic" / "host"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src_root}/restic/host/", b"")
        await _put(fs, f"{src_root}/restic/host/data/", b"")
        await _put(fs, f"{src_root}/restic/host/config", b"cfg")

        written = await _fs_copy_repo(
            src_root, "restic/host", str(new_repo), label="host"
        )

    assert written == ["restic/host/config"]
    assert _files_under(new_repo) == {Path("config")}


@pytest.mark.parametrize(
    "rel, expected",
    [
        ("config", True),
        (f"keys/{KEY_ID}", True),
        (f"data/ab/{PACK_ID}", True),
        (f"index/{INDEX_ID}", True),
        (f"snapshots/{SNAP_ID}", True),
        (f"locks/{SNAP_ID}", True),
        ("keys/key01", False),
        (f"data/{PACK_ID}", False),
        (f"data/abc/{PACK_ID}", False),
        (f"data/AB/{PACK_ID}", False),
        (f"snapshots/{SNAP_ID}x", False),
        ("config/x", False),
        ("evil.sh", False),
        ("../config", False),
        ("", False),
    ],
)
def test_is_restic_repo_file(rel: str, expected: bool) -> None:
    assert is_restic_repo_file(rel) is expected


async def test_fs_copy_cross_cutting_refuses_malformed_checkpoint_name(
    tmp_path: Path, mock_s3: None
) -> None:
    """A ``ckpt-*.json`` listing entry must be exactly ``ckpt-NNNNN.json``."""
    src = f"{S3_BUCKET}/bad-ckpt.checkpoints/s__0"
    new = tmp_path / "staging"
    new.mkdir()

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src}/ckpt-00001.json", b'{"checkpoint_id":1}')
        await _put(fs, f"{src}/ckpt-x.json", b"evil")

        with pytest.raises(RuntimeError, match="ckpt-x.json"):
            await _fs_copy_cross_cutting(src, str(new))

    assert not (new / "ckpt-x.json").exists()


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
        await _put(fs, f"{old_root}/restic/host/data/ab/{PACK_ID}", b"pack")
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
        assert (
            await fs.read_file(f"{new_root}/restic/host/data/ab/{PACK_ID}") == b"pack"
        )
        assert (
            await fs.read_file(f"{new_root}/restic/restic-config.json")
            == b'{"restic_password":"p"}'
        )

        # Manifest records the shipment.
        manifest_lines = (staging / MANIFEST_FILENAME).read_text().splitlines()
        assert set(manifest_lines) == {
            "restic/restic-config.json",
            "restic/host/config",
            f"restic/host/data/ab/{PACK_ID}",
            "ckpt-00001.json",
        }

        # Tamper with the destination to prove the next host_egress doesn't
        # re-ship already-manifested files.
        await fs.write_file(f"{new_root}/restic/host/config", b"untouched")

        await host_egress(staging_dir=str(staging), destination_dir=new_root)

        assert await fs.read_file(f"{new_root}/restic/host/config") == b"untouched"
