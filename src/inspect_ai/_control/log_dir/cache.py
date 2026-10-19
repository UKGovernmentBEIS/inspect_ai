"""A local, per-user cache of what log-dir reads parse from ``.eval`` logs.

With it, a poll of an unchanged finished log costs nothing beyond the
listing, and a poll of a running log costs its central directory plus the
journal members added since the last poll. One JSON file per log (named by
the SHA-256 of its key, see :func:`_cache_key`) under
``inspect_data_dir("ctl")/log-dir-cache/``, created 0700, holding the
Inspect version that parsed it and:

- the plan: the header read from ``header.json`` or ``_journal/start.json``.
  A finished log's plan is used while the log's version (S3 ETag, local
  stat) is unchanged. A running log's central directory is read on every
  poll, and its cached header is used only while ``_journal/start.json``
  keeps the CRC-32 it was read from;
- for a finished log, the sample summaries of that version;
- for a running log, the journal summary members already parsed, keyed by
  member name, CRC-32 and compressed size, checked against the fresh
  central directory.

Nothing keyed on a running log's version is reused. Manifests, sample
members and segments are not cached.

Entries are stored only from reads that passed their consistency checks and
written when the invocation ends (:meth:`LogDirCache.close`), at most once per
log, atomically (temp file, then rename) and owner-only (0600) into the existing
directory, which a write never creates. Concurrent pollers may overwrite each
other's entries, but every entry describes a real version of its log. An
entry of another schema or Inspect version is a cache miss. The first failure
to key, load, validate, serialize or write an entry turns the cache off for
the rest of the invocation: every later read is uncached, and nothing more is
loaded or written. Above :data:`MAX_CACHE_BYTES`, the least recently used
entries are removed.

Only local and S3 logs are cached (see :func:`_cache_key`).

The cache is active only inside :func:`use_cache`, as the CLI's reads are;
the reader functions consult :func:`active_cache`. See "Cache" in
``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from importlib.metadata import version as package_version
from logging import getLogger
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.async_zip import AsyncZipReader, CentralDirectory
from inspect_ai._util.asyncfiles import is_s3_filename
from inspect_ai._util.atomic_write import atomic_write_bytes
from inspect_ai._util.constants import PKG_NAME, get_deserializing_context
from inspect_ai._util.discovery import DISCOVERY_DIR_MODE, DISCOVERY_FILE_MODE
from inspect_ai._util.file import filesystem, local_path
from inspect_ai.log._log import EvalLog, EvalSampleSummary
from inspect_ai.log._recorders.eval import _read_journal_summaries

from .select import LogPlan, MemberSnapshot, SampleKey
from .walk import LogFile

logger = getLogger(__name__)

SCHEMA_VERSION = 1
"""The entry format; an entry with any other version is discarded."""

MAX_CACHE_BYTES = 256 * 1024 * 1024
"""Size above which the least recently used entries are removed."""

INSPECT_VERSION = package_version(PKG_NAME)
"""The Inspect version whose log models parse the cached values; an entry from
any other version is discarded, since its parser may have dropped or defaulted
fields this one reads."""


class _Plan(BaseModel):
    header: EvalLog
    finished: bool
    version: str | None
    """The log version ``header`` was read from."""

    header_crc: int | None


class _JournalMember(BaseModel):
    crc32: int
    compressed_size: int
    summaries: list[EvalSampleSummary]


class _Entry(BaseModel):
    # NaN and infinite scores and metrics round-trip, as in the log itself
    model_config = ConfigDict(ser_json_inf_nan="constants")

    schema_version: int
    inspect_version: str
    """The Inspect version that parsed the entry's values."""

    location: str
    """The log's cache key (see :func:`_cache_key`)."""

    plan: _Plan
    summaries: list[EvalSampleSummary] | None = None
    """The sample summaries of ``plan.version``, once read."""

    journal: dict[str, _JournalMember] = Field(default_factory=dict)
    """Parsed journal summary members, by member name."""


class JournalCache:
    """Journal summary members of one log, served from the cache when unchanged.

    Records every member it returns, so a read that succeeds can store them.
    """

    def __init__(self, cached: dict[str, _JournalMember]) -> None:
        self._cached = cached
        self._read: dict[str, _JournalMember] = {}

    async def read(self, reader: AsyncZipReader, path: str) -> list[EvalSampleSummary]:
        """The member's summaries; read only when its name, CRC-32 or size is new.

        Raises ``KeyError`` when the central directory has no such member.
        """
        entry = await reader.get_member_entry(path)
        cached = self._cached.get(path)
        if (
            cached is not None
            and cached.crc32 == entry.crc32
            and cached.compressed_size == entry.compressed_size
        ):
            self._read[path] = cached
            return cached.summaries
        summaries = await _read_journal_summaries(reader, path)
        if entry.crc32 is not None:
            self._read[path] = _JournalMember(
                crc32=entry.crc32,
                compressed_size=entry.compressed_size,
                summaries=summaries,
            )
        return summaries

    def members(self, cd: CentralDirectory | None) -> dict[str, _JournalMember]:
        """The members returned whose entries ``cd`` lists unchanged."""
        return _still_listed(self._read, cd)


class LogDirCache:
    """The cache directory, with the entries this invocation has loaded."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._entries: dict[str, _Entry | None] = {}
        self._unwritten: dict[str, _Entry] = {}
        self._wrote = False
        self._failed = False

    def finished_plan(self, file: LogFile) -> LogPlan | None:
        """The cached plan of a finished ``file``, with the version it was read from.

        It describes the log only while the log still has that version; a
        caller that finds another version reads the plan again.
        """
        entry = self._entry(file)
        if entry is None or not entry.plan.finished or entry.plan.version is None:
            return None
        return _log_plan(file, entry)

    def running_plan(self, file: LogFile) -> LogPlan | None:
        """The cached plan of a running ``file``.

        Its header may be reused only while ``_journal/start.json`` has the
        plan's ``header_crc``.
        """
        entry = self._entry(file)
        if entry is None or entry.plan.finished:
            return None
        return _log_plan(file, entry)

    def snapshot(self, plan: LogPlan) -> MemberSnapshot | None:
        """The cached summaries of a finished log at ``plan``'s version, if held."""
        entry = self._entry(plan.file)
        if (
            entry is None
            or entry.summaries is None
            or not entry.plan.finished
            or plan.version is None
            or plan.version != entry.plan.version
        ):
            return None
        return MemberSnapshot(
            plan=plan,
            summaries={SampleKey(str(s.id), s.epoch): s for s in entry.summaries},
        )

    def journal(self, file: LogFile) -> JournalCache:
        entry = self._entry(file)
        return JournalCache(entry.journal if entry is not None else {})

    def store_plan(self, plan: LogPlan) -> None:
        """Store a plan read and checked in this invocation, for :meth:`flush`.

        Keeps the cached journal members its central directory still lists.
        """
        entry = self._entry(plan.file)
        self._store(
            plan,
            summaries=None,
            journal=(
                _still_listed(entry.journal, plan.central_directory)
                if entry is not None
                else {}
            ),
        )

    def store_snapshot(self, snapshot: MemberSnapshot, journal: JournalCache) -> None:
        """Store a member view read and checked in this invocation, for :meth:`flush`.

        Keeps a finished log's summaries, and the journal members its central
        directory still lists.
        """
        plan = snapshot.plan
        self._store(
            plan,
            summaries=list(snapshot.summaries.values()) if plan.finished else None,
            journal=journal.members(plan.central_directory),
        )

    def flush(self) -> None:
        """Write the entries stored since the last flush, each once."""
        try:
            while self._unwritten:
                key, entry = self._unwritten.popitem()
                atomic_write_bytes(
                    str(self._path(key)),
                    entry.model_dump_json().encode(),
                    fsync=False,
                    mode=DISCOVERY_FILE_MODE,
                    make_parents=False,
                )
                self._wrote = True
        except Exception as ex:
            self._fail(ex)

    def close(self) -> None:
        """Write the stored entries and prune, once, when the invocation ends."""
        self.flush()
        self.prune()

    def prune(self) -> None:
        """Remove the least recently used entries while the cache is too large.

        A no-op until this cache has written something, or once it has failed.
        """
        if not self._wrote or self._failed:
            return
        self._wrote = False
        files: list[tuple[float, int, str]] = []
        try:
            with os.scandir(self.directory) as entries:
                for item in entries:
                    if item.is_file(follow_symlinks=False):
                        stat = item.stat(follow_symlinks=False)
                        files.append((stat.st_mtime, stat.st_size, item.path))
        except OSError as ex:
            logger.debug(f"not pruning the log-dir cache: {ex}")
            return
        total = sum(size for _, size, _ in files)
        for _, size, path in sorted(files):
            if total <= MAX_CACHE_BYTES:
                break
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as ex:
                logger.debug(f"could not prune {path}: {ex}")
                continue
            total -= size

    # Entries are disposable, so any failure to key, load, validate,
    # serialize or write one turns the cache off and logs are read instead.
    # The log model's validators alone can raise many exception types on bad
    # input, and a native path need not encode as UTF-8. Turning it off,
    # rather than missing on one key, leaves no state in which part of an
    # entry was refreshed and part was not.

    def _fail(self, ex: Exception) -> None:
        logger.debug(f"log-dir cache off for this invocation: {ex!r}")
        self._failed = True
        self._unwritten.clear()

    def _entry(self, file: LogFile) -> _Entry | None:
        if self._failed:
            return None
        try:
            key = _cache_key(file.location)
            if key is None:
                return None
            if key not in self._entries:
                self._entries[key] = self._load(key)
            return self._entries[key]
        except Exception as ex:
            self._fail(ex)
            return None

    def _load(self, key: str) -> _Entry | None:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            entry = _Entry.model_validate_json(
                data, context=get_deserializing_context()
            )
        except Exception:
            # it never will validate; removed, the next invocation rebuilds it
            with suppress(OSError):
                path.unlink()
            raise
        if (
            entry.schema_version != SCHEMA_VERSION
            or entry.inspect_version != INSPECT_VERSION
            or entry.location != key
        ):
            return None
        # the modification time records the last use, for pruning
        with suppress(OSError):
            os.utime(path)
        return entry

    def _store(
        self,
        plan: LogPlan,
        *,
        summaries: list[EvalSampleSummary] | None,
        journal: dict[str, _JournalMember],
    ) -> None:
        if self._failed:
            return
        try:
            key = _cache_key(plan.file.location)
            if key is None:
                return
            entry = _Entry(
                schema_version=SCHEMA_VERSION,
                inspect_version=INSPECT_VERSION,
                location=key,
                plan=_Plan(
                    header=plan.header,
                    finished=plan.finished,
                    version=plan.version,
                    header_crc=plan.header_crc,
                ),
                summaries=summaries,
                journal=journal,
            )
        except Exception as ex:
            self._fail(ex)
            return
        self._entries[key] = entry
        self._unwritten[key] = entry

    def _path(self, key: str) -> Path:
        return self.directory / f"{hashlib.sha256(key.encode()).hexdigest()}.json"


def open_cache() -> LogDirCache | None:
    """The user's cache, its directory created owner-only; ``None`` if it cannot be."""
    try:
        directory = inspect_data_dir("ctl") / "log-dir-cache"
        directory.mkdir(mode=DISCOVERY_DIR_MODE, exist_ok=True)
    except OSError as ex:
        logger.debug(f"log-dir cache disabled: {ex}")
        return None
    # some filesystems (FUSE, network mounts) ignore chmod; the directory is
    # under the user's data directory either way
    with suppress(OSError):
        directory.chmod(DISCOVERY_DIR_MODE)
    return LogDirCache(directory)


_active_cache: ContextVar[LogDirCache | None] = ContextVar(
    "log_dir_cache", default=None
)


def active_cache() -> LogDirCache | None:
    """The cache the current reads use, or ``None`` outside :func:`use_cache`."""
    return _active_cache.get()


@contextmanager
def use_cache(cache: LogDirCache | None) -> Iterator[None]:
    """Make the reads inside the block use ``cache``.

    Nothing is written here: an invocation may read in several blocks, and
    writes each entry once, from :meth:`LogDirCache.close`.
    """
    token = _active_cache.set(cache)
    try:
        yield
    finally:
        _active_cache.reset(token)


def _log_plan(file: LogFile, entry: _Entry) -> LogPlan:
    header = entry.plan.header
    header.location = file.location
    return LogPlan(
        file=file,
        central_directory=None,
        header=header,
        finished=entry.plan.finished,
        version=entry.plan.version,
        header_crc=entry.plan.header_crc,
    )


def _still_listed(
    members: dict[str, _JournalMember], cd: CentralDirectory | None
) -> dict[str, _JournalMember]:
    """The journal members whose entries ``cd`` lists with the same CRC-32 and size."""
    if cd is None:
        return {}
    listed: dict[str, _JournalMember] = {}
    for path, member in members.items():
        entry = cd.entry(path)
        if (
            entry is not None
            and entry.crc32 == member.crc32
            and entry.compressed_size == member.compressed_size
        ):
            listed[path] = member
    return listed


def _cache_key(location: str) -> str | None:
    """The key a log's entry is stored by; ``None`` when the log is not cached.

    An S3 log's URL, or a local log's absolute path. Only these backends have
    a version that names the log's content (the ETag; inode, mtime and
    size). Other backends' metadata can stay the same across a rewrite (an
    Azure log's version comes from its creation time and size), so nothing
    read from their logs is cached.
    """
    if is_s3_filename(location):
        return location
    if filesystem(location).is_local():
        return os.path.abspath(local_path(location))
    return None
