"""Tests for StreamingAttachmentStore and write_attachments_field."""

import io
import json
import os
import tempfile
from pathlib import Path

from inspect_ai.log._recover._attachments import (
    StreamingAttachmentStore,
    write_attachments_field,
)


def test_store_confines_files_and_preserves_ids(tmp_path: Path) -> None:
    store_dir = tmp_path / "attachments"
    store = StreamingAttachmentStore(str(store_dir))
    outside = tmp_path / "photo"
    outside.write_bytes(b"original")
    ids = ["", "..", str(outside), "album/photo", r"album\photo"]
    expected = {key: f"photo {i}" for i, key in enumerate(ids)}
    store.update(expected)

    files = [p for p in store_dir.rglob("*") if p.is_file()]
    assert sorted(p.read_text() for p in files) == sorted(expected.values())
    assert dict(store.iter_items()) == expected
    for key, value in expected.items():
        assert store.pop(key) == value
    assert all(not p.exists() for p in files)
    store.close()
    assert outside.read_bytes() == b"original"


def test_store_dedups_by_hash() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = StreamingAttachmentStore(d)
        store["abcdef01"] = "hello"
        store["abcdef01"] = "SHOULD_BE_IGNORED"
        assert store["abcdef01"] == "hello"
        store.close()


def test_store_iter_items_yields_all_pairs() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = StreamingAttachmentStore(d)
        store["0011aabb"] = "first"
        store["ff22ccdd"] = "second"
        pairs = dict(store.iter_items())
        assert pairs == {"0011aabb": "first", "ff22ccdd": "second"}
        store.close()


def test_store_close_removes_dir() -> None:
    with tempfile.TemporaryDirectory() as parent:
        store_dir = os.path.join(parent, "store")
        store = StreamingAttachmentStore(store_dir)
        store["abcdef01"] = "hello"
        store.close()
        assert not os.path.exists(store_dir)


def test_store_handles_unicode_content() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = StreamingAttachmentStore(d)
        store["abcdef01"] = "héllo — world\n\ttab"
        pairs = dict(store.iter_items())
        assert pairs["abcdef01"] == "héllo — world\n\ttab"
        store.close()


def test_write_attachments_field_empty() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = StreamingAttachmentStore(d)
        buf = io.BytesIO()
        write_attachments_field(buf, store, comma=True)
        assert buf.getvalue() == b',"attachments":{}'
        store.close()


def test_write_attachments_field_single() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = StreamingAttachmentStore(d)
        store["abcdef01"] = "hello"
        buf = io.BytesIO()
        write_attachments_field(buf, store, comma=True)
        obj = json.loads(b"{" + buf.getvalue()[1:] + b"}")
        assert obj == {"attachments": {"abcdef01": "hello"}}
        store.close()


def test_write_attachments_field_multiple_and_escaping() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = StreamingAttachmentStore(d)
        store["00112233"] = 'quote" backslash\\ newline\n'
        store["aabbccdd"] = "plain"
        buf = io.BytesIO()
        write_attachments_field(buf, store, comma=True)
        obj = json.loads(b"{" + buf.getvalue()[1:] + b"}")
        assert obj["attachments"]["00112233"] == 'quote" backslash\\ newline\n'
        assert obj["attachments"]["aabbccdd"] == "plain"
        store.close()
