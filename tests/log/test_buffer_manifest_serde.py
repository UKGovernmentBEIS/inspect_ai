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
