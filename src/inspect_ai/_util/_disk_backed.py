"""Disk-backed container classes using RocksDict.

Provides ``DiskBackedList`` and ``DiskBackedDict``: drop-in replacements for
Python lists and dicts that store data on disk via RocksDB, keeping memory
usage constant regardless of collection size.

These are activated by the ``--disk-backed`` CLI flag and are transparent to
the rest of the evaluation pipeline.
"""

import shutil
import tempfile
from collections.abc import Iterator
from typing import Generic, TypeVar, overload

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


def _require_rocksdict() -> type:
    """Import and return ``Rdict`` from *rocksdict*, raising a clear error if missing."""
    try:
        from rocksdict import Rdict

        return Rdict
    except ImportError:
        raise ImportError(
            "The 'rocksdict' package is required for --disk-backed mode. "
            "Install it with: pip install 'inspect_ai[disk-backed]'"
        ) from None


def _destroy_rdict(path: str) -> None:
    """Destroy a RocksDict database at *path*, falling back to shutil."""
    Rdict = _require_rocksdict()
    try:
        Rdict.destroy(path)  # type: ignore[attr-defined]
    except Exception:
        shutil.rmtree(path, ignore_errors=True)


class DiskBackedList(Generic[T]):
    """A list-like container backed by RocksDB for reduced memory usage.

    Items are serialised with pickle (the RocksDict default) and stored on
    disk.  Only items that are actively accessed reside in memory.

    Use as a context manager to ensure automatic cleanup::

        with DiskBackedList(items) as dbl:
            item = dbl[0]
            ...
    """

    def __init__(
        self, items: list[T] | None = None, *, path: str | None = None
    ) -> None:
        Rdict = _require_rocksdict()
        self._tmpdir = path or tempfile.mkdtemp(prefix="inspect_dbl_")
        self._owns_tmpdir = path is None
        self._db = Rdict(self._tmpdir)  # type: ignore[no-untyped-call]
        self._length: int = 0
        self._closed = False
        if items:
            for item in items:
                self.append(item)

    # -- sequence interface ---------------------------------------------------

    def __len__(self) -> int:
        return self._length

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        if isinstance(index, slice):
            indices = range(*index.indices(self._length))
            return [self._db[str(i)] for i in indices]
        if index < 0:
            index += self._length
        if index < 0 or index >= self._length:
            raise IndexError(f"DiskBackedList index {index} out of range")
        return self._db[str(index)]  # type: ignore[no-any-return]

    def __setitem__(self, index: int, value: T) -> None:
        if index < 0:
            index += self._length
        if index < 0 or index >= self._length:
            raise IndexError(f"DiskBackedList index {index} out of range")
        self._db[str(index)] = value

    def __delitem__(self, index: int) -> None:
        if index < 0:
            index += self._length
        if index < 0 or index >= self._length:
            raise IndexError(f"DiskBackedList index {index} out of range")
        del self._db[str(index)]

    def __iter__(self) -> Iterator[T]:
        for i in range(self._length):
            try:
                yield self._db[str(i)]
            except KeyError:
                continue

    def __contains__(self, value: object) -> bool:
        for item in self:
            if item == value:
                return True
        return False

    def append(self, item: T) -> None:
        """Append *item* to the end of the list."""
        self._db[str(self._length)] = item
        self._length += 1

    def extend(self, items: list[T]) -> None:
        """Extend the list by appending all *items*."""
        for item in items:
            self.append(item)

    def pop(self, index: int) -> T:
        """Remove and return the item at *index*.

        Unlike a regular list, this does **not** shift subsequent elements.
        Intended for use-then-discard patterns where order preservation of
        remaining items is not required.
        """
        value: T = self[index]
        del self._db[str(index if index >= 0 else index + self._length)]
        return value

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close the database and remove temporary files."""
        if self._closed:
            return
        self._closed = True
        self._db.close()
        if self._owns_tmpdir:
            _destroy_rdict(self._tmpdir)

    def __enter__(self) -> "DiskBackedList[T]":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class DiskBackedDict(Generic[K, V]):
    """A dict-like container backed by RocksDB for reduced memory usage.

    Keys are converted to strings for storage; values are pickled
    automatically by RocksDict.

    Use as a context manager to ensure automatic cleanup::

        with DiskBackedDict() as dbd:
            dbd["key"] = value
            ...
    """

    def __init__(self, *, path: str | None = None) -> None:
        Rdict = _require_rocksdict()
        self._tmpdir = path or tempfile.mkdtemp(prefix="inspect_dbd_")
        self._owns_tmpdir = path is None
        self._db = Rdict(self._tmpdir)  # type: ignore[no-untyped-call]
        self._keys: set[str] = set()
        self._closed = False

    # -- mapping interface ----------------------------------------------------

    def __setitem__(self, key: K, value: V) -> None:
        skey = str(key)
        self._db[skey] = value
        self._keys.add(skey)

    def __getitem__(self, key: K) -> V:
        skey = str(key)
        if skey not in self._keys:
            raise KeyError(key)
        return self._db[skey]  # type: ignore[no-any-return]

    def __delitem__(self, key: K) -> None:
        skey = str(key)
        if skey not in self._keys:
            raise KeyError(key)
        del self._db[skey]
        self._keys.discard(skey)

    def __contains__(self, key: object) -> bool:
        return str(key) in self._keys

    def __len__(self) -> int:
        return len(self._keys)

    def __iter__(self) -> Iterator[K]:
        # Keys are stored as strings; return them as-is (K is typically str | int)
        yield from self._keys  # type: ignore[misc]

    def get(self, key: K, default: V | None = None) -> V | None:
        """Return the value for *key*, or *default* if not present."""
        skey = str(key)
        if skey not in self._keys:
            return default
        return self._db[skey]  # type: ignore[no-any-return]

    def keys(self) -> set[str]:
        """Return a set of all keys."""
        return set(self._keys)

    def values(self) -> Iterator[V]:
        """Iterate over all values."""
        for skey in self._keys:
            yield self._db[skey]

    def items(self) -> Iterator[tuple[str, V]]:
        """Iterate over all (key, value) pairs."""
        for skey in self._keys:
            yield skey, self._db[skey]

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close the database and remove temporary files."""
        if self._closed:
            return
        self._closed = True
        self._db.close()
        if self._owns_tmpdir:
            _destroy_rdict(self._tmpdir)

    def __enter__(self) -> "DiskBackedDict[K, V]":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
