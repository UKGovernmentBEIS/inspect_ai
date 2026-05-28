"""Roundtrip test for host egress against a moto-backed S3 sample checkpoints dir.

Exercises the real ``AsyncFilesystem`` S3 path end-to-end: restic-style
files written into a local staging dir, host egress ships them to
``s3://test-bucket/...``, then we read them back via
``AsyncFilesystem`` and verify shape + content.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.util._checkpoint._host_egress import MANIFEST_FILENAME, host_egress

S3_BUCKET = "s3://test-bucket"


def _write(p: Path, content: bytes = b"x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


async def test_host_egress_roundtrip_to_s3(tmp_path: Path, mock_s3: None) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "context").mkdir()
    # Restic-shape contents that span all tier buckets.
    _write(staging / "restic" / "host" / "config", b"host-config")
    _write(staging / "restic" / "host" / "keys" / "key01", b"host-key")
    _write(staging / "restic" / "host" / "data" / "ab" / "cdef", b"pack-data")
    _write(staging / "restic" / "host" / "index" / "11", b"idx")
    _write(staging / "restic" / "host" / "snapshots" / "22", b"snap")
    _write(staging / "restic" / "sandboxes" / "default" / "config", b"sb-config")
    _write(
        staging / "restic" / "sandboxes" / "default" / "data" / "ab" / "cd",
        b"sb-pack",
    )
    _write(staging / "restic" / "restic-config.json", b'{"restic_password":"pwd"}')
    _write(staging / "ckpt-00001.json", b'{"checkpoint_id":1}')
    # Should be excluded:
    _write(staging / "context" / "events.json", b"events")

    dest = f"{S3_BUCKET}/egress-roundtrip/eval.checkpoints/s__0"

    async with AsyncFilesystem() as fs:
        await host_egress(staging_dir=str(staging), destination_dir=dest)

        assert await fs.read_file(f"{dest}/restic/host/config") == b"host-config"
        assert await fs.read_file(f"{dest}/restic/host/keys/key01") == b"host-key"
        assert await fs.read_file(f"{dest}/restic/host/data/ab/cdef") == b"pack-data"
        assert await fs.read_file(f"{dest}/restic/host/index/11") == b"idx"
        assert await fs.read_file(f"{dest}/restic/host/snapshots/22") == b"snap"
        assert (
            await fs.read_file(f"{dest}/restic/sandboxes/default/config")
            == b"sb-config"
        )
        assert (
            await fs.read_file(f"{dest}/restic/sandboxes/default/data/ab/cd")
            == b"sb-pack"
        )
        assert (
            await fs.read_file(f"{dest}/restic/restic-config.json")
            == b'{"restic_password":"pwd"}'
        )
        assert await fs.read_file(f"{dest}/ckpt-00001.json") == b'{"checkpoint_id":1}'

        # Context subdir must not have been shipped.
        assert not await fs.exists(f"{dest}/context/events.json")
        assert not await fs.exists(f"{dest}/context")

    manifest = (staging / MANIFEST_FILENAME).read_text().splitlines()
    assert "context/events.json" not in manifest
    assert "ckpt-00001.json" in manifest


async def test_host_egress_second_cycle_only_ships_new(
    tmp_path: Path, mock_s3: None
) -> None:
    """Second egress on the same staging dir ships only newly-added files."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "context").mkdir()
    _write(staging / "restic" / "host" / "config", b"v1")
    _write(staging / "ckpt-00001.json", b"side1")
    dest = f"{S3_BUCKET}/egress-second/eval.checkpoints/s__0"

    async with AsyncFilesystem() as fs:
        await host_egress(staging_dir=str(staging), destination_dir=dest)

        # Sneak a marker into S3 at a path that already exists to prove
        # the second egress doesn't re-PUT it.
        await fs.write_file(f"{dest}/restic/host/config", b"untouched-after-egress")

        _write(staging / "restic" / "host" / "data" / "ab" / "cd", b"pack")
        _write(staging / "ckpt-00002.json", b"side2")
        await host_egress(staging_dir=str(staging), destination_dir=dest)

        assert (
            await fs.read_file(f"{dest}/restic/host/config")
            == b"untouched-after-egress"
        )
        assert await fs.read_file(f"{dest}/restic/host/data/ab/cd") == b"pack"
        assert await fs.read_file(f"{dest}/ckpt-00002.json") == b"side2"
