"""Encoding guarantees for the buffer manifest, which is rewritten every sync."""

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
    segment_cursor_ids,
)


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

    # Shape, not exact bytes: float formatting differs between serializers for
    # small magnitudes, so byte-equality would be brittle.
    assert b"\n" not in raw
    assert b'": ' not in raw


def test_write_manifest_round_trips() -> None:
    manifest = _manifest()
    raw, parsed = _round_trip(manifest)

    assert parsed is not None
    assert json.loads(raw) == json.loads(manifest.model_dump_json(exclude_none=True))


def test_legacy_segment_without_pool_ids_round_trips() -> None:
    """Around half of surviving buffer segments omit the pool ids entirely."""
    legacy = json.dumps(
        {
            "metrics": [],
            "samples": [
                {
                    "summary": {"id": "s1", "epoch": 1, "input": "i", "target": "t"},
                    "segments": [
                        {"id": 1, "last_event_id": 7, "last_attachment_id": 2}
                    ],
                }
            ],
            "segments": [{"id": 1, "last_event_id": 7, "last_attachment_id": 2}],
        }
    )

    parsed = Manifest.model_validate_json(legacy)
    segment = parsed.samples[0].segments[0]

    assert not isinstance(segment, int)
    # NotRequired, so nothing materializes the keys; the defaults live in
    # segment_cursor_ids and every consumer must go through it.
    assert "last_message_pool_id" not in segment
    assert segment_cursor_ids(segment) == (7, 2, 0, 0)


def test_legacy_bare_int_segment_entry_still_supported() -> None:
    """Manifests written before #4207 store a segment id in place of a cursor."""
    legacy = json.dumps(
        {
            "metrics": [],
            "samples": [
                {
                    "summary": {"id": "s1", "epoch": 1, "input": "i", "target": "t"},
                    "segments": [1],
                }
            ],
            "segments": [
                {
                    "id": 1,
                    "last_event_id": 7,
                    "last_attachment_id": 2,
                    "last_message_pool_id": 0,
                    "last_call_pool_id": 0,
                }
            ],
        }
    )

    parsed = Manifest.model_validate_json(legacy)

    assert parsed.samples[0].segments == [1]
