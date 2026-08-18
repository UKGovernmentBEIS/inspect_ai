"""Disk-backed attachment store for bounded-memory streaming recovery."""

from __future__ import annotations

import json as json_module
import os
import shutil
from collections.abc import Iterator, MutableMapping
from typing import IO


class StreamingAttachmentStore(MutableMapping[str, str]):
    """Dict-like store that writes each unique attachment to its own file.

    Subclasses `MutableMapping[str, str]` so it can be passed anywhere a
    mapping is expected (e.g. `condense_event`). In practice only
    `__setitem__` is exercised by the recovery pipeline; the other
    `MutableMapping` methods are provided for type-checker compatibility
    and read-back (e.g. `iter_items`).

    Every unique `(hash, content)` pair is written to
    `<dir>/<hash[:2]>/<hash[2:]>`. Duplicate writes for the same hash are
    no-ops. In-memory state is bounded to the set of seen hashes — neither
    content nor filenames are kept in memory beyond the hash set.
    """

    def __init__(self, dir: str) -> None:
        self._dir = dir
        os.makedirs(dir, exist_ok=True)
        self._seen: set[str] = set()

    def __setitem__(self, hash: str, content: str) -> None:
        if hash in self._seen:
            return
        self._seen.add(hash)
        prefix_dir = os.path.join(self._dir, hash[:2])
        os.makedirs(prefix_dir, exist_ok=True)
        with open(os.path.join(prefix_dir, hash[2:]), "wb") as f:
            f.write(content.encode("utf-8"))

    def __getitem__(self, hash: str) -> str:
        if hash not in self._seen:
            raise KeyError(hash)
        path = os.path.join(self._dir, hash[:2], hash[2:])
        with open(path, "rb") as f:
            return f.read().decode("utf-8")

    def __delitem__(self, hash: str) -> None:
        if hash not in self._seen:
            raise KeyError(hash)
        self._seen.discard(hash)
        path = os.path.join(self._dir, hash[:2], hash[2:])
        os.remove(path)

    def __iter__(self) -> Iterator[str]:
        return iter(self._seen)

    def __len__(self) -> int:
        return len(self._seen)

    def iter_items(self) -> Iterator[tuple[str, str]]:
        """Yield `(hash, content)` for every stored attachment.

        Order is unspecified (backed by `set` iteration).
        """
        for hash in self._seen:
            path = os.path.join(self._dir, hash[:2], hash[2:])
            with open(path, "rb") as f:
                yield hash, f.read().decode("utf-8")

    def close(self) -> None:
        """Remove the backing directory and all stored attachments."""
        shutil.rmtree(self._dir, ignore_errors=True)
        self._seen.clear()


def write_attachments_field(
    stream: IO[bytes],
    store: StreamingAttachmentStore,
    *,
    comma: bool,
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
