"""A local, per-user cache of what log-dir reads parse from ``.eval`` logs.

With it, a poll of an unchanged directory costs the listing, and a changed
log costs only what changed. One JSON file per log URI (named by its
SHA-256) under ``inspect_data_dir("ctl")/log-dir-cache/``, created 0700,
holding:

- the plan: the header read from ``header.json`` or ``_journal/start.json``,
  used while the log's version is unchanged. Once the version changes the plan
  is read again through the new central directory, reusing a running log's
  start record while its CRC-32 is unchanged;
- the sample summaries of that version;
- for a running log, the journal summary members already parsed, keyed by
  member name, CRC-32 and compressed size, so a changed running log costs its
  central directory plus its new journal members.

An unchanged log's key set is its plan's recorded ids plus its cached
summaries' keys. Manifests, sample members and segments are not cached.

Every value is keyed by the version of the object it was read from, and is
written only from a read that passed its consistency checks, atomically
(temp file, then rename). So the cache changes how much a read fetches,
never what it returns: concurrent pollers may overwrite each other's
entries, and any entry that survives describes a real version of its log,
which a reader uses only while the log still has that version. An entry
that does not parse, or has another schema version, is discarded. Above
:data:`MAX_CACHE_BYTES`, the least recently used entries are removed.

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
from logging import getLogger
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.async_zip import AsyncZipReader, CentralDirectory
from inspect_ai._util.asyncfiles import is_s3_filename
from inspect_ai._util.atomic_write import atomic_write_bytes
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.discovery import DISCOVERY_DIR_MODE
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
        self._wrote = False

    def plan(self, file: LogFile) -> LogPlan | None:
        """The cached plan of ``file``, with the version it was read from.

        It describes the log only while the log still has that version; a
        caller that finds another version reads the plan again.
        """
        entry = self._entry(file)
        return _log_plan(file, entry) if entry is not None else None

    def snapshot(self, file: LogFile, version: str | None) -> MemberSnapshot | None:
        """The cached plan and summaries of ``file`` at ``version``, if held."""
        entry = self._entry(file)
        if (
            entry is None
            or entry.summaries is None
            or version is None
            or version != entry.plan.version
        ):
            return None
        return MemberSnapshot(
            plan=_log_plan(file, entry),
            summaries={SampleKey(str(s.id), s.epoch): s for s in entry.summaries},
        )

    def journal(self, file: LogFile) -> JournalCache:
        entry = self._entry(file)
        return JournalCache(entry.journal if entry is not None else {})

    def store_plan(self, plan: LogPlan) -> None:
        """Store a plan read and checked in this invocation.

        Keeps the cached summaries when they are of the plan's version, and
        the journal members its central directory still lists.
        """
        entry = self._entry(plan.file)
        same_version = (
            entry is not None
            and plan.version is not None
            and entry.plan.version == plan.version
        )
        self._store(
            plan,
            summaries=entry.summaries if entry is not None and same_version else None,
            journal=(
                _still_listed(entry.journal, plan.central_directory)
                if entry is not None
                else {}
            ),
        )

    def store_snapshot(self, snapshot: MemberSnapshot, journal: JournalCache) -> None:
        """Store a member view read and checked in this invocation.

        Keeps the journal members its central directory still lists.
        """
        plan = snapshot.plan
        self._store(
            plan,
            summaries=list(snapshot.summaries.values()),
            journal=journal.members(plan.central_directory),
        )

    def prune(self) -> None:
        """Remove the least recently used entries while the cache is too large.

        A no-op until this cache has written something.
        """
        if not self._wrote:
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

    def _entry(self, file: LogFile) -> _Entry | None:
        key = _cache_key(file.location)
        if key not in self._entries:
            self._entries[key] = self._load(key)
        return self._entries[key]

    def _load(self, key: str) -> _Entry | None:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as ex:
            logger.debug(f"could not read log-dir cache entry {path}: {ex}")
            return None
        try:
            entry = _Entry.model_validate_json(
                data, context=get_deserializing_context()
            )
            if entry.schema_version != SCHEMA_VERSION:
                raise ValueError(f"schema version {entry.schema_version}")
            if entry.location != key:
                raise ValueError(f"entry for {entry.location}")
        except ValueError as ex:
            logger.debug(f"discarding log-dir cache entry {path}: {ex}")
            with suppress(OSError):
                path.unlink(missing_ok=True)
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
        key = _cache_key(plan.file.location)
        entry = _Entry(
            schema_version=SCHEMA_VERSION,
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
        path = self._path(key)
        try:
            atomic_write_bytes(str(path), entry.model_dump_json().encode(), fsync=False)
        except OSError as ex:
            logger.debug(f"could not write log-dir cache entry {path}: {ex}")
            return
        self._entries[key] = entry
        self._wrote = True

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
    """Make the reads inside the block use ``cache``, then prune it."""
    token = _active_cache.set(cache)
    try:
        yield
    finally:
        _active_cache.reset(token)
        if cache is not None:
            cache.prune()


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


def _cache_key(location: str) -> str:
    """The URI an entry is keyed by: a local log's absolute path, else its URL."""
    if is_s3_filename(location) or not filesystem(location).is_local():
        return location
    return os.path.abspath(local_path(location))
