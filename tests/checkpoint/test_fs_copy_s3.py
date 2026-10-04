"""Tests for the resume-side payload copy against a moto-backed S3.

``copy_payload_files`` downloading a remote sample dir into a local
staging dir, the remote resume flow (``copy_resume_payloads``
replicating the old attempt's sample dirs into the new attempt's
remote eval dir — s3 → s3 — and the hydrate-time staging pull whose
``seed_manifest`` keeps the next fire's egress from re-uploading the
payload). Also covers ``copy_payload_files`` against a local relative
source (the path form eval-retry actually supplies).
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
    seed_manifest,
)
from inspect_ai.util._checkpoint._layout._paths import sample_dir_segment
from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    ensure_sample_checkpoints_dir,
    sample_checkpoints_dir,
    write_checkpoint_file,
)
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint, SnapshotDetails
from inspect_ai.util._checkpoint._resume_copy import (
    _SAMPLE_FILE_COPY_CONCURRENCY,
    copy_payload_files,
    copy_resume_payloads,
)
from inspect_ai.util._checkpoint.hydrate import _inherit_restic_config
from inspect_ai.util._checkpoint.resume import resolve_resume_checkpoint

S3_BUCKET = "s3://test-bucket"


async def _put(fs: AsyncFilesystem, uri: str, content: bytes) -> None:
    await fs.write_file(uri, content)


def _checkpoint(checkpoint_id: int) -> Checkpoint:
    return Checkpoint(
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


def _checkpoint_bytes(checkpoint_id: int) -> bytes:
    return _checkpoint(checkpoint_id).model_dump_json().encode()


async def test_copy_payload_files_downloads_from_s3(
    tmp_path: Path, mock_s3: None
) -> None:
    """The whole sample dir lands, including more checkpoints than the fan-out."""
    src = f"{S3_BUCKET}/old-eval.checkpoints/s__0"
    new = tmp_path / "staging"
    new.mkdir()
    checkpoint_ids = range(1, 2 * _SAMPLE_FILE_COPY_CONCURRENCY + 2)

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src}/restic/host/config", b"cfg")
        await _put(fs, f"{src}/restic/host/keys/key01", b"k")
        await _put(fs, f"{src}/restic/host/data/ab/cdef", b"pack-data")
        await _put(fs, f"{src}/restic/sandboxes/default/config", b"sb-cfg")
        await _put(fs, f"{src}/sandboxes/bulk/archive/ckpt-00001.tar.gz", b"tar")
        await _put(
            fs,
            f"{src}/restic/restic-config.json",
            b'{"restic_password":"the-pw"}',
        )
        await _put(
            fs,
            f"{src}/restic/snapshot-strategies.json",
            b'{"strategies":{"default":"archive"}}',
        )
        for n in checkpoint_ids:
            await _put(fs, f"{src}/ckpt-{n:05d}.json", _checkpoint_bytes(n))

        written = await copy_payload_files(src, str(new))

    assert set(written) == {
        "restic/host/config",
        "restic/host/keys/key01",
        "restic/host/data/ab/cdef",
        "restic/sandboxes/default/config",
        "sandboxes/bulk/archive/ckpt-00001.tar.gz",
        "restic/restic-config.json",
        "restic/snapshot-strategies.json",
    } | {f"ckpt-{n:05d}.json" for n in checkpoint_ids}
    assert (
        new / "restic" / "host" / "data" / "ab" / "cdef"
    ).read_bytes() == b"pack-data"
    assert (
        new / "sandboxes" / "bulk" / "archive" / "ckpt-00001.tar.gz"
    ).read_bytes() == b"tar"
    assert (
        new / "restic" / "snapshot-strategies.json"
    ).read_bytes() == b'{"strategies":{"default":"archive"}}'
    for n in checkpoint_ids:
        assert (new / f"ckpt-{n:05d}.json").read_bytes() == _checkpoint_bytes(n)


async def test_copy_payload_files_noop_when_source_missing(
    tmp_path: Path, mock_s3: None
) -> None:
    """A source dir with no files (fresh resume edge) copies nothing."""
    src = f"{S3_BUCKET}/empty-eval.checkpoints/s__0"
    new = tmp_path / "staging"
    new.mkdir()

    async with AsyncFilesystem():
        written = await copy_payload_files(src, str(new))

    assert written == []
    assert not any(new.iterdir())


async def test_copy_payload_files_local_relative_source_lands_at_correct_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local source given as a *relative* path must relativize correctly.

    Regression: ``iter_files`` returns fsspec-normalized absolute paths for
    local sources, so slicing each URI by the source's raw length (which
    held only for S3, where the URI echoes the source verbatim) cut at the
    wrong offset and produced mangled dest paths. Resume (eval-retry)
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

    new_root = Path("new.checkpoints/s__0")  # relative dest

    async with AsyncFilesystem():
        written = await copy_payload_files(src_root, str(new_root))

    assert set(written) == {
        "restic/host/config",
        "restic/host/keys/k1",
        "restic/host/data/ab/cd",
    }
    new_repo = new_root / "restic" / "host"
    assert (new_repo / "config").read_bytes() == b"cfg"
    assert (new_repo / "keys" / "k1").read_bytes() == b"k"
    assert (new_repo / "data" / "ab" / "cd").read_bytes() == b"pack"


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


async def test_inherit_restic_config_names_resume_source_when_corrupt(
    tmp_path: Path,
) -> None:
    """A copied restic-config.json that doesn't parse fails resume, naming the source.

    The adopted repos open only with the password that file carries, so
    continuing would just fail later with an opaque restic error; the
    error points at the resume source dir holding the bad file.
    """
    new = tmp_path / "staging"
    (new / "restic").mkdir(parents=True)
    (new / "restic" / "restic-config.json").write_bytes(b'{"not": "a config"}')

    with pytest.raises(
        RuntimeError, match=r"s3://bucket/old/s__0/restic/.*not a valid"
    ):
        await _inherit_restic_config(str(new), "s3://bucket/old/s__0")


# --- containment: untrusted listings cannot write outside the destination ----
#
# Object-store keys are arbitrary strings; a source prefix the eval reads
# back on retry may hold keys with `..` segments or a doubled slash, and
# a "directory" named `..`. Both copy entry points go through the same
# relativize/dir-name code, so each escape is refused before any copy.


def _assert_nothing_outside(dest: Path) -> None:
    """Nothing landed beside or above the destination dir."""
    parent = dest.parent
    assert [p.name for p in parent.iterdir() if p != dest] == []
    assert not (parent.parent / "escape").exists()
    assert not (parent.parent / "x__1").exists()


@pytest.mark.parametrize(
    "hostile_key, match",
    [
        ("restic/../../escape", r"'\.\.' is not allowed"),
        ("restic/host/../../../escape", r"'\.\.' is not allowed"),
        ("/abs/escape", "is absolute"),
        ("restic//host/config", "is empty"),
    ],
)
async def test_copy_payload_files_refuses_key_escaping_sample_dir(
    tmp_path: Path, mock_s3: None, hostile_key: str, match: str
) -> None:
    """A hostile key under the source sample dir fails the copy, and nothing is written.

    This is the path hydrate's staging pull takes on a remote destination
    (`copy_payload_files(remote sample dir, local staging dir)`).
    """
    # A prefix unique to this parametrization: the mocked bucket outlives a test.
    src = f"{S3_BUCKET}/{tmp_path.name}.checkpoints/s__0"
    dest = tmp_path / "eval.checkpoints" / "s__0"
    dest.mkdir(parents=True)

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src}/restic/host/config", b"cfg")
        await _put(fs, f"{src}/{hostile_key}", b"evil")
        with pytest.raises(ValueError, match=match):
            await copy_payload_files(src, str(dest))

    # Refused before the copy loop: not even the honest file landed.
    assert not any(dest.iterdir())
    _assert_nothing_outside(dest)


@pytest.mark.parametrize(
    "excluded_key",
    ["context/../../escape", "context//journal", "context/../x__1/ckpt-00001.json"],
)
async def test_copy_payload_files_ignores_hostile_key_under_excluded_dir(
    tmp_path: Path, mock_s3: None, excluded_key: str
) -> None:
    """A hostile key beneath the excluded `context/` dir is dropped, not fatal.

    Containment only guards paths that are joined onto the destination;
    `context/` is never copied, so an odd key under it must not fail the
    retry over an entry the copy would not have touched.
    """
    src = f"{S3_BUCKET}/{tmp_path.name}.checkpoints/s__0"
    dest = tmp_path / "eval.checkpoints" / "s__0"
    dest.mkdir(parents=True)

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{src}/restic/host/config", b"cfg")
        await _put(fs, f"{src}/context/state.json", b"{}")
        await _put(fs, f"{src}/{excluded_key}", b"evil")
        written = await copy_payload_files(src, str(dest))

    assert written == ["restic/host/config"]
    assert (dest / "restic" / "host" / "config").read_bytes() == b"cfg"
    assert not (dest / "context").exists()
    _assert_nothing_outside(dest)


@pytest.mark.parametrize(
    "hostile_dir,match",
    [
        # `<eval>/../x__1/...`: a "sample dir" named `..`.
        ("..", r"'\.\.' is not allowed"),
        # `<eval>//x__1/...`: S3 lists the CommonPrefix `<eval>//`, whose
        # terminal name is empty. Collapsing both slashes would turn that
        # into the eval dir's own name, which passes containment and then
        # copies nothing, silently.
        ("", "is empty"),
    ],
)
async def test_copy_resume_payloads_refuses_hostile_sample_dir_key(
    tmp_path: Path, mock_s3: None, hostile_dir: str, match: str
) -> None:
    """A source "sample dir" key that is not one component fails the startup copy before any file moves."""
    source_eval = f"{S3_BUCKET}/{tmp_path.name}.checkpoints"
    dest_eval = tmp_path / "root" / "new-eval.checkpoints"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{source_eval}/s__0/restic/host/config", b"cfg")
        await _put(
            fs,
            f"{source_eval}/{hostile_dir}/x__1/ckpt-00001.json",
            _checkpoint_bytes(1),
        )
        with pytest.raises(ValueError, match=match) as excinfo:
            await copy_resume_payloads(
                source_eval_dir=source_eval,
                destination_eval_dir=str(dest_eval),
            )

    # The error names the offending dir and the remedy: the startup copy
    # never skips silently, so this recurs on every retry until it is removed.
    assert f"sample dir name {hostile_dir!r}" in str(excinfo.value)
    assert "Remove that directory" in str(excinfo.value)
    assert not (dest_eval / "s__0").exists()
    _assert_nothing_outside(dest_eval)


async def test_copy_resume_payloads_refuses_local_sample_dir_with_backslash(
    tmp_path: Path,
) -> None:
    """A local sample dir named with a backslash (legal on Linux) fails the startup copy.

    `basename` flips backslashes to slashes before taking the last segment,
    which would hide the separator from containment and report a name the
    source does not have; the copy takes the terminal name itself.
    """
    source_eval = tmp_path / "old-eval.checkpoints"
    dest_eval = tmp_path / "root" / "new-eval.checkpoints"
    hostile = source_eval / "a\\b__0"
    hostile.mkdir(parents=True)
    (hostile / "ckpt-00001.json").write_bytes(_checkpoint_bytes(1))

    with pytest.raises(ValueError, match="contains a separator") as excinfo:
        await copy_resume_payloads(
            source_eval_dir=str(source_eval),
            destination_eval_dir=str(dest_eval),
        )

    assert "sample dir name 'a\\\\b__0'" in str(excinfo.value)
    assert not any(dest_eval.iterdir())
    _assert_nothing_outside(dest_eval)


async def test_hashed_sample_dir_round_trips_through_s3(
    tmp_path: Path, mock_s3: None
) -> None:
    """A hashed (``~``-joined) sample dir name works end to end on S3.

    ``~`` is on AWS's "characters to avoid" list for object keys, so
    prove the write path, the resume lookup and the startup copy agree
    on a hashed segment through the real S3 client rather than only on
    the string they compute.
    """
    old_eval = f"{S3_BUCKET}/hashed-{uuid4().hex}.checkpoints"
    new_eval = f"{S3_BUCKET}/hashed-{uuid4().hex}.checkpoints"
    sample_id = "task/variant-3"
    segment = f"{sample_dir_segment(sample_id)}__0"
    assert "~" in segment

    async with AsyncFilesystem() as fs:
        sample_dir = await ensure_sample_checkpoints_dir(old_eval, sample_id, 0)
        assert sample_dir == f"{old_eval}/{segment}"
        assert sample_dir == sample_checkpoints_dir(old_eval, sample_id, 0)
        assert await resolve_resume_checkpoint(old_eval, sample_id, 0) is None

        await write_checkpoint_file(
            sample_checkpoints_dir=sample_dir, checkpoint=_checkpoint(1)
        )
        await _put(fs, f"{sample_dir}/restic/host/config", b"cfg")
        resume = await resolve_resume_checkpoint(old_eval, sample_id, 0)
        assert resume is not None and resume.attempt == "resume"

        await copy_resume_payloads(
            source_eval_dir=old_eval, destination_eval_dir=new_eval
        )

        new_sample_dir = f"{new_eval}/{segment}"
        copied = Checkpoint.model_validate_json(
            await fs.read_file(f"{new_sample_dir}/ckpt-00001.json")
        )
        assert copied.checkpoint_id == 1
        assert await fs.read_file(f"{new_sample_dir}/restic/host/config") == b"cfg"
        resume = await resolve_resume_checkpoint(new_eval, sample_id, 0)
        assert resume is not None and resume.attempt == "resume"


async def test_copy_resume_payloads_file_uri_destination_writes_validated_names(
    tmp_path: Path, mock_s3: None
) -> None:
    """A ``file://`` destination receives the validated strings, not decoded ones.

    The local copy sink resolves ``file://`` URIs with ``local_path``,
    which percent-decodes, so ``%2e%2e`` (a legal, contained key segment)
    joined onto a ``file://`` URI would reach the OS as ``..``. The copy
    resolves both sides to plain paths before any name is joined.
    """
    source_eval = f"{S3_BUCKET}/{tmp_path.name}.checkpoints"
    dest_eval = tmp_path / "root" / "new-eval.checkpoints"

    async with AsyncFilesystem() as fs:
        await _put(fs, f"{source_eval}/s__0/restic/host/config", b"cfg")
        await _put(fs, f"{source_eval}/s__0/%2e%2e/%2e%2e/%2e%2e/escape", b"evil")
        await _put(
            fs, f"{source_eval}/%2e%2e/x__1/ckpt-00001.json", _checkpoint_bytes(1)
        )
        await copy_resume_payloads(
            source_eval_dir=source_eval,
            destination_eval_dir=dest_eval.as_uri(),
        )

    assert (dest_eval / "s__0" / "restic" / "host" / "config").read_bytes() == b"cfg"
    literal = dest_eval / "s__0" / "%2e%2e" / "%2e%2e" / "%2e%2e" / "escape"
    assert literal.read_bytes() == b"evil"
    assert (dest_eval / "%2e%2e" / "x__1" / "ckpt-00001.json").exists()
    _assert_nothing_outside(dest_eval)


async def test_copy_payload_files_file_uri_source_reads_listed_names(
    tmp_path: Path,
) -> None:
    """A ``file://`` source is read at the names the listing produced.

    Without resolving the URI first, the sink would percent-decode a
    literal ``%2e%2e`` directory in the source path and read its parent.
    """
    source = tmp_path / "old.checkpoints" / "s__0"
    (source / "restic" / "%2e%2e").mkdir(parents=True)
    (source / "restic" / "%2e%2e" / "config").write_bytes(b"cfg")
    dest = tmp_path / "new.checkpoints" / "s__0"

    async with AsyncFilesystem():
        written = await copy_payload_files(source.as_uri(), dest.as_uri())

    assert written == ["restic/%2e%2e/config"]
    assert (dest / "restic" / "%2e%2e" / "config").read_bytes() == b"cfg"
