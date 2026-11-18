"""Encoding and legacy-compatibility guarantees for the buffer manifest."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import filestore as filestore_module
from inspect_ai.log._recorders.buffer.filestore import (
    Manifest,
    SampleBufferFilestore,
    SampleManifest,
    SampleSegment,
    Segment,
)

POOL_KEYS = {"last_message_pool_id", "last_call_pool_id"}


def _manifest() -> Manifest:
    return Manifest(
        metrics=[],
        samples=[
            SampleManifest(
                summary=EvalSampleSummary(id="s1", epoch=1, input="i", target="t"),
                segments=[SampleSegment(id=1, last_event_id=7, last_attachment_id=2)],
            )
        ],
        segments=[Segment(id=1, last_event_id=7, last_attachment_id=2)],
    )


def _round_trip(manifest: Manifest) -> tuple[bytes, Manifest | None]:
    with tempfile.TemporaryDirectory() as temp_dir:
        filestore = SampleBufferFilestore(os.path.join(temp_dir, "log.eval"))
        filestore.write_manifest(manifest)
        with open(filestore._manifest_file(), "rb") as f:
            return f.read(), filestore.read_manifest()


def test_write_manifest_is_not_indented() -> None:
    raw, _ = _round_trip(_manifest())

    assert b"\n" not in raw
    assert b'": ' not in raw


def test_write_manifest_round_trips() -> None:
    manifest = _manifest()
    _, parsed = _round_trip(manifest)

    assert parsed == manifest


def test_read_persisted_sidecars_with_numeric_sample_id(tmp_path: Path) -> None:
    directory = tmp_path / ".buffer" / "log"
    directory.mkdir(parents=True)
    # The persisted key hashes the indented JSON array of string id and epoch.
    sample_key = hashlib.sha256(b'[\n  "1",\n  1\n]').hexdigest()
    metadata = b'{"source":"dataset"}'
    store = b'{"step":2}'
    metadata_hash = hashlib.sha256(metadata).hexdigest()
    store_hash = hashlib.sha256(store).hexdigest()
    (directory / f"metadata.{sample_key}.{metadata_hash}.json").write_bytes(metadata)
    (directory / f"store.{sample_key}.{store_hash}.json").write_bytes(store)
    sample = {
        "summary": {"id": 1, "epoch": 1, "input": "i", "target": "t"},
        "metadata_hash": metadata_hash,
        "store_hash": store_hash,
    }
    (directory / "manifest.json").write_text(json.dumps({"samples": [sample]}))

    filestore = SampleBufferFilestore(str(tmp_path / "log.eval"), create=False)
    assert filestore.get_sample_metadata(1, 1) == {"source": "dataset"}
    assert filestore.get_sample_store("1", 1) == {"step": 2}


@pytest.mark.parametrize(
    "invalid_hash",
    ["nested/name", r"nested\name", "a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n"],
)
def test_invalid_sidecar_hash_skips_file_read(
    invalid_hash: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    filestore = SampleBufferFilestore(str(tmp_path / "log.eval"))
    manifest = _manifest()
    manifest.samples[0].metadata_hash = invalid_hash
    manifest.samples[0].store_hash = invalid_hash
    filestore.write_manifest(manifest)
    persisted = filestore.read_manifest()
    assert persisted is not None

    def unexpected_open(path: str, mode: str) -> None:
        pytest.fail(f"Attempted to open a sidecar with an invalid hash: {path!r}")

    monkeypatch.setattr(filestore_module, "open_file", unexpected_open)
    assert filestore.read_sample_metadata("s1", 1, persisted) is None
    assert "Unable to read sample metadata for id=s1 epoch=1" in caplog.text
    assert filestore.read_sample_store("s1", 1, persisted) is None
    assert "Unable to read sample store for id=s1 epoch=1" in caplog.text


def test_invalid_sidecar_hash_rejected_on_write(tmp_path: Path) -> None:
    filestore = SampleBufferFilestore(str(tmp_path / "log.eval"))

    with pytest.raises(ValueError, match="Invalid SHA-256 digest for sample metadata"):
        filestore.write_sample_metadata("s1", 1, "invalid", b"{}")
    with pytest.raises(ValueError, match="Invalid SHA-256 digest for sample store"):
        filestore.write_sample_store("s1", 1, "invalid", b"{}")
    assert not list(tmp_path.rglob("*.json"))


def test_legacy_manifest_regains_pool_ids_on_rewrite() -> None:
    """A pre-#3681 manifest omits the pool ids; validation fills them.

    Segments predating #3681 have no pool-id keys, and per-sample entries
    predating #4207 are a bare segment id. Both must keep loading, and the
    rewrite must restore the keys rather than propagating the legacy shape --
    otherwise a reader indexing them directly breaks on a file we just wrote.
    """
    legacy = json.dumps(
        {
            "metrics": [],
            "samples": [
                {
                    "summary": {"id": "s1", "epoch": 1, "input": "i", "target": "t"},
                    "segments": [1],
                }
            ],
            "segments": [{"id": 1, "last_event_id": 7, "last_attachment_id": 2}],
        }
    )

    parsed = Manifest.model_validate_json(legacy)

    assert parsed.samples[0].segments == [1]
    assert parsed.segments[0]["last_message_pool_id"] == 0

    raw, _ = _round_trip(parsed)

    assert POOL_KEYS <= json.loads(raw)["segments"][0].keys()
