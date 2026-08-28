"""Serialization guarantees for the buffer manifest.

The manifest is rewritten on every `log_shared` sync and is machine-read only,
so its encoding is on the hot path of long runs.
"""

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
        eval_path = os.path.join(temp_dir, "log.eval")
        filestore = SampleBufferFilestore(eval_path)
        filestore.write_manifest(manifest)
        raw = open(filestore._manifest_file(), "rb").read()
        return raw, filestore.read_manifest()


def test_write_manifest_is_not_indented() -> None:
    """The manifest is machine-read only; indentation was ~41% of its bytes.

    Asserted on the shape rather than exact bytes: float formatting differs
    between serializers for small magnitudes, so byte-equality is brittle.
    """
    raw, _ = _round_trip(_manifest())

    assert b"\n" not in raw
    assert b'": ' not in raw


def test_write_manifest_round_trips() -> None:
    manifest = _manifest()
    raw, parsed = _round_trip(manifest)

    assert parsed is not None
    assert json.loads(raw) == json.loads(manifest.model_dump_json(exclude_none=True))
    assert parsed.samples[0].summary.id == "s1"


def test_legacy_segment_without_pool_ids_round_trips() -> None:
    """Manifests written before pool ids existed omit those keys entirely.

    49% of surviving prd buffer segments lack them, so the reader must keep
    defaulting them rather than requiring the keys to be present.
    """
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
    # The keys stay absent -- they are NotRequired, so nothing materializes
    # them. Consumers must go through segment_cursor_ids for the defaults.
    assert "last_message_pool_id" not in segment
    assert segment_cursor_ids(segment) == (7, 2, 0, 0)


def test_legacy_bare_int_segment_entry_still_supported() -> None:
    """Pre-#4207 manifests store a bare segment id, not a cursor object.

    ~800 of 906 sampled prd buffers are int-only, so the read path must keep
    resolving them against the top-level segment list.
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
