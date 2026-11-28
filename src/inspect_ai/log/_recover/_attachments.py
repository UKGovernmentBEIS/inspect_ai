"""Disk-backed attachment store for bounded-memory streaming recovery."""

from __future__ import annotations

import hashlib
import json as json_module
import os
import shutil
from collections.abc import Iterator, MutableMapping

from inspect_ai.log._recorders.json_write import BinaryWriteStream


class StreamingAttachmentStore(MutableMapping[str, str]):
    """Dict-like store that writes each unique attachment to its own file.

    Subclasses `MutableMapping[str, str]` so it can be passed anywhere a
    mapping is expected (e.g. `condense_event`). The recovery pipeline
    writes with `__setitem__` and resolves refs with `get`; the other
    `MutableMapping` methods are provided for type-checker compatibility
    and read-back (e.g. `iter_items`).

    Buffer-supplied attachment IDs are opaque keys. A digest of each ID
    names its backing file, so only generated hex digits enter the path.
    The store keeps just the original IDs in memory and ignores duplicate writes.
    """

    def __init__(self, dir: str) -> None:
        self._dir = dir
        os.makedirs(dir, exist_ok=True)
        self._seen: set[str] = set()

    def _path(self, hash: str) -> str:
        digest = hashlib.sha256(hash.encode("utf-8")).hexdigest()
        return os.path.join(self._dir, digest[:2], digest[2:])

    def __setitem__(self, hash: str, content: str) -> None:
        if hash in self._seen:
            return
        path = self._path(hash)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content.encode("utf-8"))
        self._seen.add(hash)

    def __getitem__(self, hash: str) -> str:
        if hash not in self._seen:
            raise KeyError(hash)
        with open(self._path(hash), "rb") as f:
            return f.read().decode("utf-8")

    def __delitem__(self, hash: str) -> None:
        if hash not in self._seen:
            raise KeyError(hash)
        os.remove(self._path(hash))
        self._seen.remove(hash)

    def __iter__(self) -> Iterator[str]:
        return iter(self._seen)

    def __len__(self) -> int:
        return len(self._seen)

    def iter_items(self) -> Iterator[tuple[str, str]]:
        """Yield `(hash, content)` for every stored attachment.

        Order is unspecified (backed by `set` iteration).
        """
        for hash in self._seen:
            yield hash, self[hash]

    def close(self) -> None:
        """Remove the backing directory and all stored attachments."""
        shutil.rmtree(self._dir, ignore_errors=True)
        self._seen.clear()


def write_attachments_field(
    stream: BinaryWriteStream,
    store: StreamingAttachmentStore,
    *,
    comma: bool = False,
) -> None:
    """Stream the `"attachments"` JSON field to `stream` from `store`.

    Emits `,"attachments":{"h1":"c1","h2":"c2",...}`. Holds at most one
    attachment's content in memory at a time.

    Args:
        stream: Writable binary stream.
        store: Attachment store to read from.
        comma: If True, prepend a comma separator.
    """
    if comma:
        stream.write(b',"attachments":{')
    else:
        stream.write(b'"attachments":{')
    first = True
    for hash, content in store.iter_items():
        if not first:
            stream.write(b",")
        stream.write(json_module.dumps(hash).encode("utf-8"))
        stream.write(b":")
        stream.write(json_module.dumps(content).encode("utf-8"))
        first = False
    stream.write(b"}")
