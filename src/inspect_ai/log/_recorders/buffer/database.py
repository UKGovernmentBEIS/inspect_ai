import datetime
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from sqlite3 import Connection, OperationalError
from typing import Callable, Iterator, Literal

import psutil
from pydantic import BaseModel
from shortuuid import uuid
from typing_extensions import override

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.dateutil import is_file_older_than
from inspect_ai._util.file import basename, dirname, filesystem
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.trace import trace_action

from ..._condense import (
    ATTACHMENT_PROTOCOL,
    attachments_content_fn,
    walk_events,
    walk_input,
    walk_json_dict,
)
from ..._log import EvalSampleSummary
from ..types import SampleEvent
from .filestore import (
    Manifest,
    SampleBufferFilestore,
    SampleManifest,
    Segment,
    SegmentFile,
)
from .types import (
    AttachmentData,
    EventData,
    JsonData,
    SampleBuffer,
    SampleData,
    Samples,
)

logger = getLogger(__name__)


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

    CREATE TABLE attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id TEXT,
        sample_epoch INTEGER,
        hash TEXT UNIQUE,
        content TEXT
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
        log_images: bool = True,
        log_shared: int | None = None,
        update_interval: int = 2,
        db_dir: Path | None = None,
    ):
        self.location = filesystem(location).path_as_uri(location)
        self.log_images = log_images
        self.log_shared = log_shared
        self.update_interval = update_interval

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
                raise FileNotFoundError("Log database for '{location}' not found.")

        # create sync filestore if log_shared
        self._sync_filestore = (
            SampleBufferFilestore(location, update_interval=log_shared)
            if log_shared
            else None
        )
        self._sync_time = time.monotonic()

    def start_sample(self, sample: EvalSampleSummary) -> None:
        with self._get_connection(write=True) as conn:
            sample = self._consense_sample(conn, sample)
            conn.execute(
                """
                INSERT INTO samples (id, epoch, data)
                VALUES (?, ?, ?)
            """,
                (str(sample.id), sample.epoch, to_json_str_safe(sample)),
            )

    def log_events(self, events: list[SampleEvent]) -> None:
        with self._get_connection(write=True) as conn:
            # collect the values for all events
            values: list[str | int] = []
            for event in events:
                event = self._consense_event(conn, event)
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
            summary = self._consense_sample(conn, summary)
            conn.execute(
                """
                UPDATE samples SET data = ? WHERE id = ? and epoch = ?
            """,
                (to_json_str_safe(summary), str(summary.id), summary.epoch),
            )

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
        # short circuit no samples
        if len(samples) == 0:
            return

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

                    # Delete associated events first
                    events_query = f"""
                        DELETE FROM events
                        WHERE {placeholders}
                    """
                    cursor.execute(events_query, parameters)

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

    def cleanup(self) -> None:
        cleanup_sample_buffer_db(self.db_path)
        if self._sync_filestore is not None:
            self._sync_filestore.cleanup()

    @classmethod
    @override
    def running_tasks(cls, log_dir: str) -> list[str] | None:
        log_subdir = log_dir_hash(log_dir)
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
    ) -> SampleData | None:
        if not self.db_path.exists():
            return None

        try:
            with self._get_connection() as conn:
                return SampleData(
                    events=list(self._get_events(conn, id, epoch, after_event_id)),
                    attachments=list(
                        self._get_attachments(conn, id, epoch, after_attachment_id)
                    ),
                )
        except FileNotFoundError:
            return None

    @contextmanager
    def _get_connection(self, *, write: bool = False) -> Iterator[Connection]:
        """Get a database connection."""
        max_retries = 5
        retry_delay = 0.1

        conn: Connection | None = None
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30)
                conn.row_factory = sqlite3.Row  # enable row factory for named columns

                # Enable foreign key constraints
                conn.execute("PRAGMA foreign_keys = ON")

                # concurrency setup
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA synchronous=OFF")
                conn.execute("PRAGMA cache_size=-64000")
                conn.execute("PRAGMA temp_store=MEMORY")

                break

            except sqlite3.OperationalError as e:
                last_error = e
                if "locked" in str(e) and attempt < max_retries - 1:
                    if conn:
                        conn.close()
                    time.sleep(retry_delay * (2**attempt))
                    continue
                raise

        # ensure we have a connection
        if conn is None:
            raise sqlite3.OperationalError(
                f"Failed to establish connection after {max_retries} attempts"
            ) from last_error

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
            # rollback on any error
            conn.rollback()
            raise
        finally:
            # close the connection
            conn.close()

            # if this was for write then sync (throttled)
            if write:
                self._sync()

    def _sync(self) -> None:
        if self.log_shared is not None and self._sync_filestore is not None:
            if (time.monotonic() - self._sync_time) > self.log_shared:
                with trace_action(logger, "Log Sync", self.location):
                    sync_to_filestore(self, self._sync_filestore)

                self._sync_time = time.monotonic()

    def _increment_version(self, conn: Connection) -> None:
        conn.execute("""
        UPDATE task_database
        SET version = version + 1,
            last_updated = CURRENT_TIMESTAMP;
        """)

    def _get_task_data(self, conn: Connection) -> TaskData:
        row = conn.execute("SELECT version, metrics FROM task_database").fetchone()
        task_data = dict(version=row["version"], metrics=json.loads(row["metrics"]))
        return TaskData(**task_data)

    def _get_samples(
        self, conn: Connection, resolve_attachments: bool = False
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
        resolve_attachments: bool = False,
    ) -> Iterator[EventData]:
        query = """
            SELECT id, event_id, data
            FROM events e WHERE sample_id = ? AND sample_epoch = ?
        """
        params: list[str | int] = [str(id), epoch]

        if after_event_id is not None:
            query += " AND e.id > ?"
            params.append(after_event_id)

        query += " ORDER BY e.id"

        cursor = conn.execute(query, params)

        for row in cursor:
            event = json.loads(row["data"])
            if resolve_attachments:
                event = self._resolve_event_attachments(conn, event)
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

        cursor = conn.execute(query, params)

        for row in cursor:
            yield AttachmentData(
                id=row["id"],
                sample_id=str(id),
                epoch=epoch,
                hash=row["hash"],
                content=row["content"],
            )

    def _consense_sample(
        self, conn: Connection, sample: EvalSampleSummary
    ) -> EvalSampleSummary:
        # alias attachments
        attachments: dict[str, str] = {}
        sample = sample.model_copy(
            update={
                "input": walk_input(
                    sample.input, self._create_attachments_content_fn(attachments)
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
                    sample.input, self._resolve_attachments_content_fn(conn)
                )
            }
        )

    def _consense_event(self, conn: Connection, event: SampleEvent) -> SampleEvent:
        # alias attachments
        attachments: dict[str, str] = {}
        event.event = walk_events(
            [event.event], self._create_attachments_content_fn(attachments)
        )[0]

        # insert attachments
        self._insert_attachments(conn, event.id, event.epoch, attachments)

        # return events with aliases
        return event

    def _resolve_event_attachments(self, conn: Connection, event: JsonData) -> JsonData:
        return walk_json_dict(event, self._resolve_attachments_content_fn(conn))

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
        segments: list[int] = next(
            (
                s.segments
                for s in manifest.samples
                if s.summary.id == sample.id and s.summary.epoch == sample.epoch
            ),
            [],
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
    segment_files: list[SegmentFile] = []
    for manifest_sample in manifest.samples:
        # get last ids we've seen for this sample
        sample_last_segment_id = (
            manifest_sample.segments[-1] if manifest_sample.segments else None
        )
        sample_last_segment = next(
            (
                segment
                for segment in manifest.segments
                if segment.id == sample_last_segment_id
            ),
            None,
        )
        if sample_last_segment is not None:
            after_event_id = sample_last_segment.last_event_id
            after_attachment_id = sample_last_segment.last_attachment_id
        else:
            after_event_id, after_attachment_id = (0, 0)

        # get sample data
        sample_data = db.get_sample_data(
            id=manifest_sample.summary.id,
            epoch=manifest_sample.summary.epoch,
            after_event_id=after_event_id,
            after_attachment_id=after_attachment_id,
        )
        # if we got sample data....
        if sample_data is not None and (
            len(sample_data.events) > 0 or len(sample_data.attachments) > 0
        ):
            # add to segment file
            segment_files.append(
                SegmentFile(
                    id=manifest_sample.summary.id,
                    epoch=manifest_sample.summary.epoch,
                    data=sample_data,
                )
            )
            # update manifest
            manifest_sample.segments.append(segment_id)

            # update maximums
            last_event_id, last_attachment_id = maximum_ids(
                last_event_id, last_attachment_id, sample_data
            )

    # write the segment file and update the manifest
    if len(segment_files) > 0:
        filestore.write_segment(segment_id, segment_files)
        manifest.segments.append(
            Segment(
                id=segment_id,
                last_event_id=last_event_id,
                last_attachment_id=last_attachment_id,
            )
        )

    # write the manifest (do this even if we had no segments to pickup adds/deletes)
    filestore.write_manifest(manifest)


def maximum_ids(
    event_id: int, attachment_id: int, sample_data: SampleData
) -> tuple[int, int]:
    if sample_data.events:
        event_id = max(event_id, sample_data.events[-1].id)
    if sample_data.attachments:
        attachment_id = max(attachment_id, sample_data.attachments[-1].id)
    return event_id, attachment_id


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
