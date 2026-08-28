"""Encoding and legacy-compatibility guarantees for the buffer manifest."""

import json
import os
import tempfile

from inspect_ai.log._log import EvalSampleSummary
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
