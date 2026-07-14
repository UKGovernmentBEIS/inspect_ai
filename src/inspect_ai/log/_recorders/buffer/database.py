import datetime
import hashlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Sequence
from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from sqlite3 import Connection, OperationalError
from typing import TYPE_CHECKING, Callable, Iterable, Iterator, Literal, cast

import psutil
from pydantic import BaseModel, JsonValue
from shortuuid import uuid
from typing_extensions import override

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.dateutil import is_file_older_than
from inspect_ai._util.file import (
    basename,
    dirname,
    filesystem,
)
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.trace import trace_action
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool import (
    _call_pool_json,
    _compress_refs,
    _msg_pool_json,
    _msg_pool_jsonable,
)
from inspect_ai.event._pool_index import (
    CallPoolIndex,
    MessagePoolIndex,
    condense_model_event_with_indices,
)
from inspect_ai.log._recorders.buffer.history import SampleHistory
from inspect_ai.model import ChatMessage

from ..._condense import (
    ATTACHMENT_PROTOCOL,
    WalkContext,
    attachments_content_fn,
    walk_chat_message,
    walk_events,
    walk_input,
    walk_json_dict,
    walk_json_value,
)
from ..._log import EvalSampleSummary
from ..types import SampleEvent
from .filestore import (
    Manifest,
    SampleBufferFilestore,
    SampleManifest,
    SampleSegment,
    Segment,
    SegmentFile,
    sample_segment_cursor,
)
from .types import (
    AttachmentData,
    CallPoolData,
    EventData,
    JsonData,
    MessagePoolData,
    SampleBuffer,
    SampleData,
    Samples,
)

logger = getLogger(__name__)
SYNC_CLEANUP_TIMEOUT = 30

if TYPE_CHECKING:
    from .types import TranscriptEventSink


class TaskData(BaseModel):
    version: int
    metrics: list[TaskDisplayMetric]


class SampleBufferDatabase(SampleBuffer):
    SCHEMA = """

    CREATE TABLE IF NOT EXISTS task_database (
        version INTEGER PRIMARY KEY DEFAULT 1,
        metrics TEXT DEFAULT '[]',
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE samples (
        id TEXT,
        epoch INTEGER,
        data TEXT, -- JSON containing all other sample fields
        PRIMARY KEY (id, epoch)
    );

    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        sample_id TEXT,
        sample_epoch INTEGER,
        data TEXT -- JSON containing full event
    );

    CREATE INDEX IF NOT EXISTS idx_events_sample_uuid
        ON events(sample_id, sample_epoch, event_id, id);

    CREATE TABLE attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id TEXT,
        sample_epoch INTEGER,
        hash TEXT,
        content TEXT,
        UNIQUE(sample_id, sample_epoch, hash)
    );

    CREATE TABLE message_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id TEXT,
        sample_epoch INTEGER,
        msg_id TEXT,
        data TEXT,
        UNIQUE(sample_id, sample_epoch, msg_id)
    );

    CREATE TABLE call_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id TEXT,
        sample_epoch INTEGER,
        hash TEXT,
        data TEXT,
        UNIQUE(sample_id, sample_epoch, hash)
    );

    -- Indices for foreign keys and common queries
    CREATE INDEX IF NOT EXISTS idx_events_sample ON events(sample_id, sample_epoch);
    CREATE INDEX IF NOT EXISTS idx_attachments_hash ON attachments(hash);

    -- Note the version
    INSERT INTO task_database (version) VALUES (1);
    """

    def __init__(
        self,
        location: str,
        *,
        create: bool = True,
        read_only: bool = False,
        log_images: bool = True,
        log_shared: int | None = None,
        update_interval: int = 2,
        db_dir: Path | None = None,
    ):
        """Open (or create) the sample buffer database for ``location``.

        Args:
            location: Eval log location the buffer belongs to.
            create: Create the database (and schema) if it doesn't exist.
            read_only: Open connections with SQLite ``mode=ro``. A read-only
                connection can never (re-)create the database file, so a
                reader racing the buffer's deletion (eval teardown, stale
                sweep) fails with ``OperationalError`` instead of leaving an
                empty database behind that makes the task look running.
                Incompatible with ``create``.
            log_images: Log image attachments.
            log_shared: Sync interval for shared log directories.
            update_interval: Version update interval.
            db_dir: Override the database directory (defaults to the
                inspect data dir).
        """
        if create and read_only:
            raise ValueError("read_only is incompatible with create")
        self.location = filesystem(location).path_as_uri(location)
        self._read_only = read_only
        self.log_images = log_images
        self.log_shared = log_shared
        self.update_interval = update_interval

        # warn at most once per database if WAL journal mode can't be enabled
        self._wal_checked = False

        # Persistent per-thread SQLite connections. Each thread reuses one
        # connection across operations instead of opening/closing per call
        # (a large throughput win, especially under WAL). Connections are
        # tracked so they can all be closed at cleanup. Initialized before the
        # schema-creation _get_connection() call below.
        #
        # Safety rests on two invariants (see _get_connection): (a) all writes
        # and explicit-transaction reads run on the single anyio event-loop
        # thread; the only other DB-touching thread is the read-only filestore
        # sync worker, so no two threads ever touch the same connection
        # concurrently. (b) _get_connection() bodies are await-free, so no other
        # task can interleave a statement onto the shared connection mid-txn.
        # check_same_thread=False is set purely so cleanup can close a (dead)
        # thread's handle, not to enable concurrent use.
        self._local = threading.local()
        self._connections: list[Connection] = []
        self._connections_lock = threading.Lock()
        self._closed = False

        # location subdir and file
        dir, file = location_dir_and_file(self.location)

        # establish dirs
        db_dir = resolve_db_dir(db_dir)
        log_subdir = db_dir / dir

        # if we are creating then create dirs, use filename w/pid,
        # and create the database as required
        if create:
            log_subdir.mkdir(parents=True, exist_ok=True)
            self.db_path = log_subdir / f"{file}.{os.getpid()}.db"

            # initialize the database schema
            with self._get_connection() as conn:
                conn.executescript(self.SCHEMA)
                conn.commit()

        # if we are not creating then find a log in an existing directory
        # which matches the base filename (it will also have a pid)
        else:
            logs = list(log_subdir.glob(f"{file}.*.db"))
            if len(logs) > 0:
                self.db_path = logs[0]
            else:
                raise FileNotFoundError(f"Log database for '{location}' not found.")

        # Per-sample pool indices; full pool entries live in SQLite.
        self._msg_indices: dict[tuple[str, int], MessagePoolIndex] = {}
        self._call_indices: dict[tuple[str, int], CallPoolIndex] = {}

        # Prevent late ModelEvents from restarting indices at 0 after completion.
        self._completed_samples: set[tuple[str, int]] = set()

        self._sample_read_leases: dict[tuple[str, int], int] = {}
        self._pending_sample_removals: set[tuple[str, int]] = set()
        self._cleanup_pending = False
        self._lease_lock = threading.Lock()

        # create sync filestore if log_shared
        self._sync_filestore = (
            SampleBufferFilestore(location, update_interval=log_shared)
            if log_shared
            else None
        )
        self._sync_time = time.monotonic()
        self._sync_lock = threading.Lock()
        self._sync_wakeup = threading.Condition(self._sync_lock)
        self._sync_thread: threading.Thread | None = None
        self._sync_pending = False
        self._sync_closed = False
        self._sync_requested = False

    def start_sample(self, sample: EvalSampleSummary) -> None:
        with self._get_connection(write=True) as conn:
            sample = self._condense_sample(conn, sample)
            conn.execute(
                """
                INSERT INTO samples (id, epoch, data)
                VALUES (?, ?, ?)
            """,
                (str(sample.id), sample.epoch, to_json_str_safe(sample)),
            )

    def log_events(self, events: list[SampleEvent]) -> None:
        # `None` mark = the index didn't exist before this batch (pop on restore)
        index_snapshots: dict[tuple[str, int], tuple[int | None, int | None]] = {}

        def restore_index_snapshots() -> None:
            for key, (msg_mark, call_mark) in index_snapshots.items():
                if msg_mark is None:
                    self._msg_indices.pop(key, None)
                else:
                    msg_index = self._msg_indices.get(key)
                    if msg_index is not None:
                        msg_index.restore(msg_mark)

                if call_mark is None:
                    self._call_indices.pop(key, None)
                else:
                    call_index = self._call_indices.get(key)
                    if call_index is not None:
                        call_index.restore(call_mark)

        with self._get_connection(
            write=True, on_rollback=restore_index_snapshots
        ) as conn:
            # collect the values for all events
            values: list[str | int] = []
            for event in events:
                if isinstance(event.event, ModelEvent):
                    key = (str(event.id), event.epoch)
                    if key not in index_snapshots:
                        msg_index = self._msg_indices.get(key)
                        call_index = self._call_indices.get(key)
                        index_snapshots[key] = (
                            None if msg_index is None else msg_index.mark(),
                            None if call_index is None else call_index.mark(),
                        )

                event = self._condense_event(conn, event)
                values.extend(
                    (
                        event.event.uuid or uuid(),
                        str(event.id),
                        event.epoch,
                        to_json_str_safe(event.event),
                    )
                )

            # dynamically create the SQL query
            placeholders = ", ".join(["(?, ?, ?, ?)"] * len(events))
            sql = f"""
            INSERT INTO events (event_id, sample_id, sample_epoch, data)
            VALUES {placeholders}
            """

            # Insert all rows
            conn.execute(sql, values)

    def complete_sample(self, summary: EvalSampleSummary) -> None:
        with self._get_connection(write=True) as conn:
            summary = self._condense_sample(conn, summary)
            conn.execute(
                """
                UPDATE samples SET data = ? WHERE id = ? and epoch = ?
            """,
                (to_json_str_safe(summary), str(summary.id), summary.epoch),
            )

            key = (str(summary.id), summary.epoch)
            self._msg_indices.pop(key, None)
            self._call_indices.pop(key, None)
            self._completed_samples.add(key)

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        with self._get_connection(write=True) as conn:
            conn.execute(
                """
                UPDATE task_database
                SET metrics = ?,
                    last_updated = CURRENT_TIMESTAMP;
                """,
                [to_json_str_safe(metrics)],
            )

    def remove_samples(self, samples: list[tuple[str | int, int]]) -> None:
        ready: list[tuple[str, int]] = []

        with self._lease_lock:
            for sample_id, epoch in samples:
                key = (str(sample_id), epoch)
                if key in self._sample_read_leases:
                    self._pending_sample_removals.add(key)
                else:
                    ready.append(key)

        if ready:
            self._remove_samples_now(ready)

    def _remove_samples_now(self, samples: list[tuple[str, int]]) -> None:
        # short circuit no samples
        if len(samples) == 0:
            return

        # clear in-memory state
        for key in samples:
            self._msg_indices.pop(key, None)
            self._call_indices.pop(key, None)
            self._completed_samples.discard(key)

        with self._get_connection(write=True) as conn:
            cursor = conn.cursor()
            try:
                BATCH_SIZE = 100
                for i in range(0, len(samples), BATCH_SIZE):
                    # Slice out the batch
                    batch = samples[i : i + BATCH_SIZE]

                    # Build a query using individual column comparisons instead of row values
                    placeholders = " OR ".join(
                        ["(sample_id=? AND sample_epoch=?)" for _ in batch]
                    )

                    # Flatten parameters for binding
                    parameters = [item for tup in batch for item in tup]

                    # Delete associated data
                    for table in ("events", "attachments", "message_pool", "call_pool"):
                        try:
                            cursor.execute(
                                f"DELETE FROM {table} WHERE {placeholders}",
                                parameters,
                            )
                        except OperationalError:
                            pass  # table may not exist in old DBs

                    # Then delete the samples using the same approach
                    placeholders = " OR ".join(["(id=? AND epoch=?)" for _ in batch])

                    samples_query = f"""
                        DELETE FROM samples
                        WHERE {placeholders}
                    """
                    cursor.execute(samples_query, parameters)
            except OperationalError as ex:
                logger.warning(f"Unexpcted error cleaning up samples: {ex}")
            finally:
                cursor.close()

    @override
    def cleanup(self) -> None:
        if not self._close_sync_worker_for_cleanup():
            return

        with self._lease_lock:
            if self._sample_read_leases:
                self._cleanup_pending = True
                return

        self._cleanup_now()

    def _close_sync_worker_for_cleanup(self) -> bool:
        """Close the sync worker before destructive cleanup.

        Returns True when cleanup may proceed. Returns False when cleanup should
        be skipped because cleanup was requested from the sync worker itself or
        the worker did not stop within the cleanup timeout.
        """
        sync_thread: threading.Thread | None = None
        with self._sync_lock:
            self._sync_closed = True
            self._sync_wakeup.notify_all()
            sync_thread = self._sync_thread

        if sync_thread is threading.current_thread():
            logger.warning(
                "Skipping log buffer cleanup from active sync worker for %s",
                self.location,
            )
            return False

        if sync_thread is not None and sync_thread.is_alive():
            sync_thread.join(timeout=SYNC_CLEANUP_TIMEOUT)
            if sync_thread.is_alive():
                logger.warning(
                    "Timed out waiting for log buffer sync; skipping cleanup for %s",
                    self.location,
                )
                return False

        return True

    def _cleanup_now(self) -> None:
        # Close all persistent connections BEFORE unlinking. This is required
        # for correctness on Windows (unlink fails on an open file) and to allow
        # removal of the WAL -wal/-shm sidecars, which stay open as long as a
        # connection is open. The sync worker is already joined by this point
        # (see cleanup -> _close_sync_worker_for_cleanup), so closing its handle
        # cross-thread is safe.
        self._close_all_connections()
        cleanup_sample_buffer_db(self.db_path)
        if self._sync_filestore is not None:
            self._sync_filestore.cleanup()

    def __del__(self) -> None:
        # Best-effort close in case cleanup() was never called (e.g. tests that
        # construct a database without tearing it down). Guard against partial
        # __init__ where connection state may not exist yet.
        if getattr(self, "_connections", None) is not None:
            try:
                self._close_all_connections()
            except Exception:
                pass

    @classmethod
    @override
    def running_tasks(cls, log_dir: str) -> list[str] | None:
        log_subdir = log_dir_hash(filesystem(log_dir).path_as_uri(log_dir))
        db_dir = resolve_db_dir() / log_subdir

        if db_dir.exists():
            logs = [log.name.rsplit(".", 2)[0] for log in db_dir.rglob("*.*.db")]
            return logs
        else:
            return None

    @override
    def get_samples(
        self, etag: str | None = None
    ) -> Samples | Literal["NotModified"] | None:
        if not self.db_path.exists():
            return None

        try:
            with self._get_connection() as conn:
                # note version
                task_data = self._get_task_data(conn)

                # apply etag if requested
                if etag == str(task_data.version):
                    return "NotModified"

                # fetch data
                return Samples(
                    samples=list(self._get_samples(conn, True)),
                    metrics=task_data.metrics,
                    refresh=self.update_interval,
                    etag=str(task_data.version),
                )
        except FileNotFoundError:
            return None

    @override
    def get_sample_data(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        after_attachment_id: int | None = None,
        after_message_pool_id: int | None = None,
        after_call_pool_id: int | None = None,
    ) -> SampleData | None:
        if not self.db_path.exists():
            return None

        try:
            with self._get_connection() as conn:
                # This should be checking whether the sample data actually
                # exists in the database, otherwise once the sample is deleted
                # this will just return no events and no attachments until the
                # entire task is completed.
                row = conn.execute(
                    "SELECT 1 FROM samples WHERE id = ? AND epoch = ?",
                    (str(id), epoch),
                ).fetchone()
                if row is None:
                    return None

                return SampleData(
                    events=list(self._get_events(conn, id, epoch, after_event_id)),
                    attachments=list(
                        self._get_attachments(conn, id, epoch, after_attachment_id)
                    ),
                    message_pool=list(
                        self._get_message_pool(conn, id, epoch, after_message_pool_id)
                    ),
                    call_pool=list(
                        self._get_call_pool(conn, id, epoch, after_call_pool_id)
                    ),
                )
        except FileNotFoundError:
            return None

    def sample_event_count(self, id: str | int, epoch: int) -> int:
        with self._acquire_sample_read_lease(id, epoch):
            with self._get_connection() as conn:
                conn.execute("BEGIN")
                try:
                    cursor = conn.execute(
                        """
                        SELECT COUNT(DISTINCT COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT)))
                        FROM events
                        WHERE sample_id = ? AND sample_epoch = ?
                        """,
                        [str(id), epoch],
                    )
                    count = int(cursor.fetchone()[0])
                    conn.commit()
                    return count
                except Exception:
                    conn.rollback()
                    raise

    def sample_has_event(self, id: str | int, epoch: int, event_id: str) -> bool:
        with self._acquire_sample_read_lease(id, epoch):
            with self._get_connection() as conn:
                conn.execute("BEGIN")
                try:
                    row = conn.execute(
                        """
                        SELECT 1
                        FROM events
                        WHERE sample_id = ?
                          AND sample_epoch = ?
                          AND COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT)) = ?
                        LIMIT 1
                        """,
                        [str(id), epoch, event_id],
                    ).fetchone()
                    conn.commit()
                    return row is not None
                except Exception:
                    conn.rollback()
                    raise

    def sample_attachment(self, id: str | int, epoch: int, hash: str) -> str | None:
        with self._acquire_sample_read_lease(id, epoch):
            with self._get_connection() as conn:
                conn.execute("BEGIN")
                try:
                    row = conn.execute(
                        """
                        SELECT content FROM attachments
                        WHERE sample_id = ? AND sample_epoch = ? AND hash = ?
                        """,
                        [str(id), epoch, hash],
                    ).fetchone()
                    conn.commit()
                    return None if row is None else str(row["content"])
                except Exception:
                    conn.rollback()
                    raise

    def export_transcript_events(
        self, id: str | int, epoch: int, transcript_store: "TranscriptEventSink"
    ) -> int:
        seed_count = 0
        with self._acquire_sample_read_lease(id, epoch):
            with self._get_connection() as conn:
                conn.execute("BEGIN")
                try:
                    pool_attachment_refs: set[str] = set()
                    message_pos_map: dict[int, int] = {}
                    for pos, message_entry in enumerate(
                        self._get_message_pool(conn, id, epoch)
                    ):
                        message_pos_map[pos] = (
                            transcript_store.merge_message_pool_entry(
                                message_entry.msg_id, message_entry.data
                            )
                        )
                        pool_attachment_refs.update(
                            transcript_store.attachment_refs_from_json(
                                message_entry.data
                            )
                        )
                    call_pos_map: dict[int, int] = {}
                    for pos, call_entry in enumerate(
                        self._get_call_pool(conn, id, epoch)
                    ):
                        call_pos_map[pos] = transcript_store.merge_call_pool_entry(
                            call_entry.hash, call_entry.data
                        )
                        pool_attachment_refs.update(
                            transcript_store.attachment_refs_from_json(call_entry.data)
                        )

                    def attachment_lookup(hash: str) -> str | None:
                        row = conn.execute(
                            """
                            SELECT content FROM attachments
                            WHERE sample_id = ? AND sample_epoch = ? AND hash = ?
                            """,
                            [str(id), epoch, hash],
                        ).fetchone()
                        return None if row is None else str(row["content"])

                    transcript_store.merge_attachment_refs(
                        pool_attachment_refs, attachment_lookup
                    )
                    for row in self._get_events(conn, id, epoch, latest_only=True):
                        transcript_store.merge_condensed_event(
                            row.event_id,
                            self._remap_pool_refs(
                                row.event, message_pos_map, call_pos_map
                            ),
                            attachment_lookup,
                        )
                        seed_count += 1
                    conn.commit()
                    return seed_count
                except Exception:
                    conn.rollback()
                    raise

    @staticmethod
    def _remap_pool_refs(
        event: JsonData, message_pos_map: dict[int, int], call_pos_map: dict[int, int]
    ) -> JsonData:
        """Rewrite a condensed event's pool refs after exporting its pool entries."""
        remapped = dict(event)
        input_refs = remapped.get("input_refs")
        if isinstance(input_refs, list):
            remapped["input_refs"] = cast(
                JsonValue, _remap_refs(input_refs, message_pos_map)
            )
        call = remapped.get("call")
        if isinstance(call, dict):
            call_refs = call.get("call_refs")
            if isinstance(call_refs, list):
                remapped["call"] = {
                    **call,
                    "call_refs": cast(JsonValue, _remap_refs(call_refs, call_pos_map)),
                }
        return remapped

    @contextmanager
    def open_sample_history_tail(
        self,
        id: str | int,
        epoch: int,
        n: int,
    ) -> Iterator[SampleHistory]:
        if n <= 0:
            yield SampleHistory([], [], [], {})
            return

        with self._acquire_sample_read_lease(id, epoch):
            with self._get_connection() as conn:
                conn.execute("BEGIN")
                history = self._sample_history(
                    conn, id, epoch, self._get_events_tail(conn, id, epoch, n)
                )
                conn.commit()
            yield history

    @contextmanager
    def open_sample_history_from(
        self,
        id: str | int,
        epoch: int,
        start: int,
        limit: int | None = None,
    ) -> Iterator[SampleHistory]:
        with self._acquire_sample_read_lease(id, epoch):
            with self._get_connection() as conn:
                conn.execute("BEGIN")
                history = self._sample_history(
                    conn,
                    id,
                    epoch,
                    self._get_events_from(conn, id, epoch, start, limit),
                )
                conn.commit()
            yield history

    @contextmanager
    def open_sample_history(
        self,
        id: str | int,
        epoch: int,
    ) -> Iterator[SampleHistory]:
        with self._acquire_sample_read_lease(id, epoch):
            with self._get_connection() as conn:
                conn.execute("BEGIN")
                history = self._sample_history(
                    conn,
                    id,
                    epoch,
                    self._get_events(conn, id, epoch, latest_only=True),
                )
                conn.commit()
            yield history

    def _sample_history(
        self,
        conn: Connection,
        id: str | int,
        epoch: int,
        events: Iterable[EventData],
    ) -> SampleHistory:
        message_pool = [
            json.loads(entry.data) for entry in self._get_message_pool(conn, id, epoch)
        ]
        call_pool = [
            json.loads(entry.data) for entry in self._get_call_pool(conn, id, epoch)
        ]
        attachments = {
            entry.hash: entry.content
            for entry in self._get_attachments(conn, id, epoch)
        }
        return SampleHistory(list(events), message_pool, call_pool, attachments)

    @contextmanager
    def _acquire_sample_read_lease(
        self,
        id: str | int,
        epoch: int,
    ) -> Iterator[None]:
        key = (str(id), epoch)
        with self._lease_lock:
            self._sample_read_leases[key] = self._sample_read_leases.get(key, 0) + 1
        try:
            yield
        finally:
            ready_remove = False
            cleanup_ready = False
            with self._lease_lock:
                lease_count = self._sample_read_leases[key] - 1
                if lease_count > 0:
                    self._sample_read_leases[key] = lease_count
                else:
                    del self._sample_read_leases[key]
                    if key in self._pending_sample_removals:
                        self._pending_sample_removals.remove(key)
                        ready_remove = True
                    if self._cleanup_pending and not self._sample_read_leases:
                        self._cleanup_pending = False
                        cleanup_ready = True
            if ready_remove:
                self._remove_samples_now([key])
            if cleanup_ready:
                self._cleanup_now()

    def _open_connection(self) -> Connection:
        """Open and configure a new SQLite connection (with connect-time retry).

        Opened with check_same_thread=False so the cleanup/finalizer path can
        close a connection owned by another (by then dead) thread. This does
        NOT make the connection safe for concurrent use across threads — each
        connection is only ever used by the thread that opened it.
        """
        max_retries = 5
        retry_delay = 0.1

        conn: Connection | None = None
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                # Re-create the parent directory immediately before connecting
                # (writable connections only).
                if not self._read_only:
                    self.db_path.parent.mkdir(parents=True, exist_ok=True)

                # mode=ro can never (re-)create the file: a connect after
                # the database was deleted raises OperationalError rather
                # than leaving an empty database behind
                database = (
                    f"{self.db_path.as_uri()}?mode=ro"
                    if self._read_only
                    else self.db_path
                )
                conn = sqlite3.connect(
                    database,
                    uri=self._read_only,
                    timeout=30,
                    check_same_thread=False,
                )
                conn.row_factory = sqlite3.Row  # enable row factory for named columns

                # Enable foreign key constraints
                conn.execute("PRAGMA foreign_keys = ON")

                # concurrency setup
                conn.execute("PRAGMA busy_timeout=30000")

                # Use WAL journal mode so concurrent readers (the realtime
                # viewer, the filestore sync thread, and buffer-backed
                # transcript history) don't block the writer and vice-versa.
                # Rollback-journal modes serialize readers and writers, which
                # is the principal cause of "database is locked" errors here.
                # Keep synchronous=OFF: WAL+OFF has the same durability profile
                # as the prior delete+OFF mode (corruption only on OS/power
                # loss, not on a clean process crash) while avoiding the
                # per-commit fsync cost that dominates inference-light evals.
                # (Read-only connections skip these journal/durability writes —
                # they read whatever mode the writer established.)
                if not self._read_only:
                    try:
                        journal_mode = conn.execute(
                            "PRAGMA journal_mode=WAL"
                        ).fetchone()[0]
                    except sqlite3.OperationalError as ex:
                        if "locked" in str(ex):
                            raise
                        journal_mode = f"unavailable: {ex}"

                    if not self._wal_checked:
                        self._wal_checked = True
                        if str(journal_mode).lower() != "wal":
                            logger.warning(
                                "Sample buffer database at %s could not enable WAL "
                                "journal mode (using '%s'); this may lead to "
                                "'database is locked' errors under concurrent "
                                "access. This typically happens when the inspect "
                                "data directory is on a network filesystem.",
                                self.db_path,
                                journal_mode,
                            )
                    conn.execute("PRAGMA synchronous=OFF")
                    # cap WAL growth: truncate the -wal file back down after
                    # checkpoints rather than letting it grow without bound
                    conn.execute("PRAGMA journal_size_limit=134217728")
                conn.execute("PRAGMA cache_size=-64000")
                conn.execute("PRAGMA temp_store=MEMORY")

                return conn

            except sqlite3.OperationalError as e:
                last_error = e
                if conn is not None:
                    conn.close()
                    conn = None
                # "locked" is always transient. "unable to open database file"
                # is retryable only for writable connections: it usually means a
                # sibling rmdir'd our shared log directory, which the mkdir above
                # re-creates on the next attempt. For read_only connections it is
                # the intended "buffer is gone" signal and must propagate so
                # callers can degrade (see _control/events.py).
                msg = str(e)
                retryable = "locked" in msg or (
                    not self._read_only and "unable to open database file" in msg
                )
                if retryable and attempt < max_retries - 1:
                    time.sleep(retry_delay * (2**attempt))
                    continue
                raise
            except BaseException:
                # close any half-open connection before propagating a
                # non-retryable error raised during connect/PRAGMA setup
                if conn is not None:
                    conn.close()
                raise

        raise sqlite3.OperationalError(
            f"Failed to establish connection after {max_retries} attempts"
        ) from last_error

    def _thread_connection(self) -> Connection:
        """Return this thread's persistent connection, opening one if needed."""
        if self._closed:
            raise RuntimeError("SampleBufferDatabase used after cleanup")
        conn: Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open_connection()
            with self._connections_lock:
                # re-check under the lock: if cleanup() won the race while we
                # were opening, discard this connection rather than tracking and
                # using a handle to an already-unlinked database
                if self._closed:
                    conn.close()
                    raise RuntimeError("SampleBufferDatabase used after cleanup")
                self._local.conn = conn
                self._connections.append(conn)
        return conn

    def _discard_thread_connection(self, conn: Connection) -> None:
        """Drop a (possibly poisoned) connection so the next op reopens a fresh one."""
        if getattr(self._local, "conn", None) is conn:
            self._local.conn = None
        with self._connections_lock:
            try:
                self._connections.remove(conn)
            except ValueError:
                pass
        try:
            conn.close()
        except Exception:
            pass

    def _close_all_connections(self) -> None:
        """Close every tracked connection (cleanup/finalizer).

        Precondition: no other thread may be mid-operation on a tracked
        connection when this runs (closing a connection in use from another
        thread is undefined even with check_same_thread=False). This holds
        because callers either (a) join the filestore sync worker first
        (_close_sync_worker_for_cleanup, which aborts cleanup if the join times
        out) and (b) run on the single event-loop thread that performs all other
        DB access — so that thread is never mid-op while calling cleanup. The
        _closed flag (set here, re-checked under the lock in _thread_connection)
        closes the remaining "open racing with close" window. Offloading a DB
        operation to another non-joined thread would break this precondition.
        """
        with self._connections_lock:
            self._closed = True
            conns, self._connections = self._connections, []
        for conn in conns:
            try:
                conn.close()
            except Exception:
                pass
        # clear the calling thread's handle (other threads are no longer running)
        self._local.conn = None

    @contextmanager
    def _get_connection(
        self,
        *,
        write: bool = False,
        on_rollback: Callable[[], None] | None = None,
    ) -> Iterator[Connection]:
        """Get this thread's persistent database connection.

        The connection is reused across operations rather than opened/closed per
        call. IMPORTANT: the body of a `with _get_connection()` block must remain
        await-free — an `await` between acquiring the connection and committing
        would let another anyio task run a statement on the same shared
        connection mid-transaction.
        """
        conn = self._thread_connection()

        try:
            # do work
            yield conn

            # if this was for a write then bump the version
            if write:
                conn.execute("""
                UPDATE task_database
                SET version = version + 1,
                    last_updated = CURRENT_TIMESTAMP;
                """)

            # commit
            conn.commit()

        except Exception:
            # roll back, then self-heal by discarding the connection so the next
            # op on this thread transparently reopens a fresh one. Buffer-write
            # errors are swallowed by the caller (Transcript._notify_subscribers),
            # so a wedged connection would otherwise silently disable realtime
            # logging for the rest of the run. on_rollback always fires (even if
            # rollback() raises) and the original exception is re-raised.
            try:
                conn.rollback()
            except Exception:
                pass
            finally:
                self._discard_thread_connection(conn)
                if on_rollback is not None:
                    on_rollback()
            raise
        finally:
            # if this was for write then sync (throttled). Note: no conn.close()
            # here — the connection persists and is closed at cleanup.
            if write:
                self._sync()

    @property
    def shared_sync_interval(self) -> int | None:
        """Effective shared-log sync interval in seconds, or None when off.

        ``log_shared`` carries the raw configured value, but a normal CLI run
        passes ``0`` ("off") which is stored as ``0`` yet never creates a
        filestore. Shared sync is actually running only when a filestore was
        created (``log_shared`` truthy at construction). This collapses both
        ``0`` and "no filestore" to ``None`` so callers report a single "off"
        signal rather than a misleading ``0s`` interval.
        """
        return self.log_shared if self._sync_filestore is not None else None

    def set_sync_interval(self, seconds: int) -> bool:
        """Change the interval for syncing buffered events to the shared log dir.

        Only meaningful when this buffer is syncing to a shared (eg. S3) log
        directory — i.e. it was opened with a ``log_shared`` interval. Lowering
        the interval makes in-progress sample events appear in the shared log
        sooner; raising it reduces remote-write frequency. The running sync
        worker picks up the new interval on its next wake-up.

        Args:
            seconds: New sync interval, in seconds (clamped to a minimum of 1).

        Returns:
            True if the interval was updated, False if this buffer has no
            shared-log sync configured (nothing to retune).
        """
        if self.log_shared is None or self._sync_filestore is None:
            return False
        with self._sync_lock:
            self.log_shared = max(1, seconds)
            self._sync_filestore.update_interval = self.log_shared
            # wake the worker so it recomputes its wait against the new interval
            self._sync_wakeup.notify_all()
        return True

    def _sync(self) -> None:
        sync_filestore = self._sync_filestore
        if self.log_shared is None or sync_filestore is None:
            return

        with self._sync_lock:
            if self._sync_closed:
                return

            self._sync_requested = True
            self._sync_pending = True

            if self._sync_thread is None or not self._sync_thread.is_alive():
                self._sync_thread = threading.Thread(
                    target=self._sync_to_filestore,
                    args=(sync_filestore,),
                    daemon=True,
                    name="inspect-buffer-sync",
                )
                self._sync_thread.start()

            self._sync_wakeup.notify_all()

    def _sync_to_filestore(self, sync_filestore: SampleBufferFilestore) -> None:
        while True:
            with self._sync_lock:
                while not self._sync_closed:
                    assert self.log_shared is not None
                    remaining = self.log_shared - (time.monotonic() - self._sync_time)
                    if self._sync_requested and remaining <= 0:
                        self._sync_requested = False
                        self._sync_pending = False
                        self._sync_time = time.monotonic()
                        break

                    timeout = max(remaining, 0) if self._sync_requested else None
                    self._sync_wakeup.wait(timeout=timeout)
                else:
                    self._sync_thread = None
                    return

            try:
                with trace_action(logger, "Log Sync", self.location):
                    sync_to_filestore(self, sync_filestore)
            except Exception:
                logger.exception("Log Sync failed for %s", self.location)
            except BaseException:
                with self._sync_lock:
                    self._sync_requested = False
                    self._sync_pending = False
                    self._sync_thread = None
                raise

    def _get_task_data(self, conn: Connection) -> TaskData:
        row = conn.execute("SELECT version, metrics FROM task_database").fetchone()
        task_data = dict(version=row["version"], metrics=json.loads(row["metrics"]))
        return TaskData(**task_data)

    def _get_samples(
        self,
        conn: Connection,
        resolve_attachments: bool | Literal["full", "core"] = False,
    ) -> Iterator[EvalSampleSummary]:
        cursor = conn.execute(
            """
            SELECT s.data as sample_data
            FROM samples s
            ORDER BY s.id
        """
        )

        for row in cursor:
            summary = EvalSampleSummary.model_validate_json(row["sample_data"])
            if resolve_attachments:
                summary = self._resolve_sample_attachments(conn, summary)
            yield summary

    def _get_events(
        self,
        conn: Connection,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        resolve_attachments: bool | Literal["full", "core"] = False,
        latest_only: bool = False,
    ) -> Iterator[EventData]:
        if latest_only:
            query = """
                WITH first_rows AS (
                    SELECT
                        COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT)) AS logical_id,
                        MIN(id) AS first_id,
                        MAX(id) AS latest_id
                    FROM events
                    WHERE sample_id = ? AND sample_epoch = ?
                    GROUP BY COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT))
                )
                SELECT e.id, fr.logical_id AS event_id, e.data
                FROM first_rows fr
                JOIN events e ON e.id = fr.latest_id
                ORDER BY fr.first_id
            """
            params: list[str | int] = [str(id), epoch]
        else:
            query = """
                SELECT id, COALESCE(NULLIF(e.event_id, ''), CAST(e.id AS TEXT)) AS event_id, data
                FROM events e WHERE sample_id = ? AND sample_epoch = ?
            """
            params = [str(id), epoch]

            if after_event_id is not None:
                query += " AND e.id > ?"
                params.append(after_event_id)

            query += " ORDER BY e.id"

        cursor = conn.execute(query, params)

        message_cache: dict[str, tuple[ChatMessage, ChatMessage]] = {}

        for row in cursor:
            event = json.loads(row["data"])
            if resolve_attachments is True or resolve_attachments == "full":
                event = self._resolve_event_attachments(conn, event, message_cache)
            yield EventData(
                id=row["id"],
                event_id=row["event_id"],
                sample_id=str(id),
                epoch=epoch,
                event=event,
            )

    def _get_events_tail(
        self,
        conn: Connection,
        id: str | int,
        epoch: int,
        n: int,
    ) -> Iterator[EventData]:
        query = """
            WITH first_rows AS (
                SELECT
                    COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT)) AS logical_id,
                    MIN(id) AS first_id,
                    MAX(id) AS latest_id
                FROM events
                WHERE sample_id = ? AND sample_epoch = ?
                GROUP BY COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT))
            ), tail_rows AS (
                SELECT logical_id, first_id, latest_id
                FROM first_rows
                ORDER BY first_id DESC
                LIMIT ?
            )
            SELECT e.id, tr.logical_id AS event_id, e.data
            FROM tail_rows tr
            JOIN events e ON e.id = tr.latest_id
            ORDER BY tr.first_id
        """
        cursor = conn.execute(query, [str(id), epoch, n])

        for row in cursor:
            event = json.loads(row["data"])
            yield EventData(
                id=row["id"],
                event_id=row["event_id"],
                sample_id=str(id),
                epoch=epoch,
                event=event,
            )

    def _get_events_from(
        self,
        conn: Connection,
        id: str | int,
        epoch: int,
        start: int,
        limit: int | None = None,
    ) -> Iterator[EventData]:
        # LIMIT -1 is SQLite's "no limit", so the cap can ride the query
        # unconditionally.
        query = """
            WITH first_rows AS (
                SELECT
                    COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT)) AS logical_id,
                    MIN(id) AS first_id,
                    MAX(id) AS latest_id
                FROM events
                WHERE sample_id = ? AND sample_epoch = ?
                GROUP BY COALESCE(NULLIF(event_id, ''), CAST(id AS TEXT))
            ), ordered_rows AS (
                SELECT logical_id, latest_id, ROW_NUMBER() OVER (ORDER BY first_id) AS row_num
                FROM first_rows
            )
            SELECT e.id, ordered_rows.logical_id AS event_id, e.data
            FROM ordered_rows
            JOIN events e ON e.id = ordered_rows.latest_id
            WHERE ordered_rows.row_num > ?
            ORDER BY ordered_rows.row_num
            LIMIT ?
        """
        cursor = conn.execute(
            query, [str(id), epoch, start, -1 if limit is None else limit]
        )

        for row in cursor:
            event = json.loads(row["data"])
            yield EventData(
                id=row["id"],
                event_id=row["event_id"],
                sample_id=str(id),
                epoch=epoch,
                event=event,
            )

    def _get_attachments(
        self,
        conn: Connection,
        id: str | int,
        epoch: int,
        after_attachment_id: int | None = None,
    ) -> Iterator[AttachmentData]:
        query = """
            SELECT id, hash, content FROM attachments
            WHERE sample_id = ? AND sample_epoch = ?
        """
        params: list[str | int] = [id, epoch]

        if after_attachment_id is not None:
            query += " AND id > ?"
            params.append(after_attachment_id)

        query += " ORDER BY id"

        cursor = conn.execute(query, params)

        for row in cursor:
            yield AttachmentData(
                id=row["id"],
                sample_id=str(id),
                epoch=epoch,
                hash=row["hash"],
                content=row["content"],
            )

    def _get_message_pool(
        self,
        conn: Connection,
        id: str | int,
        epoch: int,
        after_id: int | None = None,
    ) -> Iterator[MessagePoolData]:
        query = """
            SELECT id, msg_id, data FROM message_pool
            WHERE sample_id = ? AND sample_epoch = ?
        """
        params: list[str | int] = [str(id), epoch]
        if after_id is not None:
            query += " AND id > ?"
            params.append(after_id)
        query += " ORDER BY id"
        for row in conn.execute(query, params):
            yield MessagePoolData(
                id=row["id"],
                sample_id=str(id),
                epoch=epoch,
                msg_id=row["msg_id"],
                data=row["data"],
            )

    def _get_call_pool(
        self,
        conn: Connection,
        id: str | int,
        epoch: int,
        after_id: int | None = None,
    ) -> Iterator[CallPoolData]:
        query = """
            SELECT id, hash, data FROM call_pool
            WHERE sample_id = ? AND sample_epoch = ?
        """
        params: list[str | int] = [str(id), epoch]
        if after_id is not None:
            query += " AND id > ?"
            params.append(after_id)
        query += " ORDER BY id"
        for row in conn.execute(query, params):
            yield CallPoolData(
                id=row["id"],
                sample_id=str(id),
                epoch=epoch,
                hash=row["hash"],
                data=row["data"],
            )

    def _condense_sample(
        self, conn: Connection, sample: EvalSampleSummary
    ) -> EvalSampleSummary:
        # alias attachments
        attachments: dict[str, str] = {}
        sample = sample.model_copy(
            update={
                "input": walk_input(
                    sample.input,
                    self._create_attachments_content_fn(attachments),
                    WalkContext(message_cache={}, only_core=False),
                )
            }
        )

        # insert attachments
        self._insert_attachments(conn, sample.id, sample.epoch, attachments)

        # return sample with aliases
        return sample

    def _resolve_sample_attachments(
        self, conn: Connection, sample: EvalSampleSummary
    ) -> EvalSampleSummary:
        return sample.model_copy(
            update={
                "input": walk_input(
                    sample.input,
                    self._resolve_attachments_content_fn(conn),
                    WalkContext(message_cache={}, only_core=False),
                )
            }
        )

    def _condense_event(self, conn: Connection, event: SampleEvent) -> SampleEvent:
        if isinstance(event.event, ModelEvent):
            return self._condense_model_event(conn, event, event.event)

        # alias attachments
        attachments: dict[str, str] = {}
        event.event = walk_events(
            [event.event],
            self._create_attachments_content_fn(attachments),
            WalkContext(message_cache={}, only_core=False),
        )[0]

        # insert attachments
        self._insert_attachments(conn, event.id, event.epoch, attachments)
        return event

    def _condense_model_event(
        self, conn: Connection, event: SampleEvent, model_event: ModelEvent
    ) -> SampleEvent:
        key = (str(event.id), event.epoch)
        if key in self._completed_samples:
            raise RuntimeError(
                f"ModelEvent for sample {key} arrived after "
                "complete_sample; this would corrupt buffer DB pool "
                "indices."
            )

        msg_index = self._msg_indices.get(key)
        if msg_index is None:
            msg_index = self._msg_indices[key] = MessagePoolIndex()
        call_index = self._call_indices.get(key)
        if call_index is None:
            call_index = self._call_indices[key] = CallPoolIndex()

        attachments: dict[str, str] = {}
        content_fn = self._create_attachments_content_fn(attachments)
        context = WalkContext(message_cache={}, only_core=False)

        # positions derive from index size: valid only because the condense
        # helper registers each add_message/add_call result in the index
        # before the next call (see condense_model_event_with_indices), so
        # size == rows already inserted for this sample
        def add_message(hash_value: str, walked: ChatMessage) -> int:
            index = msg_index.size
            self._insert_message_pool_entry(
                conn, event.id, event.epoch, hash_value, walked
            )
            return index

        def add_call(hash_value: str, walked: JsonValue) -> int:
            index = call_index.size
            self._insert_call_pool_entry(
                conn, event.id, event.epoch, hash_value, walked
            )
            return index

        condensed = condense_model_event_with_indices(
            model_event,
            messages=msg_index,
            calls=call_index,
            walk_message=lambda m: walk_chat_message(m, content_fn, context),
            walk_call_message=lambda v: walk_json_value(v, content_fn, context),
            add_message=add_message,
            add_call=add_call,
        )

        # walk the remainder (input now [], call request without messages)
        condensed_event = walk_events([condensed], content_fn, context)[0]
        self._insert_attachments(conn, event.id, event.epoch, attachments)
        return SampleEvent(id=event.id, epoch=event.epoch, event=condensed_event)

    def _resolve_event_attachments(
        self,
        conn: Connection,
        event: JsonData,
        message_cache: dict[str, tuple[ChatMessage, ChatMessage]],
    ) -> JsonData:
        return walk_json_dict(
            event,
            self._resolve_attachments_content_fn(conn),
            WalkContext(message_cache=message_cache, only_core=False),
        )

    def _create_attachments_content_fn(
        self, attachments: dict[str, str]
    ) -> Callable[[str], str]:
        return attachments_content_fn(self.log_images, 100, attachments)

    def _resolve_attachments_content_fn(self, conn: Connection) -> Callable[[str], str]:
        def content_fn(text: str) -> str:
            if text.startswith(ATTACHMENT_PROTOCOL):
                hash = text.replace(ATTACHMENT_PROTOCOL, "", 1)
                attachments = self._get_attachments_content(conn, [hash])
                content = attachments.get(hash, None)
                if content is not None:
                    return content
                else:
                    return text
            else:
                return text

        return content_fn

    def _insert_attachments(
        self, conn: Connection, id: int | str, epoch: int, attachments: dict[str, str]
    ) -> None:
        parameters: list[list[int | str]] = []
        for k, v in attachments.items():
            parameters.append([id, epoch, k, v])

        conn.executemany(
            """
            INSERT OR IGNORE INTO attachments (sample_id, sample_epoch, hash, content)
            VALUES (?, ?, ?, ?)
            """,
            parameters,
        )

    def _insert_message_pool_entry(
        self,
        conn: Connection,
        sample_id: str | int,
        epoch: int,
        msg_id: str,
        msg: ChatMessage,
    ) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO message_pool (sample_id, sample_epoch, msg_id, data) VALUES (?, ?, ?, ?)",
            (str(sample_id), epoch, msg_id, _msg_pool_json(_msg_pool_jsonable(msg))),
        )

    def _insert_call_pool_entry(
        self,
        conn: Connection,
        sample_id: str | int,
        epoch: int,
        hash: str,
        call_msg: JsonValue,
    ) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO call_pool (sample_id, sample_epoch, hash, data) VALUES (?, ?, ?, ?)",
            (str(sample_id), epoch, hash, _call_pool_json(call_msg)),
        )

    def _get_attachments_content(
        self, conn: Connection, hashes: list[str]
    ) -> dict[str, str | None]:
        # Create placeholders for the IN clause
        placeholders = ",".join("?" * len(hashes))

        cursor = conn.execute(
            f"""
            SELECT hash, content
            FROM attachments
            WHERE hash IN ({placeholders})
            """,
            hashes,
        )

        # Create result dictionary with all requested hashes initialized to None
        results: dict[str, str | None] = {hash_: None for hash_ in hashes}

        # Update with found values
        for row in cursor:
            results[row["hash"]] = row["content"]

        return results


def sync_to_filestore(
    db: SampleBufferDatabase, filestore: SampleBufferFilestore
) -> None:
    # read existing manifest (create an empty one if there is none)
    manifest = filestore.read_manifest() or Manifest()

    # prepare a list of buffered samples from the db
    samples = db.get_samples()
    if samples is None:
        return
    assert isinstance(samples, Samples)

    # at the end of the sync, the manifest should contain only the samples
    # in the db -- create a new list of sample manifests propagating the
    # segment lists from the existing sample manifests
    sample_manifests: list[SampleManifest] = []
    for sample in samples.samples:
        # lookup sample segments in the existing manifest
        # Copy before appending the next segment below.
        segments = list(
            next(
                (
                    s.segments
                    for s in manifest.samples
                    if s.summary.id == sample.id and s.summary.epoch == sample.epoch
                ),
                [],
            )
        )
        # add to manifests
        sample_manifests.append(SampleManifest(summary=sample, segments=segments))

    # draft of new manifest has the new sample list and the existing segments
    manifest.metrics = samples.metrics
    manifest.samples = sample_manifests

    # determine what segment data we already have so we can limit
    # sample queries accordingly
    if len(manifest.segments) > 0:
        last_segment = manifest.segments[-1]
        last_segment_id = last_segment.id
    else:
        last_segment_id = 0

    # work through samples and create segment files for those that need it
    # (update the manifest with the segment id). track the largest event
    # and attachment ids we've seen
    segment_id = last_segment_id + 1
    last_event_id = 0
    last_attachment_id = 0
    last_message_pool_id = 0
    last_call_pool_id = 0
    segment_files: list[SegmentFile] = []
    segment_by_id = {seg.id: seg for seg in manifest.segments}
    for manifest_sample in manifest.samples:
        # take the max of last_*_id across all of this sample's segments, not
        # just the latest: each segment's last_*_id is 0 if no items of that
        # type were added there, so the latest alone can regress the cursor.
        after_event_id = 0
        after_attachment_id = 0
        after_message_pool_id = 0
        after_call_pool_id = 0
        for sample_segment in manifest_sample.segments:
            seg = sample_segment_cursor(sample_segment, segment_by_id)
            if seg is not None:
                after_event_id = max(after_event_id, seg.last_event_id)
                after_attachment_id = max(after_attachment_id, seg.last_attachment_id)
                after_message_pool_id = max(
                    after_message_pool_id, seg.last_message_pool_id
                )
                after_call_pool_id = max(after_call_pool_id, seg.last_call_pool_id)

        # get sample data
        sample_data = db.get_sample_data(
            id=manifest_sample.summary.id,
            epoch=manifest_sample.summary.epoch,
            after_event_id=after_event_id,
            after_attachment_id=after_attachment_id,
            after_message_pool_id=after_message_pool_id,
            after_call_pool_id=after_call_pool_id,
        )
        # if we got sample data....
        if sample_data is not None and (
            len(sample_data.events) > 0
            or len(sample_data.attachments) > 0
            or len(sample_data.message_pool) > 0
            or len(sample_data.call_pool) > 0
        ):
            (
                segment_last_event_id,
                segment_last_attachment_id,
                segment_last_message_pool_id,
                segment_last_call_pool_id,
            ) = maximum_ids(0, 0, 0, 0, sample_data)

            # add to segment file
            segment_files.append(
                SegmentFile(
                    id=manifest_sample.summary.id,
                    epoch=manifest_sample.summary.epoch,
                    data=sample_data,
                )
            )
            # update manifest
            manifest_sample.segments.append(
                SampleSegment(
                    id=segment_id,
                    last_event_id=segment_last_event_id,
                    last_attachment_id=segment_last_attachment_id,
                    last_message_pool_id=segment_last_message_pool_id,
                    last_call_pool_id=segment_last_call_pool_id,
                )
            )

            # update maximums
            last_event_id = max(last_event_id, segment_last_event_id)
            last_attachment_id = max(last_attachment_id, segment_last_attachment_id)
            last_message_pool_id = max(
                last_message_pool_id, segment_last_message_pool_id
            )
            last_call_pool_id = max(last_call_pool_id, segment_last_call_pool_id)

    # write the segment file and update the manifest
    if len(segment_files) > 0:
        filestore.write_segment(segment_id, segment_files)
        manifest.segments.append(
            Segment(
                id=segment_id,
                last_event_id=last_event_id,
                last_attachment_id=last_attachment_id,
                last_message_pool_id=last_message_pool_id,
                last_call_pool_id=last_call_pool_id,
            )
        )

    # write the manifest (do this even if we had no segments to pickup adds/deletes)
    filestore.write_manifest(manifest)


def maximum_ids(
    event_id: int,
    attachment_id: int,
    message_pool_id: int,
    call_pool_id: int,
    sample_data: SampleData,
) -> tuple[int, int, int, int]:
    # SampleData lists must be ordered by row id; latest_only event lists are not.
    if sample_data.events:
        event_id = max(event_id, sample_data.events[-1].id)
    if sample_data.attachments:
        attachment_id = max(attachment_id, sample_data.attachments[-1].id)
    if sample_data.message_pool:
        message_pool_id = max(message_pool_id, sample_data.message_pool[-1].id)
    if sample_data.call_pool:
        call_pool_id = max(call_pool_id, sample_data.call_pool[-1].id)
    return event_id, attachment_id, message_pool_id, call_pool_id


def _remap_refs(
    refs: Sequence[object], pos_map: dict[int, int]
) -> list[tuple[int, int]]:
    """Translate pooled ref ranges after exporting pool entries into a new store."""
    indices: list[int] = []
    for ref in refs:
        if not isinstance(ref, (list, tuple)) or len(ref) != 2:
            continue
        start, end = ref
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        indices.extend(pos_map[index] for index in range(start, end))
    return _compress_refs(indices)


def cleanup_sample_buffer_databases(db_dir: Path | None = None) -> None:
    try:
        db_dir = resolve_db_dir(db_dir)
        for db in db_dir.rglob("*.*.db"):
            # this is a failsafe cleanup method for buffer db's leaked during
            # abnormal terminations. therefore, it's not critical that we clean
            # it up immediately. it's also possible that users are _sharing_
            # their inspect_data_dir across multiple pid namespaces (e.g. in an
            # effort to share their cache) one eval could remove the db of
            # another running eval if we don't put in a delay.
            if is_file_older_than(db, datetime.timedelta(days=3), default=False):
                _, pid_str, _ = db.name.rsplit(".", 2)
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if not psutil.pid_exists(pid):
                        cleanup_sample_buffer_db(db)
    except Exception as ex:
        logger.warning(f"Error cleaning up sample buffer databases at {db_dir}: {ex}")


def cleanup_sample_buffer_db(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        # remove WAL sidecar files (present when journal_mode=WAL)
        path.with_name(f"{path.name}-wal").unlink(missing_ok=True)
        path.with_name(f"{path.name}-shm").unlink(missing_ok=True)
        try:
            # Remove the directory if it's empty
            path.parent.rmdir()
        except OSError:
            # Not empty or other error, which is fine
            pass
    except Exception as ex:
        logger.warning(f"Error cleaning up sample buffer database at {path}: {ex}")


def resolve_db_dir(db_dir: Path | None = None) -> Path:
    return db_dir or inspect_data_dir("samplebuffer")


def location_dir_and_file(location: str) -> tuple[str, str]:
    dir = log_dir_hash(dirname(location))
    file = basename(location)
    return dir, file


def log_dir_hash(log_dir: str) -> str:
    log_dir = log_dir.rstrip("/\\")
    return hashlib.sha256(log_dir.encode()).hexdigest()
